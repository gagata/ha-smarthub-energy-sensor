"""Utility functions for SmartHub integration."""

def sanitize_host(host: str) -> str:
    """Sanitize host: remove protocol and trailing slashes."""
    if not host:
        return ""
    return host.split("://")[-1].rstrip("/")
