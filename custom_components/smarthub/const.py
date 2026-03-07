"""Constants for the SmartHub integration."""

DOMAIN = "smarthub"

# Configuration keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_ACCOUNT_ID = "account_id"
CONF_LOCATION_ID = "location_id"
CONF_HOST = "host"
CONF_POLL_INTERVAL = "poll_interval"
CONF_TIMEZONE = "timezone"
CONF_MFA_TOTP = "mfa_totp"

# Default values
DEFAULT_POLL_INTERVAL = 360  # 6 hour in minutes
MIN_POLL_INTERVAL = 15  # Minimum 15 minutes
MAX_POLL_INTERVAL = 1440  # Maximum 24 hours

# API constants
DEFAULT_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
SESSION_TIMEOUT = 300  # 5 minutes - force session refresh
HISTORICAL_IMPORT_DAYS = 90 # number of days for initial import

# Sensor constants
ENERGY_SENSOR_KEY = "current_energy_usage"
ATTR_LAST_READING_TIME = "last_reading_time"
ATTR_ACCOUNT_ID = "account_id"
ATTR_LOCATION_ID = "location_id"
LOCATION_KEY = "location"
METER_NAME   = "meter_name"

# List of supported services provided by the smarthub endpoint
ELECTRIC_SERVICE = "Electric Service"
SUPPORTED_SERVICES = [ELECTRIC_SERVICE]
