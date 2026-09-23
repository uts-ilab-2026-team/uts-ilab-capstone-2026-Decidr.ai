"""Domain-independent representation recovery; never supplies missing business facts."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
import re
import unicodedata


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str


class CriticalInterpretationError(ValueError):
    def __init__(self, message: str, code: str = 'critical_semantics'):
        super().__init__(message)
        self.issue = ValidationIssue(code, 'critical', message)


CRITICAL_ERRORS = (
    'wrong_intent', 'wrong_target', 'wrong_requested_field', 'changed_negation',
    'changed_modality', 'changed_quantity_or_date', 'invented_content', 'incomplete_action',
    'omitted_question', 'unnecessary_clarification', 'unresolved_ambiguity', 'ungrounded_value',
    'prohibited_fields', 'invalid_structure',
)
RECOVERABLE_ERRORS = (
    'casing', 'punctuation_or_unicode', 'inflection', 'terminology_normalisation',
    'aligned_source_span', 'null_representation',
)


def normalise(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text).casefold()
                   if not unicodedata.combining(c))


def tokens(text):
    return list(re.finditer(r'\d+(?:\.\d+)?%?|[^\W\d_]+', text, re.UNICODE))


@lru_cache(maxsize=4096)
def root(word):
    word = normalise(word)
    # General English inflection/nominalisation, not business synonyms.
    for ending in ('ations', 'ation', 'ments', 'ment', 'ing', 'als', 'al', 'ed', 's'):
        if word.endswith(ending) and len(word) > len(ending) + 3:
            word = word[:-len(ending)]
            if ending in ('ing', 'ed') and len(word) > 3 and word[-1] == word[-2]:
                word = word[:-1]
            break
    return word.removesuffix('e')


def protected(text):
    return set(re.findall(r'\d+(?:\.\d+)?%?|\b(?:not|no|never|without|can|cannot|may|must|shall|should|before|after|until|since)\b', normalise(text)))


@lru_cache(maxsize=4096)
def token_score(a, b):
    a, b = normalise(a), normalise(b)
    if a == b:
        return 1.0
    if protected(a) or protected(b):
        return 0.0
    if root(a) == root(b):
        return 1.0
    # Conservative lexical similarity requires a substantial shared prefix.
    if len(a) >= 5 and len(b) >= 5 and a[:4] == b[:4]:
        score = SequenceMatcher(None, a, b).ratio()
        return score if score >= .8 else 0.0
    return 0.0


def align(value, source, threshold=.85, *, process=False):
    """All content tokens must align. No unmatched actor/action/qualifier is invented."""
    bounded = rf'(?<!\w){re.escape(value)}(?!\w)'
    match = re.search(bounded, source)
    if match:
        return match.start(), match.end(), 'exact', 1.0
    match = re.search(bounded, source, re.IGNORECASE)
    if match:
        return match.start(), match.end(), 'case_insensitive', 1.0
    wanted = [m[0] for m in tokens(value)]
    ignored = {'a', 'an', 'the'} | ({'process'} if process else set())
    wanted = [w for w in wanted if normalise(w) not in ignored]
    actual = tokens(source)
    if not wanted:
        raise CriticalInterpretationError('No content tokens to align', 'ungrounded_value')
    candidates = []
    # Bounded windows prevent a phrase being manufactured from an arbitrary document.
    for start in range(len(actual)):
        for end in range(start + 1, min(len(actual), start + min(24, len(wanted) * 3 + 3)) + 1):
            window = actual[start:end]
            scores, used = [], set()
            for word in wanted:
                choices = [(token_score(word, token[0]), i) for i, token in enumerate(window) if i not in used]
                score, index = max(choices, default=(0, -1))
                if not score:
                    break
                scores.append(score)
                used.add(index)
            if len(scores) != len(wanted):
                continue
            score = sum(scores) / len(scores)
            if score < threshold:
                continue
            lo, hi = window[min(used)].start(), window[max(used)].end()
            exact = source[lo:hi]
            if not protected(value) <= protected(exact):
                continue
            # A set match alone could reverse date components or threshold bounds.
            numeric = re.findall(r"\d+(?:\.\d+)?%?", value)
            source_numeric = iter(re.findall(r"\d+(?:\.\d+)?%?", exact))
            if any(not any(n == candidate for candidate in source_numeric) for n in numeric):
                continue
            method = 'unicode_punctuation' if normalise(' '.join(wanted)) == normalise(' '.join(m[0] for m in tokens(exact))) else 'token_alignment'
            if len(window) > len(wanted) + 2:
                method = 'bounded_token_overlap'
            candidates.append((score, -(hi-lo), -lo, lo, hi, method))
    if not candidates:
        raise CriticalInterpretationError('Normalised value cannot be safely aligned to employee wording', 'ungrounded_value')
    score, _, _, lo, hi, method = max(candidates)
    return lo, hi, method, round(score, 4)


def align_payload(payload, question, context=(), threshold=.85, corrections=None):
    """Populate exact traceability independently from normalised QueryFrame values."""
    corrections = corrections if corrections is not None else []
    optional = (
        'process', 'known_actor', 'business_action', 'business_object', 'scope', 'modality',
        'clarification_question',
    )
    for frame_index, frame in enumerate(payload.get('frames', [])):
        for field in optional:
            if isinstance(frame.get(field), str) and frame[field].strip().casefold() in {'none', 'null', 'n/a'}:
                corrections.append({'frame': frame_index, 'field': field, 'code': 'null_representation'})
                frame[field] = None
        supplied = frame.get('source_spans', [])
        # Do not remove prohibited or unknown schema fields while repairing representation.
        allowed = {'field', 'text', 'context_index', 'normalised_value', 'source_span',
                   'source_start', 'source_end', 'alignment_method', 'alignment_score'}
        if not isinstance(supplied, list) or any(not isinstance(s, dict) or set(s)-allowed for s in supplied):
            raise CriticalInterpretationError('Invalid or prohibited source-span fields', 'invalid_structure')
        for span in supplied:
            if frame.get(span.get('field')) is None and str(span.get('text')).casefold() in {'none', 'null', 'n/a'}:
                corrections.append({'frame': frame_index, 'field': span.get('field'),
                                    'code': 'null_representation', 'action': 'removed_absent_value_span'})
        rebuilt = []
        fields = ('process', 'known_actor', 'business_action', 'business_object', 'scope', 'modality',
                  'conditions', 'numeric_values', 'temporal_scope')
        for field in fields:
            values = frame.get(field)
            values = values if isinstance(values, list) else [values] if values else []
            for value in values:
                if not isinstance(value, str):
                    raise CriticalInterpretationError('Grounded values must be strings', 'invalid_structure')
                prior = [s for s in supplied if s.get('field') == field]
                choices = []
                for context_index, source in [(None, question), *enumerate(context)]:
                    try:
                        lo, hi, method, score = align(value, source, threshold, process=field == 'process')
                    except CriticalInterpretationError:
                        continue
                    choices.append((score, context_index is None, context_index, source, lo, hi, method))
                if not choices:
                    raise CriticalInterpretationError(f'{field}: normalised value cannot be grounded', 'ungrounded_value')
                score, _, index, source, lo, hi, method = max(choices, key=lambda c: (c[0], c[1]))
                span = {'field': field, 'text': source[lo:hi], 'context_index': index,
                        'normalised_value': value, 'source_span': source[lo:hi],
                        'source_start': lo, 'source_end': hi, 'alignment_method': method,
                        'alignment_score': score}
                if not any(s.get('text') == span['text'] and s.get('context_index') == index
                           and all(s.get(k) is None or s[k] == span[k] for k in (
                               'normalised_value', 'source_span', 'source_start', 'source_end',
                               'alignment_method', 'alignment_score')) for s in prior):
                    corrections.append({'frame': frame_index, 'field': field, 'code': 'aligned_source_span',
                                        **{k: v for k, v in span.items() if k != 'field'}})
                rebuilt.append(span)
        # Ontology labels are not lexical extractions. Their semantic checks are separate.
        for span in supplied:
            if span.get('field') not in fields:
                if span.get('field') not in {'polarity', 'assessment_target'}:
                    raise CriticalInterpretationError('Unknown source-span field', 'invalid_structure')
                index = span.get('context_index')
                if index is not None and (not isinstance(index, int) or not 0 <= index < len(context)):
                    raise CriticalInterpretationError('Unavailable source context', 'ungrounded_value')
                source = question if index is None else context[index]
                lo, hi, method, score = align(span.get('text', ''), source, threshold)
                rebuilt.append({**span, 'text': source[lo:hi], 'source_span': source[lo:hi],
                                'normalised_value': frame.get(span['field']), 'source_start': lo,
                                'source_end': hi, 'alignment_method': method, 'alignment_score': score})
        for match in re.finditer(r'\b(?:without|not|never)\b', question, re.IGNORECASE):
            if not any(s['field'] == 'polarity' for s in rebuilt):
                rebuilt.append({'field': 'polarity', 'text': match[0], 'normalised_value': frame.get('polarity'),
                                'source_span': match[0], 'source_start': match.start(), 'source_end': match.end(),
                                'alignment_method': 'exact', 'alignment_score': 1.0, 'context_index': None})
                corrections.append({'frame': frame_index, 'field': 'polarity', 'code': 'aligned_source_span', 'source_span': match[0]})
        frame['source_spans'] = rebuilt
    return payload
