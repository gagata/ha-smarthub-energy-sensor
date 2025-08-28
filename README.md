# Home Assistant SmartHub Energy Sensor Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/github/v/release/salmeister/ha-smarthub-energy-sensor)](https://github.com/salmeister/ha-smarthub-energy-sensor/releases)
[![License](https://img.shields.io/github/license/salmeister/ha-smarthub-energy-sensor)](LICENSE)

A production-ready Home Assistant custom integration that connects to SmartHub Coop energy portals to provide real-time electricity usage data. This integration is fully compatible with Home Assistant's Energy Dashboard and provides reliable, stable monitoring for your energy consumption.

## ✨ Features

- 🔌 **Energy Dashboard Integration**: Seamlessly works with Home Assistant's built-in Energy Dashboard
- 📊 **Real-time Monitoring**: Tracks your electricity usage with configurable polling intervals
- 🔒 **Secure Authentication**: Robust credential handling with proper error management
- 🔄 **Automatic Retry**: Built-in retry logic for reliable data collection
- 🎛️ **Easy Configuration**: User-friendly configuration flow with input validation
- 🏠 **Device Integration**: Creates proper device entities for better organization
- 📱 **Production Ready**: Comprehensive error handling and logging for stability

## 🚀 Installation

### Option 1: HACS (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on the three-dot menu and select "Custom repositories"
3. Add this repository URL: `https://github.com/salmeister/ha-smarthub-energy-sensor`
4. Select "Integration" as the category
5. Click "ADD" and then search for "SmartHub Energy"
6. Click "Download" to install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=salmeister&repository=ha-smarthub-energy-sensor)

### Option 2: Manual Installation

1. Download the latest release from the [releases page](https://github.com/salmeister/ha-smarthub-energy-sensor/releases)
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
│       └── strings/
│           └── en.json
```

## ⚙️ Configuration

### Requirements

Before setting up the integration, you'll need to gather the following information from your SmartHub portal:

1. **Email Address**: Your login email for the SmartHub portal
2. **Password**: Your SmartHub portal password
3. **Host**: Your energy provider's SmartHub domain (e.g., `yourprovider.smarthub.coop`)
4. **Account ID**: Found on your billing statements
5. **Location ID**: Retrieved from the SmartHub portal (see instructions below)

### Getting Your Location ID

The Location ID is required for the integration to work properly. Here's how to find it:

1. Log into your SmartHub portal
2. Navigate to the "Usage Explorer" page
3. Open your browser's Developer Tools (F12)
4. Go to the "Network" tab
5. Refresh the page or navigate within the usage section
6. Look for a call to `services/secured/utility-usage/poll`
7. Click on this request and go to the "Payload" or "Request" tab
8. Copy the value of the `serviceLocationNumber` field

### Setup Process

1. Go to **Settings** → **Devices & Services**
2. Click **"+ Add Integration"**
3. Search for **"SmartHub"**
4. Follow the configuration wizard:
   - Enter your email address
   - Enter your password
   - Enter your account ID
   - Enter your location ID
   - Enter your SmartHub host
   - Set your preferred poll interval (15-1440 minutes, default: 60 minutes)

The integration will validate your credentials and create the energy sensor automatically.

## 📊 Energy Dashboard Integration

Once configured, your SmartHub energy sensor will automatically appear in Home Assistant with the correct device class and state class for energy monitoring.

### Adding to Energy Dashboard

1. Go to **Settings** → **Dashboards** → **Energy**
2. Click **"Add Consumption"** in the Electricity grid section
3. Select your SmartHub energy sensor from the dropdown
4. The sensor will now provide data to your Energy Dashboard

### Sensor Details

- **Device Class**: Energy
- **State Class**: Total Increasing
- **Unit**: kWh (Kilowatt Hours)
- **Icon**: Lightning bolt (mdi:lightning-bolt)

## 🔧 Configuration Options

| Option | Default | Range | Description |
|--------|---------|-------|-------------|
| Poll Interval | 60 minutes | 15-1440 minutes | How often to check for new energy data |

**Note**: SmartHub data typically updates every 15-60 minutes, so setting a very low poll interval may not provide more frequent updates but will increase API calls.

## 🛠️ Troubleshooting

### Common Issues

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
4. [Open an issue](https://github.com/salmeister/ha-smarthub-energy-sensor/issues) with logs and details

## 🔒 Security & Privacy

- Credentials are stored securely using Home Assistant's configuration encryption
- API calls use HTTPS with proper SSL verification
- No data is transmitted to third parties outside of your SmartHub provider
- Session tokens are properly managed and refreshed as needed

## 🤝 Contributing

Contributions are welcome! Please feel free to:

- Report bugs or issues
- Suggest new features
- Submit pull requests
- Improve documentation

## 📋 Limitations

- Data availability depends on your energy provider's SmartHub implementation
- Update frequency is limited by the provider's data refresh rate
- Currently supports electricity usage only (no gas or other utilities)
- Requires active SmartHub portal access

## 📜 Changelog

See [CHANGELOG.md](CHANGELOG.md) for detailed release notes and version history.

## 🙏 Credits

- Thanks to [@tedpearson](https://github.com/tedpearson) for the [Go implementation](https://github.com/tedpearson/electric-usage-downloader) that provided inspiration
- Original integration concept by [@gagata](https://github.com/gagata)
- Production improvements and maintenance by [@salmeister](https://github.com/salmeister)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.