# Home Assistant SmartHub Energy Sensor Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/github/v/release/gagata/ha-smarthub-energy-sensor)](https://github.com/gagata/ha-smarthub-energy-sensor/releases)
[![License](https://img.shields.io/github/license/gagata/ha-smarthub-energy-sensor)](LICENSE)

A Home Assistant custom integration that connects to SmartHub Coop energy portals to download the hourly or daily usage information. The integration populates historical electricity usage data, but does not show realtime data as that information is not available in SmartHub Coop energy portals. This integration is fully compatible with Home Assistant's Energy Dashboard, Net Mettering and provides reliable, stable monitoring for your energy consumption.

## ✨ Features

- 🔌 **Energy Dashboard Integration**: Seamlessly works with Home Assistant's built-in Energy Dashboard, including backfilling hourly metrics
- 📊 **Periodic Monitoring**: Tracks your electricity usage with configurable polling intervals
- 🔒 **Secure Authentication**: Robust credential handling with proper error management including Multi Factor Auth support
- 🔄 **Automatic Retry**: Built-in retry logic for reliable data collection
- 🎛️ **Easy Configuration**: User-friendly configuration flow with input validation
- 🏠 **Device Integration**: Creates proper device entities for better organization
- 📱 **Production Ready**: Comprehensive error handling and logging for stability

## 🚀 Installation

### Option 1: HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on the three-dot menu and select "Custom repositories"
3. Add this repository URL: `https://github.com/gagata/ha-smarthub-energy-sensor`
4. Select "Integration" as the category
5. Click "ADD" and then search for "SmartHub Energy"
6. Click "Download" to install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gagata&repository=ha-smarthub-energy-sensor)

### Option 2: Manual Installation

1. Download the latest release from the [releases page](https://github.com/gagata/ha-smarthub-energy-sensor/releases)
2. Extract the `smarthub` folder to your `custom_components` directory
3. Restart Home Assistant

```
config/
├── custom_components/
│   └── smarthub/
│       ├── __init__.py
│       ├── api.py
│       ├── config_flow.py
│       ├── const.py
│       ├── exceptions.py
│       ├── manifest.json
│       ├── sensor.py
│       ├── services.yaml
│       ├── strings.json
│       ├── icons/
│       │   ├── icon.svg
│       │   └── README.md
│       └── translations/
│           └── en.json
```

## ⚙️ Configuration

### Requirements

Version 2.1 and higher requires Home Assistant version 2025.11 and greater.

Before setting up the integration, you'll need to gather the following information from your SmartHub portal:

1. **Email Address**: Your login email for the SmartHub portal
2. **Password**: Your SmartHub portal password
3. **Host**: Your energy provider's SmartHub domain (e.g., `yourprovider.smarthub.coop`)
4. **Account ID**: Found on your billing statements

### Setup Process

1. Go to **Settings** → **Devices & Services**
2. Click **"+ Add Integration"**
3. Search for **"SmartHub"**
4. Follow the configuration wizard:
   - Enter your email address
   - Enter your password
   - Enter your account ID
   - Enter your SmartHub host
   - Set the TimeZone for your meter
   - Adjust the polling interval for how often it should query for new usage information

The integration will validate your credentials and create the energy sensor automatically.

## 📊 Energy Dashboard Integration

Once configured, your SmartHub energy sensor will automatically appear in Home Assistant with the correct device class and state class for energy monitoring.

### Adding to Energy Dashboard

1. Go to **Settings** → **Dashboards** → **Energy**
2. Click **"Add Consumption"** in the Electricity grid section
3. Select your SmartHub energy sensor from the dropdown
   Note: there will be multiple entries, 1 entity (monthly), and 2 Statistics (daily, hourly)- select one of the statistics which provide historical usage aligned with the your actual energy usage.
4. The sensor will now provide data to your Energy Dashboard

#### Solar or Net Metering
Different energy providers have different solar / net metering configurations. Your energy provider might provide data on how much energy you return to the grid, how much energy you consume, or a combination of both.

The integration should automatically determine the appropriate option, and provide an additional "return" hourly and daily statistic.

In the Energy dashboard set the Grid Consumption entry to the "usage" statistic, and the Return to Grid to the "return" statistic.

### Sensor Details

- **Device Class**: Energy
- **State Class**: Total Increasing
- **Unit**: kWh (Kilowatt Hours)
- **Icon**: Lightning bolt (mdi:lightning-bolt)

## 🔧 Configuration Options

By default, the integration will poll the SmartHub API every 6 hours. You can adjust this when re-configuring the integration to between 15-1440 minutes.

**Note**: SmartHub data typically updates every 15-60 minutes, so setting a very low poll interval may not provide more frequent updates but will increase API calls.

## 🛠️ Troubleshooting

### Common Issues

**Entity Not showing historical information**
- This is expected - the entity only stores the monthly value at the time it was polled. The integration also populates a historical `statistic` which aligns the time of use with the time the energy usage actually happened.

**"Cannot Connect" Error**
- Verify your SmartHub host is correct (without http:// or https://)
- Check your internet connection
- Ensure the SmartHub portal is accessible

**"Invalid Authentication" Error**
- Double-check your email and password
- Try logging into the SmartHub portal manually to verify credentials
- Some portals may have rate limiting - wait a few minutes and try again

**"No Data Available"**
- Verify your Account ID and Location ID are correct
- Check that your account has recent usage data in the SmartHub portal
- Some providers may have delays in data availability

**"Energy Statistics are offset from the right time"**
- Update the timezone where your SmartHub utility is located.
  This can be done easily via when you reconfigure the integration.

### Debug Logging

To enable debug logging for troubleshooting:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.smarthub: debug
```

### Support

If you encounter issues:

1. Check the Home Assistant logs for error messages
2. Verify all configuration parameters are correct
3. Test access to your SmartHub portal manually
4. Turn on the debug logs
5. [Open an issue](https://github.com/gagata/ha-smarthub-energy-sensor/issues) with logs and details

## 🔒 Security & Privacy

- Credentials are stored securely using Home Assistant's configuration encryption
- API calls use HTTPS with proper SSL verification
- No data is transmitted to third parties outside of your SmartHub provider
- Session tokens are properly managed and refreshed as needed

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

### Pull Request Process
1. Fork the repository and create a feature branch
2. Make your changes and ensure they follow the existing code style
3. Use the [PR template](.github/PULL_REQUEST_TEMPLATE.md) when opening your pull request
4. Select the appropriate change type in the PR template - this automatically labels your PR for release notes
5. Ensure your changes don't break existing functionality

### Code Style
- Follow Python PEP 8 standards
- Use type hints for new functions
- Add appropriate logging for debugging
- Keep error messages user-friendly

### What to Contribute
- Report bugs or issues
- Suggest new features
- Submit pull requests
- Improve documentation
- Add tests for new functionality

## 📋 Limitations

- Data availability depends on your energy provider's SmartHub implementation
- Update frequency is limited by the provider's data refresh rate
- Currently supports electricity usage only (no gas or other utilities)
- Requires active SmartHub portal access



## 🙏 Credits

- Thanks to [@tedpearson](https://github.com/tedpearson) for the [Go implementation](https://github.com/tedpearson/electric-usage-downloader) that provided inspiration
- Original integration concept by [@gagata](https://github.com/gagata)
- Production improvements and maintenance by [@gagata](https://github.com/gagata)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
