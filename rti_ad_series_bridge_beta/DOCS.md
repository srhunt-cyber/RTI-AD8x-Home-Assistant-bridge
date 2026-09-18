# RTI AD-series MQTT Bridge 2.0 app/add-on

This experimental Home Assistant packaging runs the same production 2.0 bridge
as the standalone Linux and Docker installations. The bridge core is
field-tested; the app/add-on packaging remains experimental.

## Before starting

Install and configure an MQTT broker first. For the official Mosquitto Broker
app, create a dedicated MQTT user and use `core-mosquitto` as the broker host.
The RTI amplifier and this app must be able to reach each other on the LAN.

Each amplifier accepts only one IP control connection. Stop any older bridge,
Telnet session, web control client, or RTI IP driver before starting this app.

## Configure

1. Start the app once. It creates `config.yaml` in this app's configuration
   directory and exits intentionally.
2. Open the app configuration directory with Studio Code Server or another
   file editor that can access app configuration files.
3. Set the MQTT host and credentials, then add each amplifier and its zones.
4. Start the app again and inspect its Log tab.

Keep `amp1`, `amp2`, and the current zone names during a v1.8 migration to
preserve MQTT topics and Home Assistant entity IDs. Leave
`use_source_names: false` to preserve numeric source selections.

Do not run this app and another RTI bridge at the same time.

Amplifier-default restoration is disabled and dry-run-only in the generated
configuration. Follow the staged procedure in `docs/DEPLOYMENT.md`; do not enable
automatic restoration until `CHECK` and one `ZONE` test have succeeded.

Version 2.0 can also generate MQTT-backed Home Assistant `media_player` entities.
The app itself cannot silently edit Home Assistant's main configuration. Use
the repository's `scripts/generate_ha_media_players.py` from another checkout,
copy the resulting YAML into `/config/packages`, and follow the one-zone test
in `docs/DEPLOYMENT.md`. The recommended `dual` mode preserves existing
dashboards while adding native speaker entities for media cards and Alexa.
