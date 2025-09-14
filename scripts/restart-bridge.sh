#!/bin/bash

#!/bin/bash
# Restart RTI AD-8x MQTT bridge service

set -e

echo "Reloading systemd units..."
sudo systemctl daemon-reload

echo "Restarting bridge service..."
sudo systemctl restart rti-ad8x-mqtt-bridge.service

echo
echo "Service status:"
systemctl status rti-ad8x-mqtt-bridge.service --no-pager