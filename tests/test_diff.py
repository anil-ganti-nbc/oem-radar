from oem_radar.core.config import SeverityRule
from oem_radar.core.diff import diff, score
from oem_radar.core.models import Availability, ChangeEvent, ChangeType, Component, Configuration, Severity

from test_models import make_product

KEY = "src:k12"


def test_diff_identity_is_empty():
    p = make_product()
    assert diff(p, p, KEY) == []


def test_new_product_is_breaking():
    events = diff(None, make_product(), KEY)
    assert [e.change_type for e in events] == [ChangeType.NEW_PRODUCT]
    assert events[0].severity == Severity.BREAKING


def test_component_and_spec_changes_detected_and_scored():
    before = make_product()
    after = make_product(cpu=Component(raw="AMD Ryzen AI Max+ 396"), memory="128 GB")
    events = {e.change_type: e for e in diff(before, after, KEY)}
    assert events[ChangeType.COMPONENT_CHANGED].severity == Severity.SIGNIFICANT
    assert events[ChangeType.SPEC_CHANGED].field == "memory"
    assert events[ChangeType.SPEC_CHANGED].severity == Severity.SIGNIFICANT


def test_unseen_component_rule_outranks_plain_component_change():
    e = ChangeEvent(product_key=KEY, change_type=ChangeType.COMPONENT_CHANGED,
                    field="cpu", meta={"unseen_component": True})
    assert score(e) == Severity.BREAKING  # the star signal (DIFF_ENGINE.md §4)


def test_description_whitespace_noise_is_not_a_change():
    before = make_product(description="Fast  mini PC")
    after = make_product(description="Fast mini\nPC")
    assert diff(before, after, KEY) == []


def test_config_rules_override_defaults():
    quiet = [SeverityRule(match={"change_type": "images_changed"}, severity=1),
             SeverityRule(match={}, severity=2)]
    e = ChangeEvent(product_key=KEY, change_type=ChangeType.IMAGES_CHANGED, field="images")
    assert score(e, quiet) == Severity.NOISE
    assert score(e) == Severity.NOTABLE  # default table


def test_configuration_availability_transition_is_an_editorial_event():
    """Known SKU + preorder opening must not require a new URL or product."""
    before = make_product(configurations=[Configuration(
        sku="SKU-1", label="16GB / 512GB", availability=Availability.PREORDER,
    )])
    after = make_product(configurations=[Configuration(
        sku="SKU-1", label="16GB / 512GB", availability=Availability.IN_STOCK,
    )])

    events = diff(before, after, KEY)

    assert len(events) == 1
    event = events[0]
    assert event.change_type == ChangeType.AVAILABILITY_CHANGED
    assert event.field == "configurations.availability"
    assert event.old_value == {"configuration": "SKU-1", "availability": "preorder"}
    assert event.new_value == {"configuration": "SKU-1", "availability": "in_stock"}
    assert event.severity == Severity.NOTABLE


def test_configuration_transition_to_unknown_is_not_treated_as_unavailable():
    before = make_product(configurations=[Configuration(
        sku="SKU-1", availability=Availability.IN_STOCK,
    )])
    after = make_product(configurations=[Configuration(
        sku="SKU-1", availability=Availability.UNKNOWN,
    )])

    assert diff(before, after, KEY) == []
