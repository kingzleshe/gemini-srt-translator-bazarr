#!/usr/bin/env python3
from __future__ import annotations

import argparse
import mimetypes
import json
import logging
import os
import shutil
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from gst_worker.backups import (
    backup_file_path,
    backup_info,
    create_backup,
    create_scheduled_backup_if_due,
    list_backups,
    purge_old_backups,
    restore_backup_archive,
)
from gst_worker.bazarr import (
    find_english_subtitle,
    find_source_subtitle,
    list_wanted_items,
    missing_enabled_targets,
    read_bazarr_api_key,
    refresh_bazarr,
)
from gst_worker.config import (
    DEFAULT_APP_CONFIG,
    DEFAULT_SOURCE_LANGUAGES,
    DEFAULT_TARGET_LANGUAGES,
    FALLBACK_LANGUAGES,
    GEMINI_LANGUAGE_NAMES,
    SECRET_MASK,
    SECRET_CONFIG_KEYS,
    GST_BOOL_CONFIG_KEYS,
    GST_STRING_CONFIG_KEYS,
    enabled_languages,
    enabled_source_languages,
    enabled_target_languages,
    load_app_config,
    normalize_app_config,
    normalize_bazarr_language,
    save_app_config,
    supported_languages,
)
from gst_worker.connection_tests import test_connection
from gst_worker.gemini import gemini_models
from gst_worker.http import HTTPClient, JsonFileCache, MemoryCache, cached_get_json, first_data
from gst_worker.queue import (
    QUEUE_STATES,
    cancel_failed_job,
    enqueue_translation_jobs,
    ensure_queue_dirs,
    job_id_for,
    queue_snapshot,
    retry_failed_job,
    should_skip_job,
)
from gst_worker.subtitles import (
    is_english_code,
    is_english_subtitle_path,
    scan_english_subtitles,
    scan_source_subtitles,
    subtitle_source_language,
    subtitle_video_guess,
    target_output_path,
    zh_output_path,
)
from gst_worker.tmdb import (
    TMDB_BASE_URL,
    build_movie_description,
    build_series_description,
    build_tmdb_description,
    extract_tmdb_movie_id,
    tmdb_find_movie_id,
    tmdb_find_tv_id,
)
from gst_worker.translation import (
    DailyQuotaExceededError,
    ProviderUnavailableError,
    build_gst_command,
    run_translation,
    translation_environment,
)


PROVIDER_RETRY_DELAYS = (120, 300, 900)
DAILY_QUOTA_PAUSE_SECONDS = 86_400


def load_settings(config_path: str | None = None) -> dict[str, Any]:
    app_config = load_app_config(config_path) if config_path else normalize_app_config({})
    bazarr_config_path = os.getenv("BAZARR_CONFIG_PATH", "/bazarr-config/config.yaml")
    bazarr_url = (
        str(app_config.get("bazarr_url") or "").strip()
        or os.getenv("BAZARR_URL", "http://bazarr:6767")
    ).rstrip("/")
    settings: dict[str, Any] = {
        "bazarr_url": bazarr_url,
        "bazarr_api_key": (
            str(app_config.get("bazarr_api_key") or "").strip()
            or os.getenv("BAZARR_API_KEY")
            or read_bazarr_api_key(bazarr_config_path)
        ),
        "gemini_api_key": (
            str(app_config.get("gemini_api_key") or "").strip()
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GEMINI_API_KEY1")
            or ""
        ),
        "gemini_api_key2": str(app_config.get("gemini_api_key2") or "").strip() or os.getenv("GEMINI_API_KEY2", ""),
        "tmdb_api_key": str(app_config.get("tmdb_api_key") or "").strip() or os.getenv("TMDB_API_KEY", ""),
    }
    for key in GST_STRING_CONFIG_KEYS:
        settings[key] = str(app_config.get(key) or "").strip()
    for key in GST_BOOL_CONFIG_KEYS:
        settings[key] = bool(app_config.get(key))
    settings["gst_batch_size"] = int(app_config.get("gst_batch_size") or 500)
    settings["gst_retry_batch_size"] = int(app_config.get("gst_retry_batch_size", 300))
    settings["gst_model"] = str(app_config.get("gst_model") or os.getenv("GST_MODEL", "gemini-flash-latest"))
    settings["job_settle_seconds"] = int(app_config.get("job_settle_seconds") or 0)
    if os.getenv("GST_BATCH_SIZE") and not app_config.get("gst_batch_size"):
        settings["gst_batch_size"] = int(os.getenv("GST_BATCH_SIZE", "500"))
    return settings


def public_app_config(config_path: str, settings: dict[str, str] | None = None) -> dict[str, Any]:
    runtime_settings = settings or load_settings(config_path)
    config = load_app_config(config_path)
    config["bazarr_url"] = runtime_settings["bazarr_url"]
    for key in SECRET_CONFIG_KEYS:
        config[key] = SECRET_MASK if runtime_settings.get(key, "") else ""
        config[f"{key}_configured"] = bool(runtime_settings.get(key, ""))
    return config


def settings_from_payload(config_path: str, body: dict[str, Any]) -> dict[str, str]:
    settings = load_settings(config_path)
    bazarr_url = str(body.get("bazarr_url") or "").strip().rstrip("/")
    if bazarr_url:
        settings["bazarr_url"] = bazarr_url
    for key in SECRET_CONFIG_KEYS:
        value = str(body.get(key) or "").strip()
        if value and value != SECRET_MASK:
            settings[key] = value
    return settings


def seed_app_config_from_settings(
    config_path: str,
    settings: dict[str, str],
    postprocess_targets_path: str | None = None,
) -> bool:
    config = load_app_config(config_path)
    changed = False
    if not config.get("bazarr_url") and settings.get("bazarr_url"):
        config["bazarr_url"] = settings["bazarr_url"]
        changed = True
    for key in SECRET_CONFIG_KEYS:
        if not config.get(key) and settings.get(key):
            config[key] = settings[key]
            changed = True
    if changed:
        save_app_config(config_path, config, postprocess_targets_path)
    return changed


def process_job(
    job: dict[str, Any],
    settings: dict[str, Any],
    cache: MemoryCache,
    http: HTTPClient,
    status_callback: Callable[[str], None] | None = None,
) -> str:
    if should_skip_job(job):
        logging.info("Skipping job for %s", job.get("subtitle_path"))
        return "skipped"

    if status_callback:
        status_callback("Resolving movie details")
    description = build_tmdb_description(
        job,
        bazarr=http,
        tmdb=http,
        bazarr_url=settings["bazarr_url"],
        bazarr_api_key=settings["bazarr_api_key"],
        tmdb_api_key=settings["tmdb_api_key"],
        cache=cache,
    )
    if status_callback:
        status_callback("Sending subtitle batches to Gemini")
    status = run_translation(job, description, settings)
    if status_callback:
        status_callback("Refreshing Bazarr")
    refresh_bazarr(job, http=http, bazarr_url=settings["bazarr_url"], api_key=settings["bazarr_api_key"])
    return status


class QueueWorker:
    def __init__(self, queue_dir: str, settings: dict[str, Any], cache: MemoryCache, http: HTTPClient) -> None:
        self.queue_dir = Path(queue_dir)
        self.settings = settings
        self.cache = cache
        self.http = http
        ensure_queue_dirs(str(self.queue_dir))
        self.recover_interrupted_jobs()

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
                processing_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
            processing_path.replace(pending_path)
            logging.info("Recovered interrupted job %s to pending", processing_path.name)

    @property
    def provider_pause_path(self) -> Path:
        return self.queue_dir / "provider-pause.json"

    def provider_pause_until(self, now: float) -> float | None:
        if not self.provider_pause_path.exists():
            return None
        try:
            pause = json.loads(self.provider_pause_path.read_text(encoding="utf-8"))
            retry_at = float(pause.get("retry_at") or 0)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self.provider_pause_path.unlink(missing_ok=True)
            return None
        if retry_at > now:
            return retry_at
        self.provider_pause_path.unlink(missing_ok=True)
        return None

    def promote_deferred_jobs(self, now: float) -> None:
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
            deferred_path.replace(pending_path)
            deferred_path.with_suffix(".error").unlink(missing_ok=True)

    def ready_job_path(self, now: float | None = None) -> Path | None:
        current_time = time.time() if now is None else now
        if self.provider_pause_until(current_time) is not None:
            return None
        self.promote_deferred_jobs(current_time)
        settle_seconds = max(0, int(self.settings.get("job_settle_seconds") or 0))
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

    def process_once(self, now: float | None = None) -> bool:
        current_time = time.time() if now is None else now
        job_path = self.ready_job_path(now=current_time)
        if job_path is None:
            return False

        processing_path = self.queue_dir / "processing" / job_path.name
        try:
            job_path.replace(processing_path)
        except FileNotFoundError:
            return False

        try:
            job = json.loads(processing_path.read_text(encoding="utf-8"))
            def update_status(stage: str) -> None:
                job["started_at"] = float(job.get("started_at") or time.time())
                job["updated_at"] = time.time()
                job["stage"] = stage
                processing_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")

            update_status("Starting translation")
            status = process_job(job, self.settings, self.cache, self.http, update_status)
            for key in ("retry_at", "deferred_reason", "last_error", "provider_retry_count"):
                job.pop(key, None)
            processing_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            destination = self.queue_dir / "done" / processing_path.name
            logging.info("Job %s finished with status: %s", processing_path.name, status)
        except DailyQuotaExceededError as exc:
            failure_time = time.time()
            retry_at = failure_time + DAILY_QUOTA_PAUSE_SECONDS
            job["retry_at"] = retry_at
            job["deferred_reason"] = "daily-quota"
            job["last_error"] = str(exc)
            processing_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            destination = self.queue_dir / "deferred" / processing_path.name
            destination.with_suffix(".error").write_text(str(exc), encoding="utf-8")
            self.provider_pause_path.write_text(
                json.dumps(
                    {"retry_at": retry_at, "reason": "daily-quota", "error": str(exc)},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            logging.warning("Daily Gemini quota exhausted; queue paused until %s", int(retry_at))
        except ProviderUnavailableError as exc:
            retry_count = int(job.get("provider_retry_count") or 0) + 1
            if retry_count <= len(PROVIDER_RETRY_DELAYS):
                failure_time = time.time()
                retry_at = failure_time + PROVIDER_RETRY_DELAYS[retry_count - 1]
                job["provider_retry_count"] = retry_count
                job["retry_at"] = retry_at
                job["deferred_reason"] = "provider-unavailable"
                job["last_error"] = str(exc)
                processing_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
                destination = self.queue_dir / "deferred" / processing_path.name
                destination.with_suffix(".error").write_text(str(exc), encoding="utf-8")
                logging.warning(
                    "Gemini unavailable; job %s deferred until %s (retry %s/%s)",
                    processing_path.name,
                    int(retry_at),
                    retry_count,
                    len(PROVIDER_RETRY_DELAYS),
                )
            else:
                destination = self.queue_dir / "failed" / processing_path.name
                destination.with_suffix(".error").write_text(str(exc), encoding="utf-8")
                logging.error(
                    "Gemini remained unavailable after %s delayed retries; job %s failed",
                    len(PROVIDER_RETRY_DELAYS),
                    processing_path.name,
                )
        except Exception as exc:
            destination = self.queue_dir / "failed" / processing_path.name
            error_path = destination.with_suffix(".error")
            error_path.write_text(str(exc), encoding="utf-8")
            logging.exception("Job %s failed", processing_path.name)

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(processing_path), str(destination))
        return True

    def run_forever(self, sleep_seconds: int) -> None:
        while True:
            did_work = self.process_once()
            if not did_work:
                time.sleep(sleep_seconds)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def read_binary_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        raise ValueError("request body is empty")
    return handler.rfile.read(length)


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


def clear_logs(log_dir: str) -> bool:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / "worker.log"
    log_path.write_text("", encoding="utf-8")
    return True


def backup_maintenance_once(state_dir: str, config_path: str, postprocess_targets_path: str) -> dict[str, Any] | None:
    return create_scheduled_backup_if_due(state_dir, config_path, postprocess_targets_path)


def run_backup_scheduler(state_dir: str, config_path: str, postprocess_targets_path: str, sleep_seconds: int) -> None:
    while True:
        try:
            backup = backup_maintenance_once(state_dir, config_path, postprocess_targets_path)
            if backup:
                logging.info("Scheduled backup created: %s", backup["path"])
        except Exception:
            logging.exception("Scheduled backup maintenance failed")
        time.sleep(sleep_seconds)


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "GeminiSRTConsole/1.0"

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        try:
            status_code = int(code)
        except (TypeError, ValueError):
            super().log_request(code, size)
            return
        if status_code >= 400:
            super().log_request(code, size)

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("web %s - %s", self.address_string(), fmt % args)

    @property
    def ctx(self) -> dict[str, Any]:
        return self.server.ctx  # type: ignore[attr-defined]

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 400) -> None:
        self.send_json({"error": message}, status=status)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/status":
                self.send_json(self.api_status())
            elif parsed.path == "/api/queue":
                self.send_json(queue_snapshot(self.ctx["queue_dir"]))
            elif parsed.path == "/api/settings":
                self.send_json(public_app_config(self.ctx["config_path"], self.ctx["settings"]))
            elif parsed.path == "/api/languages":
                settings = load_settings(self.ctx["config_path"])
                self.ctx["settings"] = settings
                self.send_json({"items": supported_languages(self.ctx["http"], settings["bazarr_url"], settings["bazarr_api_key"])})
            elif parsed.path == "/api/scan":
                config = load_app_config(self.ctx["config_path"])
                params = urllib.parse.parse_qs(parsed.query)
                limit = int(params.get("limit", [config["scan_limit"]])[0])
                self.send_json(
                    {
                        "items": scan_source_subtitles(
                            config["media_roots"],
                            config["source_languages"],
                            config["target_languages"],
                            limit=limit,
                        )
                    }
                )
            elif parsed.path == "/api/wanted":
                config = load_app_config(self.ctx["config_path"])
                settings = load_settings(self.ctx["config_path"])
                self.ctx["settings"] = settings
                self.send_json(
                    {
                        "items": list_wanted_items(
                            self.ctx["http"],
                            settings["bazarr_url"],
                            settings["bazarr_api_key"],
                            config["source_languages"],
                            config["target_languages"],
                            limit=int(config["scan_limit"]),
                        )
                    }
                )
            elif parsed.path == "/api/logs":
                self.send_json({"lines": self.tail_log()})
            elif parsed.path == "/api/gemini-models":
                settings = load_settings(self.ctx["config_path"])
                self.ctx["settings"] = settings
                self.send_json({"items": gemini_models(self.ctx["http"], settings)})
            elif parsed.path == "/api/backups":
                self.send_json({"items": list_backups(self.ctx["state_dir"])})
            elif parsed.path == "/api/backups/download":
                params = urllib.parse.parse_qs(parsed.query)
                backup = backup_file_path(self.ctx["state_dir"], params.get("name", [""])[0])
                self.send_file(backup, content_type="application/zip", attachment=True)
            else:
                self.serve_static(parsed.path)
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
        except Exception as exc:
            logging.exception("GET %s failed", self.path)
            self.send_error_json(str(exc), status=500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/backups/import":
                result = restore_backup_archive(
                    read_binary_body(self),
                    self.ctx["state_dir"],
                    self.ctx["config_path"],
                    self.ctx["postprocess_targets_path"],
                )
                settings = load_settings(self.ctx["config_path"])
                self.ctx["settings"] = settings
                if self.ctx.get("worker") is not None:
                    self.ctx["worker"].settings = settings
                self.send_json({"ok": True, **result})
                return

            body = read_json_body(self)
            if parsed.path == "/api/settings":
                saved = save_app_config(self.ctx["config_path"], body, self.ctx["postprocess_targets_path"])
                settings = load_settings(self.ctx["config_path"])
                self.ctx["settings"] = settings
                if self.ctx.get("worker") is not None:
                    self.ctx["worker"].settings = settings
                self.send_json(public_app_config(self.ctx["config_path"], settings))
            elif parsed.path == "/api/enqueue":
                config = load_app_config(self.ctx["config_path"])
                targets = config["target_languages"]
                target_codes = body.get("target_codes")
                if isinstance(target_codes, list) and target_codes:
                    wanted = {str(code) for code in target_codes}
                    targets = [target for target in targets if str(target["code"]) in wanted]
                created = enqueue_translation_jobs(
                    self.ctx["queue_dir"],
                    {
                        "video_path": body.get("video_path", ""),
                        "subtitle_path": body.get("subtitle_path", ""),
                        "provider": body.get("provider", "gemini-console"),
                        "source_code": body.get("source_code") or body.get("language") or "en",
                        "source_language": body.get("source_language") or "English",
                        "series_id": body.get("series_id", ""),
                        "media_id": body.get("media_id", ""),
                        "media_type": body.get("media_type") or body.get("type") or "movie",
                    },
                    targets,
                )
                self.send_json({"created": created, "count": len(created)})
            elif parsed.path == "/api/enqueue-scan":
                config = load_app_config(self.ctx["config_path"])
                items = scan_source_subtitles(
                    config["media_roots"],
                    config["source_languages"],
                    config["target_languages"],
                    limit=int(config["scan_limit"]),
                )
                created: list[str] = []
                for item in items:
                    created.extend(
                        enqueue_translation_jobs(
                            self.ctx["queue_dir"],
                            {
                                "video_path": item["video_path"],
                                "subtitle_path": item["subtitle_path"],
                                "provider": "gemini-console",
                                "source_code": item["source_code"],
                                "source_language": item["source_language"],
                                "media_type": "movie",
                            },
                            item["missing_targets"],
                        )
                    )
                self.send_json({"created": created, "count": len(created)})
            elif parsed.path == "/api/queue/retry":
                self.send_json({"ok": retry_failed_job(self.ctx["queue_dir"], str(body.get("job_id", "")))})
            elif parsed.path == "/api/queue/cancel":
                self.send_json({"ok": cancel_failed_job(self.ctx["queue_dir"], str(body.get("job_id", "")))})
            elif parsed.path == "/api/queue/delete":
                self.send_json(
                    {
                        "ok": delete_queue_job(
                            self.ctx["queue_dir"],
                            str(body.get("state", "")),
                            str(body.get("job_id", "")),
                        )
                    }
                )
            elif parsed.path == "/api/backups":
                self.send_json(
                    {
                        "backup": create_backup(
                            self.ctx["state_dir"],
                            self.ctx["config_path"],
                            self.ctx["postprocess_targets_path"],
                            reason="manual",
                        )
                    }
                )
            elif parsed.path == "/api/test-connection":
                settings = settings_from_payload(self.ctx["config_path"], body)
                self.send_json(test_connection(str(body.get("kind", "")), settings, self.ctx["http"]))
            elif parsed.path == "/api/logs/clear":
                self.send_json({"ok": clear_logs(self.ctx["log_dir"])})
            else:
                self.send_error_json("not found", status=404)
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
        except Exception as exc:
            logging.exception("POST %s failed", self.path)
            self.send_error_json(str(exc), status=500)

    def api_status(self) -> dict[str, Any]:
        settings = load_settings(self.ctx["config_path"])
        self.ctx["settings"] = settings
        status = {
            "queue": queue_snapshot(self.ctx["queue_dir"])["counts"],
            "settings": public_app_config(self.ctx["config_path"], settings),
            "bazarr_url": settings["bazarr_url"],
        }
        try:
            status["bazarr"] = self.ctx["http"].get_json(
                f"{settings['bazarr_url']}/api/system/ping",
                headers={"X-API-KEY": settings["bazarr_api_key"]},
            )
        except Exception as exc:
            status["bazarr"] = {"error": str(exc)}
        return status

    def tail_log(self, max_lines: int = 200) -> list[str]:
        log_path = Path(self.ctx["log_dir"]) / "worker.log"
        if not log_path.exists():
            return []
        return log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]

    def serve_static(self, request_path: str) -> None:
        static_dir = Path(self.ctx["static_dir"])
        rel = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        path = (static_dir / rel).resolve()
        if not str(path).startswith(str(static_dir.resolve())) or not path.exists() or not path.is_file():
            path = static_dir / "index.html"
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str, attachment: bool = False) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if attachment:
            name = path.name.replace('"', "")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        self.wfile.write(body)


def start_web_server(ctx: dict[str, Any], host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), ConsoleHandler)
    server.ctx = ctx  # type: ignore[attr-defined]
    logging.info("Gemini SRT Translator for Bazarr listening on http://%s:%s", host, port)
    server.serve_forever()


def configure_logging(log_dir: str) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(Path(log_dir) / "worker.log", encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="process one available job and exit")
    parser.add_argument("--worker-only", action="store_true", help="run queue worker without the web console")
    parser.add_argument("--no-worker", action="store_true", help="run web console without the background worker")
    parser.add_argument("--host", default=os.getenv("WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("WEB_PORT", "6789")))
    parser.add_argument("--sleep", type=int, default=int(os.getenv("WORKER_SLEEP_SECONDS", "15")))
    args = parser.parse_args()

    state_dir = os.getenv("STATE_DIR", "/state")
    queue_dir = os.getenv("QUEUE_DIR", "/queue")
    log_dir = os.getenv("LOG_DIR", f"{state_dir}/logs")
    config_path = os.getenv("APP_CONFIG_PATH", f"{state_dir}/config.json")
    postprocess_targets_path = os.getenv("POSTPROCESS_TARGETS_PATH", "/bazarr-postprocess/targets.json")
    static_dir = os.getenv("STATIC_DIR", "/app/static")
    backup_check_seconds = int(os.getenv("BACKUP_CHECK_SECONDS", "21600"))
    configure_logging(log_dir)
    if not Path(config_path).exists():
        save_app_config(config_path, normalize_app_config({}), postprocess_targets_path)
    settings = load_settings(config_path)
    if seed_app_config_from_settings(config_path, settings, postprocess_targets_path):
        settings = load_settings(config_path)
    purge_old_backups(state_dir)

    cache = JsonFileCache(os.getenv("TMDB_CACHE_PATH", f"{state_dir}/cache/tmdb_cache.json"))
    http = HTTPClient(timeout=int(os.getenv("HTTP_TIMEOUT_SECONDS", "20")))
    worker = QueueWorker(queue_dir=queue_dir, settings=settings, cache=cache, http=http)

    if args.once:
        worker.process_once()
        return 0

    threading.Thread(
        target=run_backup_scheduler,
        args=(state_dir, config_path, postprocess_targets_path, backup_check_seconds),
        daemon=True,
    ).start()

    if args.worker_only:
        worker.run_forever(args.sleep)
        return 0

    ctx = {
        "queue_dir": queue_dir,
        "settings": settings,
        "worker": worker,
        "http": http,
        "state_dir": state_dir,
        "config_path": config_path,
        "postprocess_targets_path": postprocess_targets_path,
        "static_dir": static_dir,
        "log_dir": log_dir,
    }
    if not args.no_worker:
        threading.Thread(target=worker.run_forever, args=(args.sleep,), daemon=True).start()
    start_web_server(ctx, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
