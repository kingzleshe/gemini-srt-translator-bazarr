FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

LABEL org.opencontainers.image.title="Gemini SRT Translator for Bazarr" \
      org.opencontainers.image.description="A Bazarr companion app that translates configured source subtitles with gemini-srt-translator." \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

ARG INSTALL_FFMPEG=false
RUN if [ "$INSTALL_FFMPEG" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends ffmpeg \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY pyproject.toml uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

COPY worker.py /app/worker.py
COPY gst_worker /app/gst_worker
COPY static /app/static

CMD ["python", "/app/worker.py"]
