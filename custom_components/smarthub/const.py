"""Constants for the SmartHub integration."""

DOMAIN = "smarthub"

# Configuration keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_ACCOUNT_ID = "account_id"
CONF_LOCATION_ID = "location_id"
CONF_HOST = "host"
CONF_POLL_INTERVAL = "poll_interval"

# Default values
DEFAULT_POLL_INTERVAL = 60  # 1 hour in minutes (more frequent for energy monitoring)
MIN_POLL_INTERVAL = 15  # Minimum 15 minutes
MAX_POLL_INTERVAL = 1440  # Maximum 24 hours

# API constants
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
SESSION_TIMEOUT = 300  # 5 minutes - force session refresh

# Sensor constants
ENERGY_SENSOR_KEY = "current_energy_usage"
ATTR_LAST_READING_TIME = "last_reading_time"
ATTR_ACCOUNT_ID = "account_id"
ATTR_LOCATION_ID = "location_id"
LOCATION_KEY = "location"
