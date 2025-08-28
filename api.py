"""SmartHub API client for Home Assistant integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import ClientTimeout, ClientError

from .const import DEFAULT_TIMEOUT, MAX_RETRIES, RETRY_DELAY

_LOGGER = logging.getLogger(__name__)


class SmartHubAPIError(Exception):
    """Base exception for SmartHub API errors."""


class SmartHubAuthError(SmartHubAPIError):
    """Authentication error."""


class SmartHubConnectionError(SmartHubAPIError):
    """Connection error."""


class SmartHubDataError(SmartHubAPIError):
    """Data parsing error."""


def parse_last_usage(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse the JSON data and extract the last data point for usage.

    Args:
        data: The JSON data as a Python dictionary.

    Returns:
        A dictionary containing the usage data and metadata, or None if not found.
    
    Raises:
        SmartHubDataError: If there's an error parsing the data.
    """
    try:
        if not isinstance(data, dict):
            raise SmartHubDataError("Invalid data format: expected dictionary")

        # Locate the "ELECTRIC" data
        electric_data = data.get("data", {}).get("ELECTRIC", [])
        if not electric_data:
            _LOGGER.warning("No ELECTRIC data found in response")
            return None

        for entry in electric_data:
            # Find the entry with type "USAGE"
            if entry.get("type") == "USAGE":
                series = entry.get("series", [])
                for serie in series:
                    # Extract the last data point in the "data" array
                    usage_data = serie.get("data", [])
                    if usage_data:
                        last_data_point = usage_data[-1]
                        timestamp = last_data_point.get("x")
                        value = last_data_point.get("y")
                        
                        if value is None:
                            _LOGGER.warning("No usage value found in last data point")
                            continue
                            
                        # Convert timestamp to readable format if available
                        reading_time = None
                        if timestamp:
                            try:
                                # Assuming timestamp is in milliseconds
                                reading_time = datetime.fromtimestamp(timestamp / 1000).isoformat()
                            except (ValueError, TypeError) as e:
                                _LOGGER.warning("Could not parse timestamp %s: %s", timestamp, e)

                        return {
                            "current_energy_usage": float(value),
                            "last_reading_time": reading_time,
                            "raw_timestamp": timestamp,
                        }

        _LOGGER.warning("No USAGE data found in ELECTRIC entries")
        return None

    except Exception as e:
        raise SmartHubDataError(f"Error parsing usage data: {e}") from e


class SmartHubAPI:
    """Class to interact with the SmartHub API."""

    def __init__(
        self,
        email: str,
        password: str,
        account_id: str,
        location_id: str,
        host: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the SmartHub API client."""
        self.email = email
        self.password = password
        self.account_id = account_id
        self.location_id = location_id
        self.host = host
        self.timeout = timeout
        self.token: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(ssl=True, limit=10),
            )
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_token(self) -> str:
        """
        Authenticate and retrieve the token asynchronously.
        
        Returns:
            The authentication token.
            
        Raises:
            SmartHubAuthError: If authentication fails.
            SmartHubConnectionError: If there's a connection error.
        """
        auth_url = f"https://{self.host}/services/oauth/auth/v2"
        headers = {
            "Authority": self.host,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "HomeAssistant SmartHub Integration",
        }
        payload = f"password={self.password}&userId={self.email}"

        _LOGGER.debug("Sending authentication request to: %s", auth_url)

        try:
            session = await self._get_session()
            async with session.post(auth_url, headers=headers, data=payload) as response:
                response_text = await response.text()
                _LOGGER.debug("Auth response status: %s", response.status)

                if response.status == 401:
                    raise SmartHubAuthError("Invalid credentials")
                elif response.status != 200:
                    raise SmartHubConnectionError(
                        f"Authentication failed with HTTP status: {response.status}"
                    )

                try:
                    response_json = await response.json()
                except Exception as e:
                    raise SmartHubDataError(f"Invalid JSON response: {e}") from e

                self.token = response_json.get("authorizationToken")
                if not self.token:
                    raise SmartHubAuthError("No authorization token in response")

                _LOGGER.debug("Successfully retrieved authentication token")
                return self.token

        except ClientError as e:
            raise SmartHubConnectionError(f"Connection error during authentication: {e}") from e

    async def get_energy_data(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve energy usage data asynchronously with retry logic.
        
        Returns:
            Parsed energy usage data or None if no data available.
            
        Raises:
            SmartHubAPIError: If the request fails after retries.
        """
        if not self.token:
            await self.get_token()

        poll_url = f"https://{self.host}/services/secured/utility-usage/poll"
        headers = {
            "Authority": self.host,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Nisc-Smarthub-Username": self.email,
            "User-Agent": "HomeAssistant SmartHub Integration",
        }

        # Calculate startDateTime and endDateTime
        now = datetime.now()
        # Get data for the last 30 days ending at 5 PM today
        end_time = now.replace(hour=17, minute=0, second=0, microsecond=0)
        start_time = end_time - timedelta(days=30)

        start_timestamp = int(start_time.timestamp()) * 1000
        end_timestamp = int(end_time.timestamp()) * 1000

        data = {
            "timeFrame": "MONTHLY",
            "userId": self.email,
            "screen": "USAGE_EXPLORER",
            "includeDemand": False,
            "serviceLocationNumber": self.location_id,
            "accountNumber": self.account_id,
            "industries": ["ELECTRIC"],
            "startDateTime": str(start_timestamp),
            "endDateTime": str(end_timestamp),
        }

        _LOGGER.debug("Requesting energy data from: %s", poll_url)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                session = await self._get_session()
                async with session.post(poll_url, headers=headers, json=data) as response:
                    _LOGGER.debug("Attempt %d: Response status: %s", attempt, response.status)

                    if response.status == 401:
                        # Token expired, try to get a new one
                        if attempt == 1:
                            _LOGGER.info("Token expired, refreshing...")
                            await self.get_token()
                            continue
                        else:
                            raise SmartHubAuthError("Authentication failed after token refresh")
                    elif response.status != 200:
                        raise SmartHubConnectionError(
                            f"HTTP error {response.status}: {await response.text()}"
                        )

                    try:
                        response_json = await response.json()
                    except Exception as e:
                        raise SmartHubDataError(f"Invalid JSON response: {e}") from e

                    # Check if the status is still pending
                    status = response_json.get("status")
                    if status == "PENDING":
                        _LOGGER.debug("Attempt %d: Status is PENDING, retrying...", attempt)
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(RETRY_DELAY)
                            continue
                        else:
                            _LOGGER.warning("Maximum retries reached, data still PENDING")
                            return None
                    elif status == "COMPLETE":
                        _LOGGER.debug("Successfully retrieved energy data")
                        return parse_last_usage(response_json)
                    else:
                        _LOGGER.warning("Unexpected status in response: %s", status)
                        return None

            except ClientError as e:
                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "Attempt %d failed with connection error: %s, retrying...", 
                        attempt, e
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                else:
                    raise SmartHubConnectionError(
                        f"Connection failed after {MAX_RETRIES} attempts: {e}"
                    ) from e

        raise SmartHubAPIError(f"Failed to retrieve data after {MAX_RETRIES} attempts")

