# HomeAssistant Smarthub energy sensor

This is a custom integration used to scrape data from a smarthub portal (used by different energy providers), and create an energy usage sensor in Home Assistant. The sensor can then be used with the Energy dashboard.

# Setup

## Installation

### Manual Installation

Clone this repository in your home assistant's `custom_components` directory:
```
git clone git@github.com:gagata/ha-smarthub-energy-sensor.git
```

### Using HACS

You can use the following shortcut

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gagata&repository=ha-smarthub-energy-sensor)


Or add the custom repository to your HACS installation:

- Copy the repository address: `https://github.com/gagata/ha-smarthub-energy-sensor.git`
- Add the repository as custom repository in HACS: HACS -> click on 3-dot menu -> Custom Repositories -> Paste the URL and pick "Integration" and click "ADD"
- Go to HACS and search for `SmartHub Coop Integration` and click "Download"



## Configuration

Go to Settings > Devices & services and click +Add integration, and search for Smarthub.

The wizard will ask for:
- email address used to log in to the portal
- user password
- host (most likely `<your_provider>.smarthub.coop`)
- your account id (taken from the billing)
- your **location id** (instruction below)
- poll interval (in minutes, 12 hours by default)


**Getting the location id**

- This value can be retrieved using `Network` tab in Developer Tools in your browser.
- Navigate to Usage Explorer page, find a call to `services/secured/utility-usage/poll` in the `Network` tab.
- Open the call, and copy the `serviceLocationNumber` field from the `Payload` tab.


# Limitations
- The API provides data with a delay, the integration just reports the current total for the unbilled period
- The integration currently only sets the usage (doesn't set the cost sensor)
- It hardcodes to only lookup `ENERGY` data (no gas information)


# Credits
Thanks [@tedpearson](https://github.com/tedpearson) for his [go implementation](https://github.com/tedpearson/electric-usage-downloader) which inspired this integration.

# This sucks, can you even write proper HA integrations?
Nope, and I don't intend to, as I genuinely despise Python. Feel free to use as is, but I'll also happily accept PRs to make this thing better :)
