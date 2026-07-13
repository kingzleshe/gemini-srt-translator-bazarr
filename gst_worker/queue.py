from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .config import enabled_target_languages
from .subtitles import target_output_path


QUEUE_STATES = ("pending", "processing", "done", "failed")


def should_skip_job(job: dict[str, Any]) -> bool:
    provider = str(job.get("provider", "")).lower()
    language = str(job.get("source_code") or job.get("language") or "").split(":", 1)[0].lower()
    subtitle_path = str(job.get("subtitle_path", ""))
    target_code = str(job.get("target_code") or "zh")
    output_path = str(job.get("output_path") or target_output_path(subtitle_path, target_code, source_code=language))

    if provider and provider not in {"embeddedsubtitles", "gemini-console", "manual", "local"}:
        return True
    if language and language == target_code.lower():
        return True
    if not subtitle_path or not Path(subtitle_path).exists():
        return True
    return Path(output_path).exists()


def ensure_queue_dirs(queue_dir: str) -> None:
    root = Path(queue_dir)
    for state in QUEUE_STATES:
        (root / state).mkdir(parents=True, exist_ok=True)


def job_id_for(subtitle_path: str, output_path: str, target_code: str) -> str:
    raw = f"{subtitle_path}|{output_path}|{target_code}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def retry_failed_job(queue_dir: str, job_id: str) -> bool:
    ensure_queue_dirs(queue_dir)
    failed = Path(queue_dir) / "failed" / f"{job_id}.json"
    pending = Path(queue_dir) / "pending" / f"{job_id}.json"
    if not failed.exists() or pending.exists():
        return False
    error = failed.with_suffix(".error")
    failed.replace(pending)
    if error.exists():
        error.unlink()
    return True


def enqueue_translation_jobs(
    queue_dir: str,
    base_job: dict[str, Any],
    targets: list[dict[str, Any]],
) -> list[str]:
    ensure_queue_dirs(queue_dir)
    created: list[str] = []
    subtitle_path = str(base_job.get("subtitle_path", ""))
    if not subtitle_path or not Path(subtitle_path).exists():
        return created
    source_code = str(base_job.get("source_code") or base_job.get("language") or "en").split(":", 1)[0].strip()
    source_language = str(base_job.get("source_language") or source_code or "English")

    for target in enabled_target_languages({"target_languages": targets}):
        target_code = str(target["code"])
        if source_code.lower() == target_code.lower():
            continue
        output_path = str(base_job.get("output_path") or target_output_path(subtitle_path, target_code, source_code=source_code))
        if Path(output_path).exists():
            continue
        jid = job_id_for(subtitle_path, output_path, target_code)
        pending = Path(queue_dir) / "pending" / f"{jid}.json"
        processing = Path(queue_dir) / "processing" / f"{jid}.json"
        if pending.exists() or processing.exists():
            continue
        if retry_failed_job(queue_dir, jid):
            created.append(str(pending))
            continue

        job = {
            **base_job,
            "job_id": jid,
            "created_at": int(time.time()),
            "source_code": source_code,
            "source_language": source_language,
            "target_code": target_code,
            "target_language": str(target["language"]),
            "output_path": output_path,
        }
        tmp = pending.with_name(f".{jid}.tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        tmp.replace(pending)
        created.append(str(pending))
    return created


def queue_snapshot(queue_dir: str, limit: int = 100) -> dict[str, Any]:
    ensure_queue_dirs(queue_dir)
    root = Path(queue_dir)
    snapshot: dict[str, Any] = {"counts": {}, "total": 0}
    for state in QUEUE_STATES:
        jobs: list[dict[str, Any]] = []
        files = sorted((root / state).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        snapshot["counts"][state] = len(files)
        snapshot["total"] += len(files)
        for path in files[:limit]:
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                job = {"job_id": path.stem}
            job["_state"] = state
            job["_path"] = str(path)
            if state == "failed":
                error_path = path.with_suffix(".error")
                if error_path.exists():
                    job["error"] = error_path.read_text(encoding="utf-8")[-2000:]
            jobs.append(job)
        snapshot[state] = jobs
    return snapshot
