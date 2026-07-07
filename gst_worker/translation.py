from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from .subtitles import target_output_path


GST_OUTPUT_TAIL_LENGTH = 1000


def build_gst_command(
    input_srt: str,
    output_srt: str,
    description: str,
    target_language: str | None = None,
    gst_settings: dict[str, Any] | None = None,
) -> list[str]:
    settings = gst_settings or {}
    model = str(settings.get("gst_model") or os.getenv("GST_MODEL", "gemini-flash-latest"))
    batch_size = str(settings.get("gst_batch_size") or os.getenv("GST_BATCH_SIZE", "1000"))
    command = [
        "gst",
        "translate",
        "-i",
        input_srt,
        "-l",
        target_language or os.getenv("GST_TARGET_LANGUAGE", "Simplified Chinese"),
        "-o",
        output_srt,
        "--model",
        model,
        "--batch-size",
        batch_size,
    ]
    for option, key in (
        ("--temperature", "gst_temperature"),
        ("--top-p", "gst_top_p"),
        ("--top-k", "gst_top_k"),
    ):
        value = str(settings.get(key) or "").strip()
        if value:
            command.extend([option, value])

    thinking_budget = str(settings.get("gst_thinking_budget") or "").strip()
    thinking_level = str(settings.get("gst_thinking_level") or "").strip()
    if thinking_budget and thinking_level:
        if "2.5" in model:
            thinking_level = ""
        else:
            thinking_budget = ""
    if thinking_budget:
        command.extend(["--thinking-budget", thinking_budget])
    if thinking_level:
        command.extend(["--thinking-level", thinking_level])
    for option, key, default in (
        ("--skip-upgrade", "gst_skip_upgrade", True),
        ("--quiet", "gst_quiet", True),
        ("--paid-quota", "gst_paid_quota", False),
        ("--progress-log", "gst_progress_log", False),
        ("--thoughts-log", "gst_thoughts_log", False),
        ("--token-report", "gst_token_report", False),
        ("--no-streaming", "gst_no_streaming", False),
        ("--no-thinking", "gst_no_thinking", False),
        ("--no-context", "gst_no_context", False),
    ):
        if bool(settings.get(key, default)):
            command.append(option)
    if description:
        command.extend(["--description", description])
    return command


def _result_output_tail(result: subprocess.CompletedProcess[str]) -> str:
    stdout = str(getattr(result, "stdout", "") or "")
    stderr = str(getattr(result, "stderr", "") or "")
    parts = []
    if stdout:
        parts.append(f"stdout: {stdout[-GST_OUTPUT_TAIL_LENGTH:]}")
    if stderr:
        parts.append(f"stderr: {stderr[-GST_OUTPUT_TAIL_LENGTH:]}")
    return "\n".join(parts) or "<no output>"


def _format_gst_failure(result: subprocess.CompletedProcess[str]) -> str:
    return f"gst failed with exit {result.returncode}: {_result_output_tail(result)}"


def _int_setting(settings: dict[str, Any], key: str, env_key: str, default: int) -> int:
    raw_value = settings.get(key)
    if raw_value in (None, ""):
        raw_value = os.getenv(env_key, str(default))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _progress_line(progress_path: Path) -> int | None:
    if not progress_path.exists():
        return None
    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
        line = data.get("line")
        return int(line) if line is not None else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _remove_untrusted_retry_state(temp_output: Path, progress_path: Path) -> None:
    line = _progress_line(progress_path)
    if line is not None and line > 1:
        return
    for path in (temp_output, progress_path):
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            logging.warning("Failed to remove stale gst retry state %s: %s", path, exc)


def translation_environment(settings: dict[str, Any], base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env if base_env is not None else os.environ)
    gemini_api_key = str(settings.get("gemini_api_key") or "")
    gemini_api_key2 = str(settings.get("gemini_api_key2") or "")
    if gemini_api_key:
        env["GEMINI_API_KEY"] = gemini_api_key
        env["GEMINI_API_KEY1"] = gemini_api_key
    if gemini_api_key2:
        env["GEMINI_API_KEY2"] = gemini_api_key2
    return env


def run_translation(job: dict[str, Any], description: str, settings: dict[str, Any]) -> str:
    input_srt = str(job["subtitle_path"])
    output_srt = str(job.get("output_path") or target_output_path(input_srt, str(job.get("target_code") or "zh")))
    output_path = Path(output_srt)
    if output_path.exists():
        return "skipped-existing-output"

    temp_output = output_path.with_name(f"{output_path.stem}.partial.srt")
    progress_path = Path(input_srt).with_suffix(".progress")
    can_resume = temp_output.exists() and temp_output.stat().st_size > 0 and progress_path.exists()
    if temp_output.exists() and not can_resume:
        temp_output.unlink()

    command = build_gst_command(
        input_srt,
        str(temp_output),
        description,
        target_language=str(job.get("target_language") or os.getenv("GST_TARGET_LANGUAGE", "Simplified Chinese")),
        gst_settings=settings,
    )
    logging.info("Running translation: %s -> %s", input_srt, output_srt)
    result = subprocess.run(command, text=True, capture_output=True, check=False, env=translation_environment(settings))
    primary_batch_size = _int_setting(settings, "gst_batch_size", "GST_BATCH_SIZE", 1000)
    retry_batch_size = _int_setting(settings, "gst_retry_batch_size", "GST_RETRY_BATCH_SIZE", 500)
    if result.returncode == 130 and retry_batch_size > 0 and retry_batch_size < primary_batch_size:
        logging.warning(
            "gst exited 130 with batch size %s; retrying with batch size %s. %s",
            primary_batch_size,
            retry_batch_size,
            _result_output_tail(result),
        )
        _remove_untrusted_retry_state(temp_output, progress_path)
        retry_settings = dict(settings)
        retry_settings["gst_batch_size"] = retry_batch_size
        retry_command = build_gst_command(
            input_srt,
            str(temp_output),
            description,
            target_language=str(job.get("target_language") or os.getenv("GST_TARGET_LANGUAGE", "Simplified Chinese")),
            gst_settings=retry_settings,
        )
        result = subprocess.run(
            retry_command,
            text=True,
            capture_output=True,
            check=False,
            env=translation_environment(settings),
        )
    if result.returncode != 0:
        raise RuntimeError(_format_gst_failure(result))
    if not temp_output.exists() or temp_output.stat().st_size == 0:
        raise RuntimeError(f"gst did not create a non-empty output file: {temp_output}")

    if output_path.exists():
        temp_output.unlink()
        return "skipped-existing-output"

    temp_output.replace(output_path)
    return "translated"
