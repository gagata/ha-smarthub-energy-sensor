"""Tests for utility functions."""
from zoneinfo import ZoneInfo
from custom_components.smarthub.utils import sanitize_host, parse_epoch_set_timezone, normalize_meter_id

def test_normalize_meter_id():
    """Meter ids must become valid lowercase statistic-id fragments."""
    assert normalize_meter_id("1ND91111111") == "1nd91111111"
    assert normalize_meter_id("Main Meter") == "main_meter"
    assert normalize_meter_id("abc-123") == "abc_123"
    assert normalize_meter_id("A__B") == "a_b"
    assert normalize_meter_id("ok_id") == "ok_id"
    assert normalize_meter_id("---") == "meter"
    assert normalize_meter_id("") == "meter"

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
