FROM python:3.12-slim

ARG VERSION=2.0.1
LABEL org.opencontainers.image.title="RTI AD-series MQTT Bridge" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/srhunt-cyber/RTI-AD8x-Home-Assistant-bridge"

ENV PYTHONUNBUFFERED=1 \
    RTI_CONFIG=/config/config.yaml

WORKDIR /app
COPY bridge/requirements.txt /app/bridge/requirements.txt
RUN pip install --no-cache-dir -r /app/bridge/requirements.txt
COPY bridge /app/bridge

RUN useradd --system --uid 10001 --home-dir /app rti-bridge
USER rti-bridge

ENTRYPOINT ["python", "/app/bridge/rti_ad8x_bridge.py"]
