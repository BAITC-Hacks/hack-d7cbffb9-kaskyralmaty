FROM ghcr.io/astral-sh/uv:0.12.18 AS uv
FROM python:3.11.13-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --extra gpu --no-dev
COPY meeting_protocol ./meeting_protocol
COPY scripts ./scripts
COPY data ./data
ENV HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 HF_HOME=/models
ENTRYPOINT ["bash", "scripts/gpu-python.sh"]
CMD ["-m", "uvicorn", "meeting_protocol.web:app", "--host", "0.0.0.0", "--port", "8001"]
