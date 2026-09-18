#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR=/opt/rti-ad8x-bridge
CONFIG_DIR=/etc/rti-ad8x-bridge
SERVICE_NAME=rti-ad8x-bridge.service
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ${EUID} -ne 0 ]]; then
  exec sudo --preserve-env=RTI_INSTALL_MQTT_PASSWORD bash "$0" "$@"
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This guided installer currently supports Debian and Ubuntu (apt)." >&2
  exit 2
fi

echo "RTI AD-series MQTT Bridge 2.0 installer"
read -r -p "Use an existing MQTT broker? [Y/n] " existing_broker
existing_broker=${existing_broker:-Y}

MQTT_HOST=""
MQTT_PORT=1883
MQTT_USER=""
if [[ ${existing_broker,,} == n* ]]; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y mosquitto mosquitto-clients openssl
  MQTT_HOST=localhost
  MQTT_USER=rti_bridge
  RTI_INSTALL_MQTT_PASSWORD=$(openssl rand -base64 24 | tr -d '\n')
  export RTI_INSTALL_MQTT_PASSWORD
  install -d -m 0755 /etc/mosquitto/conf.d
  mosquitto_passwd -b -c /etc/mosquitto/passwd "$MQTT_USER" "$RTI_INSTALL_MQTT_PASSWORD"
  chown mosquitto:mosquitto /etc/mosquitto/passwd
  chmod 0600 /etc/mosquitto/passwd
  install -m 0644 /dev/null /etc/mosquitto/conf.d/rti-ad8x.conf
  cat >/etc/mosquitto/conf.d/rti-ad8x.conf <<'EOF'
listener 1883
allow_anonymous false
password_file /etc/mosquitto/passwd
EOF
  systemctl enable --now mosquitto
  systemctl restart mosquitto
  echo "Installed a local authenticated Mosquitto broker."
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip

if ! getent passwd rti-ad8x >/dev/null; then
  useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin rti-ad8x
fi
install -d -o root -g root -m 0755 "$INSTALL_DIR/bridge" "$INSTALL_DIR/scripts"
install -d -o root -g rti-ad8x -m 0750 "$CONFIG_DIR"
install -m 0644 "$SOURCE_DIR/bridge/rti_ad8x_bridge.py" "$INSTALL_DIR/bridge/"
install -m 0644 "$SOURCE_DIR/bridge/config.py" "$INSTALL_DIR/bridge/"
install -m 0644 "$SOURCE_DIR/bridge/version.py" "$INSTALL_DIR/bridge/"
install -m 0644 "$SOURCE_DIR/bridge/requirements.txt" "$INSTALL_DIR/bridge/"
install -m 0755 "$SOURCE_DIR/scripts/configure.py" "$INSTALL_DIR/scripts/"
install -m 0755 "$SOURCE_DIR/scripts/generate_ha_media_players.py" "$INSTALL_DIR/scripts/"

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --disable-pip-version-check -r "$INSTALL_DIR/bridge/requirements.txt"

if [[ -f "$CONFIG_DIR/config.yaml" ]]; then
  echo "Keeping existing $CONFIG_DIR/config.yaml"
else
  wizard=("$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/scripts/configure.py"
          --output "$CONFIG_DIR/config.yaml")
  [[ -n "$MQTT_HOST" ]] && wizard+=(--mqtt-host "$MQTT_HOST")
  [[ -n "$MQTT_USER" ]] && wizard+=(--mqtt-user "$MQTT_USER")
  wizard+=(--mqtt-port "$MQTT_PORT")
  "${wizard[@]}"
fi

chown root:rti-ad8x "$CONFIG_DIR/config.yaml"
chmod 0640 "$CONFIG_DIR/config.yaml"
install -m 0644 "$SOURCE_DIR/bridge/systemd/rti-ad8x-bridge.service" \
  "/etc/systemd/system/$SERVICE_NAME"

"$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/bridge/rti_ad8x_bridge.py" \
  --config "$CONFIG_DIR/config.yaml" --check-config
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

echo
echo "Installed and started $SERVICE_NAME"
echo "Logs: journalctl -fu $SERVICE_NAME"
echo "Config: $CONFIG_DIR/config.yaml"
if [[ -n ${RTI_INSTALL_MQTT_PASSWORD:-} ]]; then
  echo "MQTT username: $MQTT_USER"
  echo "MQTT password: $RTI_INSTALL_MQTT_PASSWORD"
  echo "Save this password and configure Home Assistant's MQTT integration to use this broker."
fi
