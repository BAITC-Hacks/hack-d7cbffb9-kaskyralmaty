FROM ghcr.io/astral-sh/uv:0.12.18@sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc AS uv
FROM python:3.11.13-slim-bookworm@sha256:86adf8dbadc3d6e82ee5dd2c74bec2e1c2467cdad47886280501df722372d2e1
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
