"""Configuration errors must be caught before evidence assessment."""

from dataclasses import asdict
import json

import pytest

from framework import CONFIG_PATH
from framework.config import GraphCredibilityConfig
from framework.constants import CREDIBILITY_DIMENSIONS
from framework.errors import GraphValidationError

DIMENSION = CREDIBILITY_DIMENSIONS[0]


@pytest.fixture
def payload():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_payload(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return GraphCredibilityConfig.load(path)


def test_existing_configuration_loads_without_changing_values(tmp_path, payload):
    assert asdict(load_payload(tmp_path, payload)) == payload


@pytest.mark.parametrize("value", [0, 1])
def test_bounded_weights_accept_endpoints(tmp_path, payload, value):
    for name in (
        "materiality_threshold", "conflict_ratio", "undated_weight", "stale_weight"
    ):
        payload[name] = value
    for name in (
        "source_class_weights", "approval_weights", "lifecycle_multipliers"
    ):
        payload[name] = dict.fromkeys(payload[name], value)
    payload["recency_years"] = value

    assert asdict(load_payload(tmp_path, payload)) == payload


@pytest.mark.parametrize("value", [0.0, 2.0])
def test_dimension_weights_allow_zero_and_relative_weights(tmp_path, payload, value):
    payload["dimension_weights"][DIMENSION] = value

    config = load_payload(tmp_path, payload)

    assert config.dimension_weights[DIMENSION] == value


@pytest.mark.parametrize(
    "keys,value",
    [
        (("materiality_threshold",), -0.1),
        (("materiality_threshold",), 1.1),
        (("materiality_threshold",), True),
        (("conflict_ratio",), -0.1),
        (("conflict_ratio",), 1.1),
        (("undated_weight",), 1.1),
        (("stale_weight",), -0.1),
        (("dimension_weights", DIMENSION), -0.1),
        (("dimension_weights", DIMENSION), float("nan")),
        (("dimension_weights", DIMENSION), float("inf")),
        (("dimension_weights", DIMENSION), True),
        (("dimension_weights", DIMENSION), "0.5"),
        (("dimension_weights", DIMENSION), None),
        (("source_class_weights", "test-source"), 1.1),
        (("approval_weights", "approved"), -0.1),
        (("lifecycle_multipliers", "current"), 1.1),
        (("recency_years",), -1),
        (("recency_years",), 1.5),
        (("recency_years",), True),
        (("recency_years",), "5"),
        (("config_version",), ""),
        (("config_version",), None),
        (("dimension_weights",), []),
        (("source_class_weights",), None),
        (("approval_weights",), {"": 0.5}),
    ],
)
def test_invalid_values_raise_field_specific_errors(tmp_path, payload, keys, value):
    target = payload
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value

    with pytest.raises(GraphValidationError) as caught:
        load_payload(tmp_path, payload)

    assert keys[0] in str(caught.value)


@pytest.mark.parametrize("case", ["missing", "extra", "all-zero", "overflow"])
def test_invalid_dimension_sets_and_totals(tmp_path, payload, case):
    weights = payload["dimension_weights"]
    if case == "missing":
        del weights[DIMENSION]
    elif case == "extra":
        weights["undeclared-dimension"] = 1.0
    elif case == "all-zero":
        payload["dimension_weights"] = dict.fromkeys(weights, 0.0)
    else:
        payload["dimension_weights"] = dict.fromkeys(weights, 1e308)

    with pytest.raises(GraphValidationError):
        load_payload(tmp_path, payload)


@pytest.mark.parametrize("text", ["{broken", "[]", "null", "{}"])
def test_invalid_json_or_structure_raises_validation_error(tmp_path, text):
    path = tmp_path / "config.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(GraphValidationError):
        GraphCredibilityConfig.load(path)


def test_direct_construction_also_validates(payload):
    payload["conflict_ratio"] = True

    with pytest.raises(GraphValidationError, match="conflict_ratio"):
        GraphCredibilityConfig(**payload)
