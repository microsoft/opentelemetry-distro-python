# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import pytest
from opentelemetry import baggage, context

from microsoft.opentelemetry.a365.core.middleware.baggage_builder import BaggageBuilder


def test_custom_attribute_sets_value_and_metadata():
    with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
        assert baggage.get_baggage("customer.tier") == "gold"
        assert baggage.get_baggage("_internal.custom_keys") == "customer.tier"


def test_custom_attributes_track_multiple_keys_in_order_without_duplicates():
    attributes = [
        ("customer.tier", "gold"),
        ("customer.region", "west"),
        ("customer.tier", "platinum"),
    ]

    with BaggageBuilder().custom_attributes(attributes).build():
        assert baggage.get_baggage("customer.tier") == "platinum"
        assert baggage.get_baggage("customer.region") == "west"
        assert baggage.get_baggage("_internal.custom_keys") == "customer.tier,customer.region"


def test_blank_custom_values_are_skipped_without_metadata():
    builder = BaggageBuilder().custom_attribute("customer.tier", " ")

    with builder.build():
        assert baggage.get_baggage("customer.tier") is None
        assert baggage.get_baggage("_internal.custom_keys") is None


@pytest.mark.parametrize("key", ["", "bad,key", "_internal.custom_keys"])
def test_custom_attribute_rejects_invalid_keys(key):
    with pytest.raises(ValueError):
        BaggageBuilder().custom_attribute(key, "value")


def test_set_pairs_does_not_mark_custom_metadata():
    with BaggageBuilder().set_pairs({"customer.tier": "gold"}).build():
        assert baggage.get_baggage("customer.tier") == "gold"
        assert baggage.get_baggage("_internal.custom_keys") is None


def test_baggage_scope_restores_previous_context():
    token = context.attach(baggage.set_baggage("customer.tier", "silver"))
    try:
        with BaggageBuilder().custom_attribute("customer.tier", "gold").build():
            assert baggage.get_baggage("customer.tier") == "gold"
        assert baggage.get_baggage("customer.tier") == "silver"
    finally:
        context.detach(token)
