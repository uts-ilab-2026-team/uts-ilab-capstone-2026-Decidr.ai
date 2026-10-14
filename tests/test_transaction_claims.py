import pytest

from decidr.transaction_claims import parse_transaction_claim

CLAIM = "CASE-782 Jordan approved 37% discount before the contract was signed."


def test_supported_word_orders_and_unsupported_extra_assertions():
    assert parse_transaction_claim(
        "Jordan approved a 37 percent discount for CASE-782 before the contract was signed"
    )
    assert parse_transaction_claim("For CASE-782, Jordan Lee approved 37% discount")
    for text in [
        CLAIM + " Also the customer paid.",
        CLAIM.replace("37%", "137%"),
        CLAIM.replace("approved", "did not approve"),
    ]:
        assert parse_transaction_claim(text) is None


@pytest.mark.parametrize(
    "claim",
    [
        "Jordan approved 37% discount in principle",
        "Jordan approved 37% discount on Teams and the customer paid",
        "CASE-782 Jordan approved 37% discount for CASE-783",
        "Jordan approved 37% discount after signing",
        "Jordan approved 37% discount on Teams via email",
    ],
)
def test_unsupported_assertions_cannot_be_discarded(claim):
    assert parse_transaction_claim(claim) is None
