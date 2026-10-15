"""Tests for the reconciled confidence axis (assess_claim / to_payload).

Confidence is ONE axis: a 0-1 score and its categorical tier come from the same calculation, so
`_confidence_band(score) == tier` for every decided outcome. The score rewards both evidence
strength (peak + mean of the aligned material origins) and corroboration (independent origins):
a lone strong source is Moderate, two independent decisive sources unlock Higher. It is
confidence-in-evidence for the STATED outcome, never a probability the claim is true.
"""

from types import SimpleNamespace

from decidr.pipeline import (
    _confidence_band,
    _facet_confidence,
    _reconcile_confidence,
)


def _edge(stance, material, score, *, document_id="doc:a", applicable=True):
    return SimpleNamespace(
        stance=stance,
        material=material,
        materiality_score=score,
        document_id=document_id,
        applicable=applicable,
    )


def _assessment(*edges, gaps=()):
    return SimpleNamespace(evidence=list(edges), gaps=tuple(gaps))


# --------------------------------------------------------------------------- #
# Bands                                                                        #
# --------------------------------------------------------------------------- #


def test_bands_map_score_to_tier():
    assert _confidence_band(0.75) == "Higher confidence"
    assert _confidence_band(0.749) == "Moderate confidence"
    assert _confidence_band(0.45) == "Moderate confidence"
    assert _confidence_band(0.449) == "Lower confidence"
    assert _confidence_band(0.0) == "Lower confidence"


# --------------------------------------------------------------------------- #
# Strength + corroboration blend                                              #
# --------------------------------------------------------------------------- #


def test_single_strong_source_is_moderate_not_higher():
    # The clash we fixed: one excellent source no longer reads 0.94/"Higher" — it is honestly
    # Moderate, and the number itself (0.938 * 0.65) reflects the lack of corroboration.
    a = _assessment(_edge("support", True, 0.938))
    score, tier = _facet_confidence(a, "Supported", ())
    assert score == 0.610
    assert tier == "Moderate confidence"
    assert _confidence_band(score) == tier


def test_two_independent_strong_sources_unlock_higher():
    a = _assessment(
        _edge("support", True, 0.90, document_id="doc:a"),
        _edge("support", True, 0.88, document_id="doc:b"),
    )
    score, tier = _facet_confidence(a, "Supported", ())
    assert score == 0.761  # 0.5*0.90 + 0.5*0.89 = 0.895, * (0.65+0.20) = 0.76075
    assert tier == "Higher confidence"


def test_weak_single_source_is_lower():
    a = _assessment(_edge("support", True, 0.60))
    score, tier = _facet_confidence(a, "Supported", ())
    assert score == 0.39  # 0.60 * 0.65
    assert tier == "Lower confidence"


def test_mean_drags_down_a_weak_second_origin():
    # A weak second origin corroborates (raises corroboration) but its low score drags the mean,
    # so the facet lifts above a lone source yet stays out of Higher.
    lone = _facet_confidence(_assessment(_edge("support", True, 0.95)), "Supported", ())[0]
    pair = _facet_confidence(
        _assessment(
            _edge("support", True, 0.95, document_id="doc:a"),
            _edge("support", True, 0.55, document_id="doc:b"),
        ),
        "Supported",
        (),
    )
    assert lone == 0.617  # 0.95 * 0.65
    assert pair[0] == 0.723  # strength 0.75 * corroboration 0.85 -> below the 0.75 Higher band
    assert pair[0] > lone
    assert pair[1] == "Moderate confidence"


def test_duplicate_origin_counts_once():
    # Three edges from the SAME document are one origin: no corroboration credit, still Moderate.
    a = _assessment(
        _edge("support", True, 0.938, document_id="doc:pol-03"),
        _edge("support", True, 0.938, document_id="doc:pol-03"),
        _edge("support", True, 0.938, document_id="doc:pol-03"),
    )
    score, tier = _facet_confidence(a, "Supported", ())
    assert score == 0.610
    assert tier == "Moderate confidence"


def test_origin_uses_its_strongest_edge():
    a = _assessment(
        _edge("support", True, 0.60, document_id="doc:a"),
        _edge("support", True, 0.90, document_id="doc:a"),  # same origin, stronger edge wins
    )
    score, _ = _facet_confidence(a, "Supported", ())
    assert score == 0.585  # 0.90 * 0.65 (single origin)


# --------------------------------------------------------------------------- #
# Caveat cap                                                                   #
# --------------------------------------------------------------------------- #


def test_gap_keeps_a_facet_out_of_higher():
    edges = (
        _edge("support", True, 0.90, document_id="doc:a"),
        _edge("support", True, 0.88, document_id="doc:b"),
    )
    uncapped = _facet_confidence(_assessment(*edges), "Supported", ())
    capped = _facet_confidence(_assessment(*edges), "Supported", ("unresolved gap",))
    assert uncapped[1] == "Higher confidence"
    assert capped[0] == 0.749  # pinned just under the Higher band
    assert capped[1] == "Moderate confidence"


def test_non_material_contradiction_keeps_a_facet_out_of_higher():
    a = _assessment(
        _edge("support", True, 0.90, document_id="doc:a"),
        _edge("support", True, 0.88, document_id="doc:b"),
        _edge("contradict", False, 0.30, document_id="doc:c", applicable=True),
    )
    score, tier = _facet_confidence(a, "Supported", ())
    assert score == 0.749
    assert tier == "Moderate confidence"


# --------------------------------------------------------------------------- #
# Direction + non-decided outcomes                                            #
# --------------------------------------------------------------------------- #


def test_contradicted_uses_contradict_edges():
    a = _assessment(
        _edge("contradict", True, 0.80, document_id="doc:a"),
        _edge("support", True, 0.99, document_id="doc:b"),  # opposing side ignored
    )
    score, tier = _facet_confidence(a, "Contradicted", ())
    assert score == 0.52  # 0.80 * 0.65
    assert tier == "Moderate confidence"


def test_insufficient_is_zero_lower_even_with_a_strong_edge():
    a = _assessment(_edge("support", True, 0.875))
    assert _facet_confidence(a, "Insufficient evidence", ()) == (0.0, "Lower confidence")


def test_contested_is_zero_moderate():
    a = _assessment(_edge("support", True, 0.80), _edge("contradict", True, 0.80))
    assert _facet_confidence(a, "Contested", ()) == (0.0, "Moderate confidence")


def test_supported_without_material_support_is_zero_lower():
    a = _assessment(_edge("support", False, 0.90), _edge("contradict", True, 0.70))
    assert _facet_confidence(a, "Supported", ()) == (0.0, "Lower confidence")


def test_qualify_and_context_are_excluded():
    a = _assessment(
        _edge("qualify", True, 0.95),
        _edge("context", True, 0.95),
        _edge("support", True, 0.60),
    )
    score, _ = _facet_confidence(a, "Supported", ())
    assert score == 0.39  # only the 0.60 support edge counts


def test_none_assessment_is_zero_lower():
    assert _facet_confidence(None, "Supported", ()) == (0.0, "Lower confidence")


def test_decided_outcome_invariant_band_equals_tier():
    # For any decided outcome the tier is exactly the band of the score.
    for scores in ([0.60], [0.95], [0.90, 0.88], [0.70, 0.71, 0.72]):
        edges = [_edge("support", True, s, document_id=f"doc:{i}") for i, s in enumerate(scores)]
        score, tier = _facet_confidence(_assessment(*edges), "Supported", ())
        assert _confidence_band(score) == tier


# --------------------------------------------------------------------------- #
# Whole-claim reconciliation (weakest-link)                                   #
# --------------------------------------------------------------------------- #


def _result(*facets):
    """facets: (facet_id, outcome, decisive, assessment) tuples."""
    verdict_facets = [
        SimpleNamespace(facet=fid, outcome=outcome, decisive=decisive)
        for fid, outcome, decisive, _ in facets
    ]
    facet_assessments = {fid: assessment for fid, _, _, assessment in facets}
    return SimpleNamespace(
        verdict=SimpleNamespace(facets=verdict_facets),
        facet_assessments=facet_assessments,
    )


def test_reconcile_claim_is_weakest_decisive_facet():
    strong = _assessment(
        _edge("support", True, 0.90, document_id="doc:a"),
        _edge("support", True, 0.88, document_id="doc:b"),
    )  # -> Higher
    lone = _assessment(_edge("support", True, 0.938))  # -> Moderate 0.610
    result = _result(
        ("c1", "Supported", True, strong),
        ("c2", "Supported", True, lone),
    )
    facet_conf, claim_score, claim_tier = _reconcile_confidence(result)
    assert facet_conf["c1"][1] == "Higher confidence"
    assert facet_conf["c2"][1] == "Moderate confidence"
    # Weakest-link: the claim is only as sure as c2.
    assert claim_score == 0.610
    assert claim_tier == "Moderate confidence"


def test_reconcile_ignores_undecisive_facets():
    decisive = _assessment(_edge("support", True, 0.60))  # Lower 0.39
    ignored = _assessment(
        _edge("support", True, 0.90, document_id="doc:a"),
        _edge("support", True, 0.88, document_id="doc:b"),
    )  # Higher, but not decisive
    result = _result(
        ("c1", "Supported", True, decisive),
        ("c2", "Supported", False, ignored),
    )
    _, claim_score, claim_tier = _reconcile_confidence(result)
    assert claim_score == 0.39
    assert claim_tier == "Lower confidence"


def test_reconcile_no_decisive_facets_is_zero_lower():
    result = _result(("c1", "Supported", False, _assessment(_edge("support", True, 0.9))))
    _, claim_score, claim_tier = _reconcile_confidence(result)
    assert claim_score == 0.0
    assert claim_tier == "Lower confidence"
