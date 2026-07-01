FROM python:3.14-slim

LABEL org.opencontainers.image.title="Gemini SRT Translator for Bazarr" \
      org.opencontainers.image.description="A Bazarr companion app that translates configured source subtitles with gemini-srt-translator." \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ARG INSTALL_FFMPEG=false
RUN if [ "$INSTALL_FFMPEG" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends ffmpeg \
      && rm -rf /var/lib/apt/lists/*; \
    fi

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r /app/requirements.txt

COPY worker.py /app/worker.py
COPY gst_worker /app/gst_worker
COPY static /app/static

CMD ["python", "/app/worker.py"]
