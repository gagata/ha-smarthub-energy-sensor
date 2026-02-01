"""Test file for basic SmartHub integration functionality."""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthub import async_setup_entry
from custom_components.smarthub.api import SmartHubAPI, SmartHubAPIError
from custom_components.smarthub.const import DOMAIN


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    return MockConfigEntry(
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
            "timezone": "UTC",
            "mfa_totp": "",
        },
        unique_id="test@example.com_test.smarthub.coop_123456",
    )


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock(spec=HomeAssistant)
    hass.data = {}
    return hass

@pytest.fixture
def api_instance():
    """Create an API instance for testing."""
    return SmartHubAPI(
        email="test@example.com",
        password="testpass",
        account_id="123456",
        timezone="UTC",
        mfa_totp="",
        host="test.smarthub.coop"
    )

def test_parse_usage_valid_data(api_instance):
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
    
    result = api_instance.parse_usage(test_data)
    
    assert result is not None
    assert "USAGE" in result
    assert len(result["USAGE"]) == 2
    assert result["USAGE"][1]["consumption"] == 150.2


def test_parse_usage_no_data(api_instance):
    """Test parsing when no usage data is available."""
    test_data = {"data": {"ELECTRIC": []}}
    
    result = api_instance.parse_usage(test_data)
    
    # parse_usage returns {} if no usage found (or rather, the dict might be empty of USAGE key)
    # Looking at code: parsed_response = {}, if len(electric_data) == 0 log warning. 
    # Returns parsed_response. So it returns {}.
    assert result == {}


def test_parse_usage_invalid_data(api_instance):
    """Test parsing invalid data raises appropriate error."""
    # The api.py raises SmartHubDataError if not dict.
    from custom_components.smarthub.api import SmartHubDataError
    with pytest.raises(SmartHubDataError):
        api_instance.parse_usage("invalid_data")


@pytest.mark.asyncio
async def test_async_setup_entry_success(mock_hass, mock_config_entry):
    """Test successful setup of config entry."""
    with patch("custom_components.smarthub.SmartHubAPI") as mock_api_class:
        mock_api = Mock()
        mock_api.get_token = AsyncMock(return_value="test_token")
        mock_api.close = AsyncMock()
        mock_api_class.return_value = mock_api
        
        with patch("custom_components.smarthub.SmartHubDataUpdateCoordinator") as mock_coordinator_cls:
             mock_coordinator = mock_coordinator_cls.return_value
             mock_coordinator.async_config_entry_first_refresh = AsyncMock()
             
             # Configure mock_hass to support await
             mock_hass.config_entries.async_forward_entry_setups = AsyncMock()

             result = await async_setup_entry(mock_hass, mock_config_entry)
            
             assert result is True
             # In the new code, runtime_data is set on entry
             assert hasattr(mock_config_entry, "runtime_data")


@pytest.mark.asyncio
async def test_async_setup_entry_connection_failure(mock_hass, mock_config_entry):
    """Test setup failure due to connection error."""
    with patch("custom_components.smarthub.SmartHubAPI") as mock_api_class:
        mock_api = Mock()
        mock_api.get_token = AsyncMock(side_effect=Exception("Connection failed"))
        mock_api.close = AsyncMock()
        mock_api_class.return_value = mock_api
        
        from homeassistant.exceptions import ConfigEntryError
        with pytest.raises(ConfigEntryError):
            await async_setup_entry(mock_hass, mock_config_entry)


def test_smarthub_api_basic_functionality():
    """Test basic SmartHub API functionality."""
    api = SmartHubAPI(
        email="test@example.com",
        password="testpass",
        account_id="123456",
        timezone="UTC",
        mfa_totp="123456",
        host="test.smarthub.coop"
    )
    
    # Test that API object is created correctly
    assert api.email == "test@example.com"
    assert api.account_id == "123456"
    assert api.timezone == "UTC"
    assert api.mfa_totp == "123456"
    assert api.host == "test.smarthub.coop"
    assert api.token is None