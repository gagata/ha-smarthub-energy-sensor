# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
 * Support for MFA login via Timebased One Time Tokens
 * Support for historical hourly energy statistics
 * Auto-detection of location IDs, as well as support for multiple locations

### Changed
 * The state entity ID is now includes the locationID which is not migrated to the new ID value. Historical monthly state data will be orphaned.

### Removed

### Fixed

## v2.0.1 - 2025-09-10
### Fixed
* **🔑 Critical Authentication Fix**: Resolved "Authentication failed after token refresh" error that caused sensors to become unavailable after a few days
* **🔄 Session Management**: Improved session handling to prevent stale authentication state
* **⏰ Session Timeouts**: Added automatic session refresh after 5 minutes to prevent connection staleness
* **🛡️ Retry Logic**: Enhanced authentication retry logic to properly handle token expiration scenarios
* **🧹 Resource Cleanup**: Better cleanup of authentication state during refresh operations

### Added
* **🛠️ Manual Services**: Added `refresh_data` and `refresh_authentication` services for manual troubleshooting
* **📊 Enhanced Logging**: More detailed logging for authentication and session management issues
* **⚡ Session Lifecycle**: Automatic session recreation when authentication issues occur

### Changed
* **🔧 Authentication Flow**: Completely redesigned authentication refresh to eliminate session conflicts
* **🔒 Token Management**: Improved token lifecycle management with proper cleanup
* **📡 Error Handling**: Better distinction between authentication and connection errors

## v2.0.0 - 2025-08-28
### Added
* **🚀 Production-Ready Architecture**: Complete rewrite for stability and reliability
* **🔌 Full Energy Dashboard Integration**: Proper device class and state class for seamless Energy Dashboard compatibility
* **⚡ Enhanced Error Handling**: Comprehensive exception handling with specific error types
* **🔒 Improved Security**: Better credential validation and secure session management
* **📊 Type Safety**: Full type hints throughout the codebase for better maintainability
* **🎛️ Input Validation**: Robust validation for all configuration inputs including email, host, and numeric ranges
* **🔄 Advanced Retry Logic**: Smart retry mechanism with exponential backoff for API reliability
* **📱 Better User Experience**: Informative error messages and validation feedback
* **🌐 Internationalization**: Proper translation support with English strings
* **📋 Session Management**: Automatic session cleanup and proper connection pooling
* **🛠️ Debug Support**: Enhanced logging and debugging capabilities
* **📖 Documentation**: Comprehensive README with setup instructions and troubleshooting

### Changed
* **⏰ Default Poll Interval**: Reduced from 12 hours to 1 hour for more responsive monitoring
* **🏷️ Sensor Naming**: More descriptive sensor names including account information
* **📊 Device Information**: Enhanced device info with proper manufacturer and model details
* **🔧 Configuration Flow**: Improved UI with better validation and error messages
* **📦 Dependencies**: Updated aiohttp requirement to version 3.8.0+
* **🏠 Home Assistant Compatibility**: Updated for modern Home Assistant standards and best practices

### Removed
* **🗑️ Deprecated Patterns**: Removed outdated code patterns and improved architecture
* **🧹 Code Cleanup**: Eliminated redundant code and improved code organization

### Fixed
* **🐛 Authentication Issues**: Better handling of authentication failures and token refresh
* **🔗 Connection Stability**: Improved connection management and timeout handling
* **📊 Data Parsing**: More robust parsing of energy data with better error handling
* **🏷️ Unique ID Generation**: Fixed unique ID generation for stable entity management
* **🎯 Energy Dashboard Compatibility**: Proper device class and state class for energy monitoring
* **⚠️ Error Reporting**: Better error messages and logging for troubleshooting

### Security
* **🔐 Credential Protection**: Enhanced security for credential storage and transmission
* **🛡️ SSL Verification**: Proper SSL certificate verification for API calls
* **🚫 Data Privacy**: No data transmission to unauthorized third parties

## v1.1.0 - 2025-07-29
### Added
* **Enhanced Device Information (`device_info` property):**
    * The `SmartHubEnergySensor` now exposes a `device_info` property. This creates a conceptual "device" in Home Assistant's Device Registry, improving organization by grouping your sensor under a dedicated "Device" card in Settings > Devices & Services.
    * The device will display a user-friendly name (e.g., "YourHostName (Account: YourAccountID)"), manufacturer ("gagata"), and model ("Energy Monitor").
    * Includes a `configuration_url` for future direct access to the SmartHub web interface.

### Changed
* **Robust `unique_id` Generation:**
    * The method for generating the sensor's `unique_id` has been significantly improved for greater reliability and stability. It now primarily uses `config_entry.unique_id` (a stable identifier for the integration setup) and falls back to `config_entry.entry_id` for older configurations. This ensures stable and unique identifiers across Home Assistant restarts and reloads, preserving historical data, allowing customizations, and preventing duplicate entities.

### Fixed
* **Improved Debugging and Logging:**
    * Strategic `_LOGGER.debug` statements have been added throughout the `async_setup_entry` functions (in `__init__.py` and `sensor.py`) and within the `SmartHubEnergySensor` class. These provide detailed information for troubleshooting and development when debug logging is enabled.
* **Missing `state_class` Attribute for Existing Entities:**
    * Resolved an issue identified during further development of separate properties where the `state_class` attribute was missing for existing entities. This was fixed by moving `state_class` and `device_class` from separate properties back to attributes in `sensor.py`.
