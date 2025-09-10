"""Exceptions for SmartHub integration."""


class SmartHubError(Exception):
    """Base class for SmartHub errors."""


class SmartHubConfigError(SmartHubError):
    """Configuration error."""


class SmartHubConnectionError(SmartHubError):
    """Connection error."""


class SmartHubAuthenticationError(SmartHubError):
    """Authentication error."""


class SmartHubDataError(SmartHubError):
    """Data parsing error."""


class SmartHubTimeoutError(SmartHubError):
    """Request timeout error."""