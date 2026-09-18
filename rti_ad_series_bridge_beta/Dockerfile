FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION=2.0.0
ARG BUILD_ARCH
ARG RTI_REF=release/v2.0.0

LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="app" \
      io.hass.arch="${BUILD_ARCH}"

RUN apk add --no-cache python3 py3-pip py3-virtualenv curl && \
    python3 -m venv /opt/rti/.venv && \
    /opt/rti/.venv/bin/pip install --no-cache-dir \
      paho-mqtt==2.1.0 psutil==7.1.3 PyYAML==6.0.2 && \
    mkdir -p /opt/rti/bridge && \
    curl -fsSL "https://raw.githubusercontent.com/srhunt-cyber/RTI-AD8x-Home-Assistant-bridge/${RTI_REF}/bridge/rti_ad8x_bridge.py" \
      -o /opt/rti/bridge/rti_ad8x_bridge.py && \
    curl -fsSL "https://raw.githubusercontent.com/srhunt-cyber/RTI-AD8x-Home-Assistant-bridge/${RTI_REF}/bridge/config.py" \
      -o /opt/rti/bridge/config.py && \
    curl -fsSL "https://raw.githubusercontent.com/srhunt-cyber/RTI-AD8x-Home-Assistant-bridge/${RTI_REF}/bridge/version.py" \
      -o /opt/rti/bridge/version.py

COPY config.example.yaml /usr/share/rti/config.example.yaml
COPY run.sh /run.sh
RUN chmod 0755 /run.sh

CMD ["/run.sh"]
