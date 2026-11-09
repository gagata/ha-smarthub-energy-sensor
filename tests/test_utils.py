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
    """Two new colliding ids stay distinct. The smaller raw id keeps the base."""
    hyphen = f"a_b_{_suffix('A-B')}"
    assert assign_unique_meter_fragments(["A-B", "A B"]) == {"A B": "a_b", "A-B": hyphen}
    assert assign_unique_meter_fragments(["A B", "A-B"]) == {"A B": "a_b", "A-B": hyphen}
    with_other = assign_unique_meter_fragments(["A-B", "OFF-2", "A B"])
    assert with_other["OFF-2"] == "off_2"
    assert with_other["A B"] == "a_b"
    assert with_other["A-B"] == hyphen
    assert valid_statistic_id(f"smarthub:smarthub_energy_sensor_123_1_{hyphen}")
    assert "__" not in hyphen

def test_saved_meter_fragment_does_not_change_when_colliders_come_and_go():
    """A fragment, once assigned, stays put if another meter appears or leaves."""
    first = assign_unique_meter_fragments(["A-B"])
    assert first == {"A-B": "a_b"}

    both = assign_unique_meter_fragments(["A B", "A-B"], saved=first)
    assert both["A-B"] == "a_b"
    assert both["A B"] == f"a_b_{_suffix('A B')}"

    # The original meter does not revert or get renamed when the collider leaves.
    assert assign_unique_meter_fragments(["A-B"], saved=both) == {"A-B": "a_b"}
    # The suffixed meter keeps the suffix even when it is the only one left.
    assert assign_unique_meter_fragments(["A B"], saved=both) == {"A B": both["A B"]}
    # A saved fragment stays reserved while its meter is absent.
    newcomer = assign_unique_meter_fragments(["A_B"], saved={"A-B": "a_b"})
    assert newcomer["A_B"] != "a_b"

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
