# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
* **Enhanced Device Information (`device_info` property):**
    * The `SmartHubEnergySensor` now exposes a `device_info` property. This creates a conceptual "device" in Home Assistant's Device Registry, improving organization by grouping your sensor under a dedicated "Device" card in Settings > Devices & Services.
    * The device will display a user-friendly name (e.g., "YourHostName (Account: YourAccountID)"), manufacturer ("gagata"), and model ("Energy Monitor").
    * Includes a `configuration_url` for future direct access to the SmartHub web interface.

### Changed
* **Robust `unique_id` Generation:**
    * The method for generating the sensor's `unique_id` has been significantly improved for greater reliability and stability. It now primarily uses `config_entry.unique_id` (a stable identifier for the integration setup) and falls back to `config_entry.entry_id` for older configurations. This ensures stable and unique identifiers across Home Assistant restarts and reloads, preserving historical data, allowing customizations, and preventing duplicate entities.
### Removed
* **Nothing**
### Fixed
* **Improved Debugging and Logging:**
    * Strategic `_LOGGER.debug` statements have been added throughout the `async_setup_entry` functions (in `__init__.py` and `sensor.py`) and within the `SmartHubEnergySensor` class. These provide detailed information for troubleshooting and development when debug logging is enabled.
* **Missing `state_class` Attribute for Existing Entities:**
    * Resolved an issue where the `state_class` attribute was missing for existing entities. This was fixed by moving `state_class` and `device_class` from separate properties back to attributes in `sensor.py`.
