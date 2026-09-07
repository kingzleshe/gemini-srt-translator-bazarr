from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import enabled_target_languages
from .subtitles import target_output_path
from .translation import DailyQuotaExceededError, ProviderUnavailableError
from .translation_attempt import DEFAULT_ATTEMPT
from .queue_policy import PROVIDER_RETRY_DELAYS, daily_quota_retry_at, provider_retry_decision


QUEUE_STATES = ("pending", "processing", "deferred", "done", "failed")


def _write_job(path: Path, job: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.stem}.tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _move_job(source: Path, destination: Path, error: str | None = None) -> None:
    source.replace(destination)
    source.with_suffix(".error").unlink(missing_ok=True)
    error_path = destination.with_suffix(".error")
    if error is None:
        error_path.unlink(missing_ok=True)
    else:
        error_path.write_text(error, encoding="utf-8")


def _reset_retry(job: dict[str, Any]) -> None:
    for key in ("provider_retry_count", "retry_at", "deferred_reason", "last_error"):
        job.pop(key, None)


def daily_quota_pause_until(queue_dir: str, now: float | None = None) -> float | None:
    try:
        pause = json.loads((Path(queue_dir) / "provider-pause.json").read_text(encoding="utf-8"))
        retry_at = float(pause.get("retry_at") or 0) if isinstance(pause, dict) else 0
        if isinstance(pause, dict) and pause.get("reason") == "daily-quota" and retry_at > (time.time() if now is None else now):
            return retry_at
    except (OSError, TypeError, ValueError):
        pass
    return None


def reject_daily_quota(queue_dir: str) -> None:
    if daily_quota_pause_until(queue_dir) is not None:
        raise ValueError("Daily Gemini quota exhausted; new jobs and retries are disabled until the quota pause expires.")


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
    reject_daily_quota(queue_dir)
    ensure_queue_dirs(queue_dir)
    failed = Path(queue_dir) / "failed" / f"{job_id}.json"
    pending = Path(queue_dir) / "pending" / f"{job_id}.json"
    if not failed.exists() or pending.exists():
        return False
    try:
        job = json.loads(failed.read_text(encoding="utf-8"))
        _reset_retry(job)
        _write_job(failed, job)
    except (OSError, TypeError, ValueError):
        pass
    _move_job(failed, pending)
    return True


def cancel_failed_job(queue_dir: str, job_id: str) -> bool:
    """Permanently remove a failed job without scheduling another attempt."""
    return delete_queue_job(queue_dir, "failed", job_id)


def delete_queue_job(queue_dir: str, state: str, job_id: str) -> bool:
    if state not in QUEUE_STATES:
        return False
    path = Path(queue_dir) / state / f"{job_id}.json"
    if not path.exists():
        return False
    path.unlink()
    error = path.with_suffix(".error")
    if error.exists():
        error.unlink()
    return True


def enqueue_translation_jobs(
    queue_dir: str,
    base_job: dict[str, Any],
    targets: list[dict[str, Any]],
) -> list[str]:
    reject_daily_quota(queue_dir)
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
        deferred = Path(queue_dir) / "deferred" / f"{jid}.json"
        if pending.exists() or processing.exists() or deferred.exists():
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
        _write_job(pending, job)
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
            if state == "processing":
                job.update(DEFAULT_ATTEMPT.progress(job))
            if state in {"deferred", "failed"}:
                error_path = path.with_suffix(".error")
                if error_path.exists():
                    job["error"] = error_path.read_text(encoding="utf-8")[-2000:]
                elif job.get("last_error"):
                    job["error"] = str(job["last_error"])[-2000:]
            jobs.append(job)
        snapshot[state] = jobs
    return snapshot


class JobQueue:
    """Own queue state transitions; execute work through an injected callback."""

    def __init__(self, queue_dir: str) -> None:
        self.queue_dir = Path(queue_dir)
        ensure_queue_dirs(queue_dir)

    def recover_interrupted_jobs(self) -> None:
        """Return work interrupted by a service restart to the pending queue."""
        for processing_path in sorted((self.queue_dir / "processing").glob("*.json")):
            pending_path = self.queue_dir / "pending" / processing_path.name
            if pending_path.exists():
                logging.warning("Keeping interrupted job %s in processing; pending copy already exists", processing_path.name)
                continue
            try:
                job = json.loads(processing_path.read_text(encoding="utf-8"))
                job["stage"] = "Recovered after service restart"
                job["updated_at"] = time.time()
                _write_job(processing_path, job)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
            _move_job(processing_path, pending_path)
            logging.info("Recovered interrupted job %s to pending", processing_path.name)

    def _fail_waiting_quota_jobs(self) -> None:
        for state in ("pending", "deferred"):
            for path in (self.queue_dir / state).glob("*.json"):
                destination = self.queue_dir / "failed" / path.name
                try:
                    _move_job(
                        path, destination,
                        "Daily Gemini quota exhausted; automatic retry cancelled. Submit again after the quota pause expires.",
                    )
                except FileNotFoundError:
                    continue

    def _promote_deferred_jobs(self, now: float) -> None:
        for deferred_path in sorted(
            (self.queue_dir / "deferred").glob("*.json"),
            key=lambda path: path.stat().st_mtime,
        ):
            try:
                job = json.loads(deferred_path.read_text(encoding="utf-8"))
                retry_at = float(job.get("retry_at") or 0)
            except Exception:
                retry_at = 0
            if retry_at > now:
                continue
            pending_path = self.queue_dir / "pending" / deferred_path.name
            if pending_path.exists():
                continue
            _move_job(deferred_path, pending_path)

    def _ready_job_path(self, settle_seconds: int, now: float | None = None) -> Path | None:
        current_time = time.time() if now is None else now
        if daily_quota_pause_until(str(self.queue_dir), current_time) is not None:
            self._fail_waiting_quota_jobs()
            return None
        self._promote_deferred_jobs(current_time)
        settle_seconds = max(0, settle_seconds)
        jobs = sorted((self.queue_dir / "pending").glob("*.json"), key=lambda path: path.stat().st_mtime)
        for job_path in jobs:
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
                subtitle_path = Path(str(job.get("subtitle_path") or ""))
                # The settle window protects an actively written subtitle, not
                # the queue event.  A manually queued, already-stable subtitle
                # should therefore start immediately.
                settled_from = subtitle_path.stat().st_mtime if subtitle_path.exists() else float(
                    job.get("created_at") or job_path.stat().st_mtime
                )
            except Exception:
                return job_path
            if current_time - settled_from >= settle_seconds:
                return job_path
        return None

    def process_once(
        self,
        execute: Callable[[dict[str, Any], Callable[[str], None]], str],
        *,
        settle_seconds: int = 0,
        now: float | None = None,
    ) -> bool:
        current_time = time.time() if now is None else now
        job_path = self._ready_job_path(settle_seconds, now=current_time)
        if job_path is None:
            return False

        processing_path = self.queue_dir / "processing" / job_path.name
        try:
            _move_job(job_path, processing_path)
        except FileNotFoundError:
            return False

        started = time.monotonic()
        error = None
        try:
            job = json.loads(processing_path.read_text(encoding="utf-8"))
            def update_status(stage: str) -> None:
                job["started_at"] = float(job.get("started_at") or time.time())
                job["updated_at"] = time.time()
                job["stage"] = stage
                _write_job(processing_path, job)

            logging.info("Job %s started | %s | %s -> %s", processing_path.stem,
                         Path(str(job.get("subtitle_path", ""))).name,
                         job.get("source_code", "?"), job.get("target_code", "?"))
            update_status("Starting translation")
            status = execute(job, update_status)
            _reset_retry(job)
            _write_job(processing_path, job)
            destination = self.queue_dir / "done" / processing_path.name
            logging.info("Job %s finished | status=%s | duration=%.1fs", processing_path.stem, status, time.monotonic() - started)
        except DailyQuotaExceededError as exc:
            failure_time = time.time()
            retry_at = daily_quota_retry_at(failure_time)
            job.pop("retry_at", None)
            job.pop("deferred_reason", None)
            job["last_error"] = str(exc)
            _write_job(processing_path, job)
            destination = self.queue_dir / "failed" / processing_path.name
            error = str(exc)
            _write_job(
                self.queue_dir / "provider-pause.json",
                {"retry_at": retry_at, "reason": "daily-quota", "error": str(exc)},
            )
            self._fail_waiting_quota_jobs()
            logging.warning("Job %s stopped: daily Gemini quota exhausted. New jobs blocked until %s; waiting jobs marked failed.",
                            processing_path.stem, datetime.fromtimestamp(retry_at, timezone.utc).isoformat())
        except ProviderUnavailableError as exc:
            decision = provider_retry_decision(int(job.get("provider_retry_count") or 0), time.time())
            if decision.state == "deferred":
                retry_count = decision.retry_count or 0
                failure_time = time.time()
                retry_at = decision.retry_at or failure_time
                job["provider_retry_count"] = retry_count
                job["retry_at"] = retry_at
                job["deferred_reason"] = "provider-unavailable"
                job["last_error"] = str(exc)
                _write_job(processing_path, job)
                destination = self.queue_dir / "deferred" / processing_path.name
                error = str(exc)
                logging.warning(
                    "Gemini unavailable; job %s deferred until %s (retry %s/%s)",
                    processing_path.name,
                    datetime.fromtimestamp(retry_at, timezone.utc).isoformat(),
                    retry_count,
                    len(PROVIDER_RETRY_DELAYS),
                )
            else:
                destination = self.queue_dir / "failed" / processing_path.name
                error = str(exc)
                logging.error(
                    "Gemini remained unavailable after %s delayed retries; job %s failed",
                    len(PROVIDER_RETRY_DELAYS),
                    processing_path.name,
                )
        except Exception as exc:
            destination = self.queue_dir / "failed" / processing_path.name
            error = str(exc)
            logging.exception("Job %s failed after %.1fs: %s", processing_path.stem, time.monotonic() - started, str(exc).splitlines()[0][:240] if str(exc) else type(exc).__name__)

        destination.parent.mkdir(parents=True, exist_ok=True)
        _move_job(processing_path, destination, error)
        return True
