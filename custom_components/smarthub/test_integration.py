"""Test file for basic SmartHub integration functionality."""
import pytest
import asyncio
from unittest.mock import Mock, patch
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from custom_components.smarthub import async_setup_entry, async_unload_entry
from custom_components.smarthub.api import SmartHubAPI, parse_last_usage, SmartHubAPIError
from custom_components.smarthub.const import DOMAIN


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="SmartHub Test",
        data={
            "email": "test@example.com",
            "password": "testpass",
            "account_id": "123456",
            "location_id": "789012",
            "host": "test.smarthub.coop",
            "poll_interval": 60,
        },
        unique_id="test@example.com_test.smarthub.coop_123456",
    )


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock(spec=HomeAssistant)
    hass.data = {}
    return hass


def test_parse_last_usage_valid_data():
    """Test parsing valid usage data."""
    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "series": [
                        {
                            "data": [
                                {"x": 1640995200000, "y": 100.5},
                                {"x": 1641081600000, "y": 150.2},
                            ]
                        }
                    ]
                }
            ]
        }
    }
    
    result = parse_last_usage(test_data)
    
    assert result is not None
    assert result["current_energy_usage"] == 150.2
    assert "last_reading_time" in result


def test_parse_last_usage_no_data():
    """Test parsing when no usage data is available."""
    test_data = {"data": {"ELECTRIC": []}}
    
    result = parse_last_usage(test_data)
    
    assert result is None


def test_parse_last_usage_invalid_data():
    """Test parsing invalid data raises appropriate error."""
    with pytest.raises(Exception):
        parse_last_usage("invalid_data")


@pytest.mark.asyncio
async def test_async_setup_entry_success(mock_hass, mock_config_entry):
    """Test successful setup of config entry."""
    with patch("custom_components.smarthub.SmartHubAPI") as mock_api_class:
        mock_api = Mock()
        mock_api.get_token.return_value = "test_token"
        mock_api_class.return_value = mock_api
        
        with patch("custom_components.smarthub.hass.config_entries.async_forward_entry_setups"):
            result = await async_setup_entry(mock_hass, mock_config_entry)
            
            assert result is True
            assert DOMAIN in mock_hass.data
            assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_setup_entry_connection_failure(mock_hass, mock_config_entry):
    """Test setup failure due to connection error."""
    with patch("custom_components.smarthub.SmartHubAPI") as mock_api_class:
        mock_api = Mock()
        mock_api.get_token.side_effect = SmartHubAPIError("Connection failed")
        mock_api_class.return_value = mock_api
        
        with pytest.raises(Exception):
            await async_setup_entry(mock_hass, mock_config_entry)


@pytest.mark.asyncio
async def test_smarthub_api_basic_functionality():
    """Test basic SmartHub API functionality."""
    api = SmartHubAPI(
        email="test@example.com",
        password="testpass",
        account_id="123456",
        location_id="789012",
        host="test.smarthub.coop"
    )
    
    # Test that API object is created correctly
    assert api.email == "test@example.com"
    assert api.account_id == "123456"
    assert api.location_id == "789012"
    assert api.host == "test.smarthub.coop"
    assert api.token is None


if __name__ == "__main__":
    # Run basic tests
    test_parse_last_usage_valid_data()
    test_parse_last_usage_no_data()
    print("Basic tests passed!")