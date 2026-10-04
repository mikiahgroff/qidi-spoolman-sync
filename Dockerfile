FROM python:3.12-slim

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

RUN mkdir -p /data && chown appuser:appuser /data

USER appuser
VOLUME ["/data"]

CMD ["python", "-m", "qidi_spoolman_sync.main"]
