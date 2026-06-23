#!/usr/bin/env bash
set -euo pipefail

VIDEO_PATH="${1:-}"
SUBTITLE_PATH="${2:-}"
LANGUAGE="${3:-}"
PROVIDER="${4:-}"
SERIES_ID="${5:-}"
MEDIA_ID="${6:-}"
QUEUE_DIR="${GST_QUEUE_DIR:-/config/postprocess/queue}"
TARGETS_FILE="${GST_TARGETS_FILE:-/config/postprocess/targets.json}"

mkdir -p "$QUEUE_DIR/pending" "$QUEUE_DIR/processing" "$QUEUE_DIR/done" "$QUEUE_DIR/failed"

provider_lc="$(printf '%s' "$PROVIDER" | tr '[:upper:]' '[:lower:]')"
language_lc="$(printf '%s' "$LANGUAGE" | cut -d: -f1 | tr '[:upper:]' '[:lower:]')"

if [ "$provider_lc" != "embeddedsubtitles" ]; then
  echo "skip: provider=$PROVIDER"
  exit 0
fi

MEDIA_TYPE="movie"
if [ -n "$SERIES_ID" ]; then
  MEDIA_TYPE="series"
fi

export VIDEO_PATH SUBTITLE_PATH LANGUAGE PROVIDER SERIES_ID MEDIA_ID MEDIA_TYPE QUEUE_DIR TARGETS_FILE
python3 - <<'PY'
import json
import os
import pathlib
import hashlib
import time

queue = pathlib.Path(os.environ["QUEUE_DIR"])
targets_file = pathlib.Path(os.environ["TARGETS_FILE"])
subtitle_path = os.environ["SUBTITLE_PATH"]
source_code = os.environ["LANGUAGE"].split(":", 1)[0].strip().lower()

if targets_file.exists():
    config = json.loads(targets_file.read_text(encoding="utf-8"))
else:
    config = {
        "source_languages": [{"code": "en", "language": "English", "enabled": True}],
        "target_languages": [{"code": "zh", "language": "Simplified Chinese", "enabled": True}],
    }

if isinstance(config, list):
    sources = [{"code": "en", "language": "English", "enabled": True}]
    targets = config
else:
    sources = config.get("source_languages") or [{"code": "en", "language": "English", "enabled": True}]
    targets = config.get("target_languages") or [{"code": "zh", "language": "Simplified Chinese", "enabled": True}]

def enabled(items):
    for item in items:
        if not isinstance(item, dict) or item.get("enabled", True) is False:
            continue
        code = str(item.get("code") or item.get("code2") or "").strip()
        language = str(item.get("language") or item.get("name") or "").strip()
        if code and language:
            yield {"code": code, "language": language}

source = None
for candidate in enabled(sources):
    if candidate["code"].lower() == source_code:
        source = candidate
        break

if source is None:
    print(f"skip: source_language={os.environ['LANGUAGE']}")
    raise SystemExit(0)

def output_path_for(code):
    if not subtitle_path.lower().endswith(".srt"):
        return f"{subtitle_path}.{code}.srt"
    prefix = subtitle_path[:-4]
    parts = prefix.split(".")
    for idx in range(len(parts) - 1, -1, -1):
        if parts[idx].lower() == source["code"].lower():
            parts[idx] = code
            return ".".join(parts) + ".srt"
    return f"{prefix}.{code}.srt"

created = []
for target in enabled(targets):
    code = target["code"]
    language = target["language"]
    if code.lower() == source["code"].lower():
        continue
    output_path = output_path_for(code)
    if pathlib.Path(output_path).exists():
        continue
    job_id = hashlib.sha1(f"{subtitle_path}|{output_path}|{code}".encode("utf-8")).hexdigest()
    pending = queue / "pending" / f"{job_id}.json"
    processing = queue / "processing" / f"{job_id}.json"
    if pending.exists() or processing.exists():
        continue
    tmp = pending.with_name(f".{job_id}.tmp")
    job = {
        "job_id": job_id,
        "created_at": int(time.time()),
        "video_path": os.environ["VIDEO_PATH"],
        "subtitle_path": subtitle_path,
        "output_path": output_path,
        "language": os.environ["LANGUAGE"],
        "source_code": source["code"],
        "source_language": source["language"],
        "target_code": code,
        "target_language": language,
        "provider": os.environ["PROVIDER"],
        "series_id": os.environ["SERIES_ID"],
        "media_id": os.environ["MEDIA_ID"],
        "media_type": os.environ["MEDIA_TYPE"],
    }
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    tmp.replace(pending)
    created.append(job_id)

if created:
    print("queued: " + ",".join(created))
else:
    print("skip: no target jobs created")
PY
