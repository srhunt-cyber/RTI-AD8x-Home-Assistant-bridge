#!/usr/bin/with-contenv bashio
set -Eeuo pipefail

config_file="$(bashio::config 'config_file')"
config_path="/config/${config_file}"

if [[ ! -f "$config_path" ]]; then
  cp /usr/share/rti/config.example.yaml "$config_path"
  chmod 0600 "$config_path"
  bashio::log.warning "Created ${config_path}. Edit it with your MQTT, amplifier, and zone settings, then restart this app."
  exit 2
fi

export RTI_CONFIG="$config_path"
exec /opt/rti/.venv/bin/python /opt/rti/bridge/rti_ad8x_bridge.py
