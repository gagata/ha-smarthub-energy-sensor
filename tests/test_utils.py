"""Tests for utility functions."""
from custom_components.smarthub.utils import sanitize_host

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
