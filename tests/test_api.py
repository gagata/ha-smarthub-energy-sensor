import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from custom_components.smarthub.api import SmartHubAPI

@pytest.mark.parametrize("password", [
    "simplepassword",
    "password with spaces",
    "password#with#hashes",
    "password&with&ampersands",
    "password?with?questions",
    "password%with%percents",
    "password+with+plus",
    "complex!@#$%^&*()_+-=[]{}|;':\",./<>?password"
])
@pytest.mark.asyncio
async def test_get_token_encoding(password):
    """Test get_token correctly handles and encodes various passwords."""
    email = "test+user@example.com"
    
    api = SmartHubAPI(
        email=email,
        password=password,
        account_id="123456",
        timezone="UTC",
        mfa_totp="",
        host="test.smarthub.coop"
    )

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value='{"authorizationToken": "fake_token"}')
    mock_response.json = AsyncMock(return_value={"authorizationToken": "fake_token"})

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    # Ensure the context manager works for 'async with session.post(...)'
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
    mock_session.post.return_value.__aexit__ = AsyncMock()

    with patch.object(SmartHubAPI, "_get_session", return_value=mock_session):
        token = await api.get_token()
        
        assert token == "fake_token"
        
        # Check the arguments to post
        args, kwargs = mock_session.post.call_args
        
        # We must use 'data' for form-encoded POST body, not 'params' for URL
        assert "data" in kwargs, "Credentials should be sent in the request body (data), not URL parameters"
        assert "params" not in kwargs or not kwargs["params"], "Credentials should not be sent as URL parameters"
        
        sent_payload = kwargs.get("data")
        assert sent_payload["password"] == password
        assert sent_payload["userId"] == email
