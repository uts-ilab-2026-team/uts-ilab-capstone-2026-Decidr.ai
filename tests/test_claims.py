from decidr.claims import check_atomicity, split_claim
from decidr.models import AtomicClaim


def _claim(text: str = "Discount approval is required.") -> AtomicClaim:
    return AtomicClaim(
        claim_id="C1",
        subject="discount",
        predicate="requires",
        object="approval",
        claim_type="decision_right",
        claim_text=text,
    )


def test_atomicity_flags_joined_propositions():
    result = check_atomicity("Finance approves discounts and Sales records the approval.")

    assert result.status == "potentially_compound"
    assert len(result.suggested_components) == 2


def test_split_preserves_original_wording():
    original = _claim("Finance approves and Sales records.")

    children = split_claim(original, ["Finance approves.", "Sales records."])

    assert [item.claim_id for item in children] == ["C1.1", "C1.2"]
    assert all(item.original_claim_text == original.claim_text for item in children)
    assert all(item.parent_claim_id == "C1" for item in children)
