"""Tests for utility functions."""
import hashlib
from zoneinfo import ZoneInfo

from homeassistant.components.recorder.statistics import valid_statistic_id

from custom_components.smarthub.utils import (
    assign_unique_meter_fragments,
    normalize_meter_id,
    parse_epoch_set_timezone,
    sanitize_host,
)

def test_normalize_meter_id():
    """Meter ids must become valid lowercase statistic-id fragments."""
    assert normalize_meter_id("1ND91111111") == "1nd91111111"
    assert normalize_meter_id("Main Meter") == "main_meter"
    assert normalize_meter_id("abc-123") == "abc_123"
    assert normalize_meter_id("A__B") == "a_b"
    assert normalize_meter_id("ok_id") == "ok_id"
    assert normalize_meter_id("---") == "meter"
    assert normalize_meter_id("") == "meter"

def _suffix(meter_id: str) -> str:
    return hashlib.sha256(meter_id.encode("utf-8")).hexdigest()[:8]

def test_assign_unique_meter_fragments_keeps_non_colliding_ids():
    """Normal ids stay on normalize_meter_id so existing statistics keep matching."""
    assert assign_unique_meter_fragments(["1ND91111111"]) == {"1ND91111111": "1nd91111111"}
    assert assign_unique_meter_fragments(["A-B"]) == {"A-B": "a_b"}
    assert assign_unique_meter_fragments(["MAIN-1", "OFF-2"]) == {
        "MAIN-1": "main_1",
        "OFF-2": "off_2",
    }
    # Duplicate rows for one physical meter share one fragment.
    assert assign_unique_meter_fragments(["MAIN-1", "MAIN-1"]) == {"MAIN-1": "main_1"}

def test_assign_unique_meter_fragments_suffixes_collisions():
    """A-B and A B must not both become a_b. The suffix is stable and order-independent."""
    hyphen = f"a_b_{_suffix('A-B')}"
    space = f"a_b_{_suffix('A B')}"
    assert hyphen != space

    forward = assign_unique_meter_fragments(["A-B", "A B"])
    reverse = assign_unique_meter_fragments(["A B", "A-B"])
    assert forward == reverse == {"A-B": hyphen, "A B": space}
    # A third, non-colliding meter keeps its historical fragment.
    with_other = assign_unique_meter_fragments(["A B", "OFF-2", "A-B"])
    assert with_other["OFF-2"] == "off_2"
    assert with_other["A-B"] == hyphen
    assert with_other["A B"] == space

    for fragment in (hyphen, space):
        assert valid_statistic_id(f"smarthub:smarthub_energy_sensor_123_1_{fragment}")
        assert "__" not in fragment

def test_sanitize_host():
    """Test that the host is correctly sanitized."""
    test_cases = [
        ("core.smarthub.coop/", "core.smarthub.coop"),
        ("https://core.smarthub.coop", "core.smarthub.coop"),
        ("https://core.smarthub.coop/", "core.smarthub.coop"),
        ("core.smarthub.coop", "core.smarthub.coop"),
        ("http://core.smarthub.coop", "core.smarthub.coop"),
        ("", ""),
        (None, ""),
    ]

    for input_host, expected_host in test_cases:
        assert sanitize_host(input_host) == expected_host

def test_parse_epoch_set_timezone():
    """Test that the epoch parser works as expected"""
    test_cases = [
        (1770285600, ZoneInfo("America/Los_Angeles"), "2026-02-05T10:00:00-08:00"), # Non TZ date : '2026-02-05T10:00:00'
        (1770285600.000, ZoneInfo("America/Los_Angeles"), "2026-02-05T10:00:00-08:00"), # Non TZ date : '2026-02-05T10:00:00'
        (1770285600.000, ZoneInfo("America/New_York"), "2026-02-05T10:00:00-05:00"), # Non TZ date : '2026-02-05T10:00:00'
    ]

    for input_epoch, input_tz, expected_iso in test_cases:
        assert parse_epoch_set_timezone(input_epoch, input_tz).isoformat() == expected_iso
