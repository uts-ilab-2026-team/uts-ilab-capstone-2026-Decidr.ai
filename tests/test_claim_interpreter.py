"""Provider contracts and safeguards with explicitly mocked model responses.

These tests do not claim to evaluate a live language model's semantic accuracy.
"""

from copy import deepcopy
import json

import httpx
import pytest

from decidr.claim_interpreter import (
    OllamaProvider,
    ProviderError,
    get_provider,
    interpret_claim,
)

CLAIM = "CASE-872 was approved by Morgan with a 37% discount."
OWN_PASSAGE_GROUNDING = "<use the selected finding's own passage>"


class MockProvider:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    def complete(self, schema, prompt):
        self.prompts.append((schema, prompt))
        data = json.JSONDecoder().raw_decode(prompt.split("\nDATA:\n", 1)[1])[0]
        scope = data.get("verification_scope")
        if not scope or scope["batch_start"] or "\nSCHEMA REPAIR:" in prompt:
            try:
                self.previous = next(self.responses)
            except StopIteration:
                pass
        result = deepcopy(self.previous)
        if schema["title"] == "Evaluation":
            self.selected_ids = {p["evidence_id"] for p in data["selected_passages"]}
            self.finding_count = len(result.get("findings", []))
        if scope and isinstance(result.get("finding_checks"), dict):
            checks = result["finding_checks"]
            result["finding_checks"] = {
                str(local): checks[str(original)]
                for local, original in enumerate(scope["original_finding_indices"])
                if str(original) in checks
            }
            # Unknown selectors must survive fixture partitioning so validation rejects them.
            result["finding_checks"].update(
                (key, check)
                for key, check in checks.items()
                if key not in {str(i) for i in range(self.finding_count)}
            )
        if schema["title"] == "EvidenceVerification":
            passages = {p["evidence_id"]: p for p in data["selected_passages"]}
            checks = result.get("finding_checks", {})
            if isinstance(checks, dict):
                for i, finding in enumerate(data["proposed_evaluation"]["findings"]):
                    check = checks.get(str(i), {})
                    if (
                        isinstance(check, dict)
                        and check.get("grounding_quote") == OWN_PASSAGE_GROUNDING
                    ):
                        check["grounding_quote"] = passages[finding["evidence_id"]]["text"]
            if scope and isinstance(result.get("omitted_evidence"), list):
                result["omitted_evidence"] = [
                    omission
                    for omission in result["omitted_evidence"]
                    if not isinstance(omission, dict)
                    or omission.get("evidence_id") in passages
                    or omission.get("evidence_id") not in self.selected_ids
                ]
                for omission in result["omitted_evidence"]:
                    if (
                        isinstance(omission, dict)
                        and omission.get("grounding_quote") == OWN_PASSAGE_GROUNDING
                        and omission.get("evidence_id") in passages
                    ):
                        omission["grounding_quote"] = passages[omission["evidence_id"]]["text"]
        return result


def interpreted(claim=CLAIM, **changes):
    return {
        "target": "event",
        "components": [
            {
                "id": "approval",
                "text": claim,
                "claim_quote": claim,
                "entities": ["CASE-872", "Morgan"] if "CASE-872" in claim else [],
                "predicate": "approved discount",
                "polarity": "positive",
                "quantities": [{"value": "37", "unit": "%", "comparator": "eq"}],
                "scope": [],
                "temporal": "",
                "modality": "asserted occurrence",
            }
        ],
        "ambiguities": [],
        "search_queries": [claim],
        **changes,
    }


def verified_claim(output=None, **changes):
    output = output or interpreted()
    result = {
        "component_checks": {
            c["id"]: {
                "valid": True,
                "reason": "The component preserves the original assertion.",
            }
            for c in output["components"]
        },
        "omitted_claim_spans": [],
    }
    issues = changes.pop("issues", [])
    valid = changes.pop("valid", True)
    if (issues or not valid) and result["component_checks"]:
        next(iter(result["component_checks"].values())).update(
            valid=False, reason="; ".join(issues) or "The component meaning is not preserved."
        )
    missing = changes.pop("unrepresented_clauses", [])
    result["omitted_claim_spans"] = [
        {"claim_quote": text, "reason": "This material assertion is missing."} for text in missing
    ]
    result.update(changes)
    return result


def passage(text="CASE-872: Morgan approved a 37% discount.", **changes):
    return {
        "evidence_id": "ev-record",
        "source_id": "record",
        "locator": "csv:row:19",
        "text": text,
        "heading": "Activity ledger",
        "source": {"source_type": "crm_records"},
        **changes,
    }


def finding(p=None, **changes):
    p = p or passage()
    return {
        "component_id": "approval",
        "evidence_id": p["evidence_id"],
        "relationship": "supports",
        "reason": "The record explicitly states the matching actor, amount and completed action.",
        "scope_fit": "yes",
        "time_fit": "unknown",
        "directness": "direct",
        "limitations": ["No independent confirmation."],
        "basis": "recorded_action",
        **changes,
    }


def assert_error(code, function):
    with pytest.raises(ProviderError) as exc:
        function()
    assert exc.value.code == code


def test_structured_passive_claim_and_verification_are_both_required():
    provider = MockProvider(interpreted(), verified_claim())
    result = interpret_claim(CLAIM, "2026-04-01", provider)
    assert result["target"] == "event"
    assert result["semantic_validation"]["component_checks"][0]["valid"]
    assert len(provider.prompts) == 2
    assert provider.prompts[0][0]["additionalProperties"] is False
    assert "Independently verify" in provider.prompts[1][1]


@pytest.mark.parametrize(
    "claim,value,unit",
    [
        ("External suppliers must complete training in six weeks.", "6", "weeks"),
        ("Assets are depreciated over twenty-five years.", "25", "years"),
        ("The limit is one hundred and fifty dollars.", "150", "dollars"),
        ("The required count is 37.", "37", "items"),
    ],
)
def test_non_approval_domains_and_number_word_normalization(claim, value, unit):
    output = interpreted(claim, target="formal_requirement")
    output["components"][0]["quantities"] = [{"value": value, "unit": unit, "comparator": "eq"}]
    provider = MockProvider(output, verified_claim(output))
    assert (
        interpret_claim(claim, "2026-04-01", provider)["components"][0]["quantities"][0]["value"]
        == value
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda out: out["components"][0].update(claim_quote="Not in original claim"),
        lambda out: out["components"][0]["entities"].append("CASE-900"),
        lambda out: out["components"][0]["quantities"][0].update(value="38"),
        lambda out: out["components"][0].update(quantities=[]),
        lambda out: out["components"].append(deepcopy(out["components"][0])),
        lambda out: out.update(invented_confidence=99),
    ],
)
def test_malformed_or_meaning_changing_extraction_is_rejected(mutate):
    output = interpreted()
    mutate(output)
    assert_error(
        "invalid_model_output", lambda: interpret_claim(CLAIM, "2026-04-01", MockProvider(output))
    )


def test_numeric_identifier_is_not_mistaken_for_quantity():
    claim = "CASE-982 was rejected."
    output = interpreted(claim)
    output["components"][0]["quantities"] = []
    assert interpret_claim(claim, "2026-04-01", MockProvider(output, verified_claim(output)))[
        "components"
    ]


@pytest.mark.parametrize(
    "claim,wrong",
    [
        ("Discounts above 37% require approval.", "gte"),
        ("Discounts of 37% or more require approval.", "gt"),
        ("At least 37% must remain reserved.", "gt"),
        ("Amounts below $37 require review.", "lte"),
    ],
)
def test_exclusive_and_inclusive_boundaries_cannot_be_changed(claim, wrong):
    output = interpreted(claim)
    output["components"][0]["quantities"][0]["comparator"] = wrong
    assert_error(
        "invalid_model_output", lambda: interpret_claim(claim, "2026-04-01", MockProvider(output))
    )


@pytest.mark.parametrize(
    "issues,missing",
    [
        (["Negation was lost."], []),
        (["A proposed action became a completed action."], []),
        (["Historical state became current state."], []),
        ([], ["37%"]),
    ],
)
def test_semantic_failures_are_operational_errors_not_evidence_gaps(issues, missing):
    verified = verified_claim(valid=False, issues=issues, unrepresented_clauses=missing)
    assert_error(
        "interpretation_failure",
        lambda: interpret_claim(CLAIM, "2026-04-01", MockProvider(interpreted(), verified)),
    )


def test_semantic_claim_verifier_must_cover_every_component():
    assert_error(
        "invalid_model_output",
        lambda: interpret_claim(
            CLAIM, "2026-04-01", MockProvider(interpreted(), verified_claim(component_checks=[]))
        ),
    )


def test_formal_approver_assertion_keeps_authority_target_with_threshold_qualifier():
    claim = "The Operations Director is the formal approver for adjustments of 37% or more."
    output = interpreted(claim, target="formal_authority")
    output["components"][0]["quantities"][0]["comparator"] = "gte"
    provider = MockProvider(output, verified_claim(output))
    assert interpret_claim(claim, "2026-04-01", provider)["target"] == "formal_authority"
    assert "WHO holds the right" in provider.prompts[0][1]
    assert "formal approver or authorised decision-maker" in provider.prompts[1][1]


def test_normalizing_an_unambiguous_comparator_is_not_material_ambiguity():
    claim = "Orders above 42 units require approval."
    wrong = interpreted(
        claim,
        target="formal_requirement",
        ambiguities=["Above is interpreted strictly as greater than, excluding the boundary."],
    )
    wrong["components"][0]["quantities"] = [{"value": "42", "unit": "units", "comparator": "gt"}]
    corrected = deepcopy(wrong)
    corrected["ambiguities"] = []
    rejected = verified_claim(
        wrong,
        valid=False,
        issues=[
            "Comparator normalization explains unambiguous wording; it is not a competing reading."
        ],
    )
    provider = MockProvider(wrong, rejected, corrected, verified_claim(corrected))
    result = interpret_claim(claim, "2026-04-01", provider)
    assert result["ambiguities"] == []
    assert result["semantic_validation"]["complete_repair_attempted"]
    assert (
        "normalization explanations and evidence gaps are not ambiguities"
        in provider.prompts[0][0]["properties"]["ambiguities"]["description"]
    )
    assert "mislabelled ambiguity" in provider.prompts[1][1]


def test_genuine_unspecified_currency_and_scope_are_preserved_as_ambiguity():
    claim = "Requests above $420 require approval."
    output = interpreted(
        claim,
        target="formal_requirement",
        ambiguities=[
            "The dollar currency is unspecified.",
            "The type and organisational scope of requests are unspecified.",
        ],
    )
    output["components"][0]["quantities"] = [{"value": "420", "unit": "$", "comparator": "gt"}]
    result = interpret_claim(claim, "2026-04-01", MockProvider(output, verified_claim(output)))
    assert result["ambiguities"] == output["ambiguities"]


def test_provider_is_configured_from_constants_not_env(monkeypatch):
    # The provider is pinned in decidr.infra.constants, not the environment: a "paid-provider"
    # env var cannot silently redirect it, and nothing remote is ever reachable.
    from decidr.infra.constants import ASSESSMENT_MODEL, ASSESSMENT_URL

    monkeypatch.setenv("DECIDR_ASSESSMENT_PROVIDER", "paid-provider")
    monkeypatch.setenv("DECIDR_ASSESSMENT_MODEL", "remote-model")
    provider = get_provider()
    assert isinstance(provider, OllamaProvider)
    assert provider.model == ASSESSMENT_MODEL
    assert provider.url == ASSESSMENT_URL.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://remote.example:11434",
        "http://user:secret@localhost:11434",
        "http://localhost:11434/other",
        "http://localhost:11434?key=secret",
    ],
)
def test_remote_or_credentialed_endpoints_are_rejected(url):
    assert_error("provider_unavailable", lambda: OllamaProvider("installed", url))


def test_explicit_cloud_model_is_rejected():
    assert_error("provider_unavailable", lambda: OllamaProvider("example:cloud"))


def mocked_http(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(
        "decidr.claim_interpreter.providers.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_local_provider_requests_structured_json_and_does_not_download(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"details": {"format": "gguf"}})
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"ok":true}'},
                "done_reason": "stop",
                "prompt_eval_count": 128,
                "eval_count": 8,
            },
        )

    mocked_http(monkeypatch, handler)
    provider = OllamaProvider("installed-model")
    assert provider.complete({"type": "object"}, "untrusted claim") == {"ok": True}
    assert [r.url.path for r in seen] == ["/api/show", "/api/tags", "/api/version", "/api/chat"]
    body = json.loads(seen[-1].content)
    assert body["think"] is False
    assert body["format"] == {"type": "object"}
    assert "untrusted DATA" in body["messages"][0]["content"]
    assert provider.provenance()["local_only"]


@pytest.mark.parametrize(
    "title,think",
    [
        ("Interpretation", False),
        ("Evaluation", False),
        ("InterpretationVerification", False),
        ("EvidenceVerification", False),
    ],
)
@pytest.mark.parametrize("timeout", [90, 420])
def test_local_provider_uses_bounded_nonthinking_requests_for_every_stage(
    monkeypatch, title, think, timeout
):
    seen = []

    def handler(request):
        if request.url.path == "/api/chat":
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "message": {
                        "content": '{"ok":true}',
                        "thinking": "Private reasoning is not returned.",
                    },
                    "prompt_eval_count": 128,
                    "eval_count": 18,
                },
            )
        return httpx.Response(200, json={})

    mocked_http(monkeypatch, handler)
    provider = OllamaProvider("installed-model", timeout=timeout)
    assert provider.complete({"type": "object", "title": title}, "Assess only supplied data.") == {
        "ok": True
    }
    body = json.loads(seen[0].content)
    assert body["think"] is think
    assert body["options"]["num_predict"] == 8192
    expected_timeout = timeout
    assert seen[0].extensions["timeout"]["read"] == expected_timeout
    provenance = provider.provenance()
    metric = provenance["generation_metrics"][0]
    assert metric["think"] is think
    assert metric["schema"] == title
    assert metric["timeout_seconds"] == expected_timeout
    assert provenance["timeout_policy"]["configured_seconds"] == timeout
    assert "Private reasoning" not in json.dumps(provenance)


def test_cloud_alias_cannot_hide_behind_local_endpoint(monkeypatch):
    mocked_http(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"remote_model": "paid-model", "remote_host": "https://cloud.example"}
        ),
    )
    assert_error(
        "provider_unavailable", lambda: OllamaProvider("local-looking-name").complete({}, "claim")
    )


@pytest.mark.parametrize(
    "body",
    [
        {"message": {"content": "not JSON"}},
        {"message": {"content": "[]"}},
        {"message": {"content": '{"ok":true}'}, "done_reason": "length"},
        {},
    ],
)
def test_local_provider_rejects_incomplete_or_malformed_output(monkeypatch, body):
    def handler(request):
        return httpx.Response(200, json={} if request.url.path == "/api/show" else body)

    mocked_http(monkeypatch, handler)
    assert_error("invalid_model_output", lambda: OllamaProvider("installed").complete({}, "claim"))


def test_duplicate_json_verifier_keys_cannot_overwrite_a_rejection(monkeypatch):
    def handler(request):
        if request.url.path != "/api/chat":
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": '{"finding_checks":{"0":{"valid":false,"reason":"Invalid."},"0":{"valid":true,"reason":"Overwritten."}},"omitted_evidence":[]}'
                },
                "prompt_eval_count": 500,
                "eval_count": 40,
            },
        )

    mocked_http(monkeypatch, handler)
    provider = OllamaProvider("mocked-model")
    assert_error(
        "invalid_model_output",
        lambda: provider.complete({"title": "EvidenceVerification"}, "Validate."),
    )
    assert provider.provenance()["completed_calls"] == 0
    assert provider.provenance()["generation_metrics"][0]["response_received"]


@pytest.mark.parametrize("content,done_reason", [("", "length"), ('{"finding_checks":', "stop")])
def test_failed_generation_retains_stage_cost_and_started_request_count(
    monkeypatch, content, done_reason
):
    def handler(request):
        if request.url.path != "/api/chat":
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": content,
                    "thinking": "Private internal reasoning must never be logged.",
                },
                "done_reason": done_reason,
                "prompt_eval_count": 4096,
                "eval_count": 8192,
                "prompt_eval_duration": 1000000,
                "eval_duration": 290000000000,
                "total_duration": 291000000000,
            },
        )

    mocked_http(monkeypatch, handler)
    provider = OllamaProvider("installed")
    assert_error(
        "invalid_model_output",
        lambda: provider.complete(
            {"title": "EvidenceVerification"}, "Evaluate the original evidence."
        ),
    )
    provenance = provider.provenance()
    assert provenance["started_requests"] == 1
    assert provenance["completed_calls"] == 0
    metric = provenance["generation_metrics"][0]
    assert metric["request_number"] == 1
    assert metric["schema"] == "EvidenceVerification"
    assert metric["think"] is False
    assert metric["response_received"] is True
    assert metric["done_reason"] == done_reason
    assert metric["input_tokens"] == 4096
    assert metric["output_tokens"] == 8192
    assert metric["generation_duration_ns"] == 290000000000
    assert metric["total_duration_ns"] == 291000000000
    assert "Private internal reasoning" not in json.dumps(provenance)


def test_generation_timeout_records_started_stage_without_success_or_raw_data(monkeypatch):
    def handler(request):
        if request.url.path == "/api/chat":
            raise httpx.ReadTimeout("A server message that should not appear in provenance.")
        return httpx.Response(200, json={})

    mocked_http(monkeypatch, handler)
    provider = OllamaProvider("installed")
    assert_error(
        "provider_failure",
        lambda: provider.complete({"title": "InterpretationVerification"}, "Private claim data."),
    )
    provenance = provider.provenance()
    assert provenance["started_requests"] == 1
    assert provenance["completed_calls"] == 0
    assert provenance["generation_metrics"][0]["schema"] == "InterpretationVerification"
    assert provenance["generation_metrics"][0]["response_received"] is False
    assert "Private claim data" not in json.dumps(provenance)


@pytest.mark.parametrize(
    "status,code",
    [(404, "provider_unavailable"), (500, "provider_failure"), (302, "provider_failure")],
)
def test_http_errors_have_explicit_processing_codes(monkeypatch, status, code):
    mocked_http(monkeypatch, lambda request: httpx.Response(status))
    assert_error(code, lambda: OllamaProvider("installed").complete({}, "claim"))


def test_timeout_and_missing_server_are_explicit_failures(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("local server unavailable")

    mocked_http(monkeypatch, handler)
    assert_error("provider_unavailable", lambda: OllamaProvider("installed").complete({}, "claim"))


def test_context_limit_is_capability_error_not_zero_confidence():
    assert_error(
        "unsupported_capability", lambda: OllamaProvider("installed").complete({}, "x" * 125_001)
    )


def test_historical_year_can_be_temporal_context_instead_of_quantity():
    claim = "Customer requests were managed in Atlas in 2023."
    output = interpreted(claim, target="historical_state")
    output["components"][0]["quantities"] = []
    output["components"][0]["temporal"] = "during 2023"
    assert (
        interpret_claim(claim, "2026-04-01", MockProvider(output, verified_claim(output)))[
            "target"
        ]
        == "historical_state"
    )


def test_bounded_schema_repair_revalidates_actual_numeric_value():
    invalid = interpreted()
    invalid["components"][0]["quantities"][0]["value"] = ""
    provider = MockProvider(invalid, interpreted(), verified_claim())
    result = interpret_claim(CLAIM, "2026-04-01", provider)
    assert result["components"][0]["quantities"][0]["value"] == "37"
    assert len(provider.prompts) == 3
    assert "SCHEMA REPAIR" in provider.prompts[1][1]


def test_schema_repair_does_not_accept_a_changed_number():
    invalid = interpreted()
    invalid["components"][0]["quantities"][0]["value"] = ""
    wrong = interpreted()
    wrong["components"][0]["quantities"][0]["value"] = "38"
    assert_error(
        "invalid_model_output",
        lambda: interpret_claim(CLAIM, "2026-04-01", MockProvider(invalid, wrong)),
    )


def test_validation_provenance_distinguishes_attempted_and_recovered_repair():
    invalid = interpreted()
    invalid["components"][0]["quantities"][0]["value"] = "38"
    provider = MockProvider(invalid, interpreted(), verified_claim())
    events = []
    provider.record_validation_attempt = lambda stage, code, repaired: events.append(
        (stage, code, repaired)
    )
    result = interpret_claim(CLAIM, "2026-04-01", provider)
    assert result["semantic_validation"]["complete_repair_attempted"]
    assert events == [
        ("claim_interpretation", "invalid_model_output", False),
        ("claim_interpretation", "invalid_model_output", True),
    ]


def test_current_formal_obligation_target_is_repaired_separately_from_time():
    claim = "The current contractor training deadline is nine days."
    wrong = interpreted(claim, target="current_state")
    wrong["components"][0]["quantities"] = [{"value": "9", "unit": "days", "comparator": "eq"}]
    wrong["components"][0]["temporal"] = "current"
    correct = deepcopy(wrong)
    correct["target"] = "formal_requirement"
    rejection = verified_claim(
        wrong,
        valid=False,
        issues=["A normative deadline is formal_requirement; current is its temporal scope."],
    )
    provider = MockProvider(wrong, rejection, correct, verified_claim(correct))
    result = interpret_claim(claim, "2026-04-01", provider)
    assert result["target"] == "formal_requirement"
    assert result["components"][0]["temporal"] == "current"
    assert "Target and time are separate dimensions" in provider.prompts[0][1]
    assert result["semantic_validation"]["complete_repair_attempted"]


def test_server_token_count_rejects_output_after_context_budget_overflow(monkeypatch):
    def handler(request):
        body = {
            "message": {"content": '{"ok":true}'},
            "prompt_eval_count": 24000,
            "eval_count": 10,
        }
        return httpx.Response(200, json={} if request.url.path != "/api/chat" else body)

    mocked_http(monkeypatch, handler)
    provider = OllamaProvider("installed")
    assert_error("unsupported_capability", lambda: provider.complete({}, "claim"))
    assert provider.provenance()["generation_metrics"][0]["input_tokens"] == 24000


def test_context_preflight_reserves_space_for_output_and_uses_utf8_bytes():
    provider = OllamaProvider("installed")
    assert_error("unsupported_capability", lambda: provider.complete({}, "a" * 48000))
    assert_error("unsupported_capability", lambda: provider.complete({}, "漢" * 16000))


def test_missing_server_context_count_cannot_silently_hide_truncation(monkeypatch):
    def handler(request):
        body = {"message": {"content": '{"ok":true}'}}
        return httpx.Response(200, json={} if request.url.path != "/api/chat" else body)

    mocked_http(monkeypatch, handler)
    assert_error("provider_failure", lambda: OllamaProvider("installed").complete({}, "claim"))


@pytest.mark.parametrize("component_id", ["component-1", "claim-92", "atom-007"])
def test_internal_component_identifier_is_not_a_claim_record_identifier(component_id):
    claim = "The current limit is 37%."
    output = interpreted(claim, target="formal_requirement")
    output["components"][0]["id"] = component_id
    result = interpret_claim(claim, "2026-04-01", MockProvider(output, verified_claim(output)))
    assert result["components"][0]["id"] == component_id


def test_output_schema_is_visible_to_model_not_only_decoder():
    provider = MockProvider(interpreted(), verified_claim())
    interpret_claim(CLAIM, "2026-04-01", provider)
    for schema, prompt in provider.prompts:
        visible = json.loads(
            prompt.split(
                "OUTPUT_SCHEMA (all required fields must be supplied with the declared types):\n",
                1,
            )[1].split("\nDATA:\n", 1)[0]
        )
        assert visible == schema


def test_schema_failure_provenance_reports_fields_without_model_input():
    output = interpreted()
    output["components"][0]["quantities"][0]["value"] = "secret-like-input"
    provider = MockProvider(output)
    errors = []
    provider.record_validation_fields = lambda stage, fields: errors.extend(fields)
    assert_error("invalid_model_output", lambda: interpret_claim(CLAIM, "2026-04-01", provider))
    assert any(e["field"] == "components.0.quantities.0.value" for e in errors)
    assert "secret-like-input" not in json.dumps(errors)


def test_unspecified_dollar_currency_is_not_a_deterministic_fx_assumption():
    from decidr.claim_interpreter import _numeric_unit, _scalar_observations

    assert _numeric_unit("$")[0] == "currency:unspecified"
    assert _numeric_unit("USD")[0] != _numeric_unit("AUD")[0]
    assert _scalar_observations("USD 700 and AUD 700") == [
        (700, "currency:USD"),
        (700, "currency:AUD"),
    ]
    assert _numeric_unit("month") is None
    assert _numeric_unit("business days")[0] != _numeric_unit("days")[0]


@pytest.mark.parametrize("value", ["15", "500", "6", "-3.25", "0", "0.125"])
def test_quantity_schema_accepts_real_numeric_strings(value):
    import re

    from decidr.claim_interpreter import Quantity

    assert (
        Quantity.model_validate({"value": value, "unit": "%", "comparator": "eq"}).value == value
    )
    assert re.fullmatch(Quantity.model_json_schema()["properties"]["value"]["pattern"], value)


@pytest.mark.parametrize("value", ["", "15%", "six", "NaN", "Infinity", "1,000"])
def test_quantity_schema_rejects_placeholders_and_noncanonical_values(value):
    from pydantic import ValidationError

    from decidr.claim_interpreter import Quantity

    with pytest.raises(ValidationError):
        Quantity.model_validate({"value": value, "unit": "%", "comparator": "eq"})


def test_temporal_field_carries_current_qualifier_without_forcing_text_duplication():
    claim = "Maintenance tickets are currently managed in Birch."
    output = interpreted(claim, target="current_state")
    c = output["components"][0]
    c.update(text="Maintenance tickets are managed in Birch.", temporal="current", quantities=[])
    provider = MockProvider(output, verified_claim(output))
    result = interpret_claim(claim, "2026-04-01", provider)
    assert result["components"][0]["temporal"] == "current"
    assert "structured component JOINTLY" in provider.prompts[1][1]
    assert "need not be\nrepeated in text" in provider.prompts[1][1]


def test_positive_interpretation_issue_is_repaired_in_verifier_only():
    inconsistent = {
        **verified_claim(),
        "valid": True,
        "issues": ["Every original clause is represented."],
    }
    provider = MockProvider(interpreted(), inconsistent, verified_claim())
    result = interpret_claim(CLAIM, "2026-04-01", provider)
    assert result["components"]
    assert [schema["title"] for schema, _ in provider.prompts] == [
        "Interpretation",
        "InterpretationVerification",
        "InterpretationVerification",
    ]


def test_claim_verifier_does_not_receive_prior_generation_failure_feedback():
    wrong = interpreted()
    wrong["components"][0]["quantities"][0]["value"] = "38"
    provider = MockProvider(wrong, interpreted(), verified_claim())
    result = interpret_claim(CLAIM, "2026-04-01", provider)
    assert result["components"][0]["quantities"][0]["value"] == "37"
    generator_data = json.loads(provider.prompts[1][1].split("\nDATA:\n", 1)[1])
    verifier_data = json.loads(provider.prompts[2][1].split("\nDATA:\n", 1)[1])
    assert generator_data["validation_feedback"]
    assert "validation_feedback" not in verifier_data
    assert verifier_data["original_claim"] == CLAIM
    assert (
        verifier_data["proposed_interpretation"]["components"][0]["quantities"][0]["value"] == "37"
    )


def test_explicit_accuracy_assertion_is_interpreted_without_claiming_it_is_true():
    claim = "CASE-872's recorded 37% discount is accurate."
    output = interpreted(claim, target="value_accuracy")
    provider = MockProvider(output, verified_claim(output))
    result = interpret_claim(claim, "2026-04-01", provider)
    assert result["target"] == "value_accuracy"
    assert "checks asserted meaning, not truth" in provider.prompts[1][1]
    assert "findings" not in result


def test_within_duration_means_upper_bound_not_exact_scalar():
    claim = "Contractor training must finish within six days."
    output = interpreted(claim, target="formal_requirement")
    output["components"][0]["quantities"] = [{"value": "6", "unit": "days", "comparator": "lte"}]
    result = interpret_claim(claim, "2026-04-01", MockProvider(output, verified_claim(output)))
    assert result["components"][0]["quantities"][0]["comparator"] == "lte"


def test_verifier_contract_has_no_redundant_global_verdict_or_free_issues():
    from decidr.claim_interpreter import InterpretationVerification

    assert set(InterpretationVerification.model_json_schema()["properties"]) == {
        "component_checks",
        "omitted_claim_spans",
    }


def test_claim_verifier_uses_required_actual_identifier_keys_and_preserves_public_list():
    from pydantic import ValidationError

    from decidr.claim_interpreter import _claim_verifier_model

    model = _claim_verifier_model(["component-7", "_meaning"])
    schema = model.model_json_schema()
    checks = schema["$defs"]["ComponentChecks"]
    assert checks["required"] == ["component-7", "_meaning"]
    assert checks["additionalProperties"] is False
    candidate = {
        "component_checks": {
            "component-7": {"valid": False, "reason": "Meaning changed."},
            "_meaning": {"valid": True, "reason": "Meaning preserved."},
        },
        "omitted_claim_spans": [],
    }
    assert model.model_validate(candidate).model_dump(by_alias=True) == candidate
    for changed in [{}, {"invented": {"valid": True, "reason": "Invented selector."}}]:
        with pytest.raises(ValidationError):
            model.model_validate({**candidate, "component_checks": changed})
    output = interpreted()
    output["components"][0]["id"] = "_meaning"
    result = interpret_claim(CLAIM, "2026-04-01", MockProvider(output, verified_claim(output)))
    assert result["semantic_validation"]["component_checks"][0]["component_id"] == "_meaning"


def test_verifier_selector_schema_repair_does_not_regenerate_the_claim():
    invalid = verified_claim(
        component_checks={"invented": {"valid": True, "reason": "Unknown selector."}}
    )
    provider = MockProvider(interpreted(), invalid, verified_claim())
    result = interpret_claim(CLAIM, "2026-04-01", provider)
    assert result["semantic_validation"]["component_checks"][0]["valid"]
    assert [schema["title"] for schema, _ in provider.prompts] == [
        "Interpretation",
        "InterpretationVerification",
        "InterpretationVerification",
    ]


def test_claim_omission_must_quote_an_actual_original_span():
    checked = verified_claim(
        omitted_claim_spans=[
            {"claim_quote": "an invented extra assertion", "reason": "This is missing."}
        ]
    )
    provider = MockProvider(interpreted(), checked)
    assert_error("invalid_model_output", lambda: interpret_claim(CLAIM, "2026-04-01", provider))


def test_actual_claim_omission_remains_an_interpretation_failure():
    checked = verified_claim(
        omitted_claim_spans=[
            {
                "claim_quote": "37% discount",
                "reason": "The discount assertion was omitted from the component meaning.",
            }
        ]
    )
    provider = MockProvider(interpreted(), checked)
    assert_error("interpretation_failure", lambda: interpret_claim(CLAIM, "2026-04-01", provider))


def test_typography_is_bound_to_original_claim_before_semantic_verification():
    claim = "The supplier’s inspection must finish within six days."
    output = interpreted(claim)
    output["components"][0].update(
        claim_quote=claim.replace("’", "'"),
        quantities=[{"value": "6", "unit": "days", "comparator": "lte"}],
    )
    provider = MockProvider(output, verified_claim(output))
    result = interpret_claim(claim, "2026-04-01", provider)
    assert result["components"][0]["claim_quote"] == claim
    data = json.loads(provider.prompts[1][1].split("\nDATA:\n", 1)[1])
    assert data["original_claim"] == claim
    assert data["proposed_interpretation"]["components"][0]["claim_quote"] == claim


def test_semantic_omission_typography_restores_the_original_span():
    claim = "The supplier’s inspection must finish within six days."
    output = interpreted(claim)
    output["components"][0]["quantities"] = [{"value": "6", "unit": "days", "comparator": "lte"}]
    rejection = verified_claim(
        output,
        omitted_claim_spans=[
            {
                "claim_quote": "The supplier's inspection",
                "reason": "Missing responsibility meaning.",
            }
        ],
    )
    provider = MockProvider(output, rejection, output, verified_claim(output))
    result = interpret_claim(claim, "2026-04-01", provider)
    assert result["components"][0]["claim_quote"] == claim
    assert result["semantic_validation"]["complete_repair_attempted"]


def test_conditional_premise_is_repaired_to_one_self_contained_proposition():
    claim = "If travel is required, staff may use company vehicles provided a supervisor approves."
    full = interpreted(claim, target="formal_requirement")
    full["components"][0].update(
        quantities=[], predicate="may use", scope=["required travel", "supervisor approval"]
    )
    split = deepcopy(full)
    split["components"][0].update(
        text="Travel is required.", claim_quote="travel is required", scope=[]
    )
    provider = MockProvider(split, full, verified_claim(full))
    result = interpret_claim(claim, "2026-04-01", provider)
    assert len(result["components"]) == 1
    assert result["components"][0]["claim_quote"] == claim
    assert result["components"][0]["scope"] == ["required travel", "supervisor approval"]
    assert [schema["title"] for schema, _ in provider.prompts] == [
        "Interpretation",
        "Interpretation",
        "InterpretationVerification",
    ]
    assert "SCHEMA REPAIR" in provider.prompts[1][1]


@pytest.mark.parametrize(
    "claim,quantities",
    [
        (
            "If a vessel enters protected water, speed must remain below six knots.",
            [{"value": "6", "unit": "knots", "comparator": "lt"}],
        ),
        ("Unless the alarm is cleared, staff must not re-enter the building.", []),
        ("Visitors may bring equipment provided it is inspected at reception.", []),
        (
            "When maintenance is complete, machines may restart provided guards are fitted.",
            [],
        ),
        ("When a customer’s **account is restricted**, exports require approval.", []),
    ],
)
def test_conditional_schema_preserves_whole_claim_and_revalidates_extracted_metadata(
    claim, quantities
):
    output = interpreted(claim, target="formal_requirement")
    output["components"][0].update(quantities=quantities, modality="conditional rule")
    provider = MockProvider(output, verified_claim(output))
    result = interpret_claim(claim, "2026-04-01", provider)
    schema = provider.prompts[0][0]
    assert schema["title"] == "Interpretation"
    assert schema["properties"]["components"]["minItems"] == 1
    assert schema["properties"]["components"]["maxItems"] == 1
    fields = schema["$defs"]["ConditionalComponent"]["properties"]
    assert fields["text"]["const"] == fields["claim_quote"]["const"] == claim
    assert result["components"] == output["components"]
    assert result["target"] == output["target"]
    assert result["search_queries"] == output["search_queries"]
    assert (
        result["semantic_validation"]["conditional_claim_method"]
        == "lexical-cue-verbatim-component-v1"
    )
    assert provider.prompts[1][0]["title"] == "InterpretationVerification"
    verified_data = json.loads(provider.prompts[1][1].split("\nDATA:\n", 1)[1])
    assert verified_data["original_claim"] == claim
    assert verified_data["proposed_interpretation"] == output


@pytest.mark.parametrize("defect", ["flattened_text", "partial_quote", "multiple_components"])
def test_conditional_shape_is_rejected_before_even_an_approving_semantic_verifier(defect):
    claim = "If pressure rises, the pump must stop unless emergency cooling is active."
    flattened = interpreted(claim, target="formal_requirement")
    flattened["components"][0]["quantities"] = []
    if defect == "flattened_text":
        flattened["components"][0]["text"] = "The pump must stop."
    elif defect == "partial_quote":
        flattened["components"][0]["claim_quote"] = "the pump must stop"
    else:
        second = deepcopy(flattened["components"][0])
        second["id"] = "condition"
        flattened["components"].append(second)

    class ApprovingVerifier(MockProvider):
        def complete(self, schema, prompt):
            self.prompts.append((schema, prompt))
            if schema["title"] == "InterpretationVerification":
                return verified_claim(flattened)
            return deepcopy(flattened)

    provider = ApprovingVerifier()
    assert_error("invalid_model_output", lambda: interpret_claim(claim, "2026-04-01", provider))
    assert all(schema["title"] == "Interpretation" for schema, _ in provider.prompts)


def test_unconditional_independent_assertions_can_still_be_split():
    claim = "The fan is running and the door is closed."
    output = interpreted(claim, target="current_state")
    first = output["components"][0]
    first.update(
        id="fan", text="The fan is running", claim_quote="The fan is running", quantities=[]
    )
    second = deepcopy(first)
    second.update(id="door", text="the door is closed", claim_quote="the door is closed")
    output["components"].append(second)
    provider = MockProvider(output, verified_claim(output))
    result = interpret_claim(claim, "2026-04-01", provider)
    assert result["components"] == output["components"]
    assert provider.prompts[0][0]["properties"]["components"]["maxItems"] == 20
    assert "conditional_claim_method" not in result["semantic_validation"]


