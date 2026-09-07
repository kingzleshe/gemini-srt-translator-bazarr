# Architecture

## Components

### Bazarr Post-Processing Script

`bazarr-postprocess/gst_enqueue.sh` runs inside the Bazarr container after Bazarr
downloads or extracts a subtitle. The script is intentionally small:

- validate provider and source language;
- load source and target languages from `targets.json`;
- skip targets that already have output files;
- write one JSON job per missing target into the shared queue.

It does not call Gemini and should return quickly.

### Worker

`worker.py` is the runtime entrypoint. In normal mode it starts:

- a background worker loop that consumes one pending job at a time;
- a small stdlib HTTP server for the console and JSON API.

Domain code is split under `gst_worker/`:

- `config.py`: app settings, language normalization, and Bazarr language list
  loading;
- `subtitles.py`: subtitle path mapping and local source subtitle scanning;
- `queue.py`: queue admission, lifecycle, skip checks, and snapshots. `JobQueue`
  owns recovery, settling, claiming, deferred retries, quota pauses, and status
  persistence. Console retry and delete operations share its transition helpers;
- `queue_policy.py`: pure retry and daily quota lifecycle decisions. This is the
  policy seam; filesystem moves remain in `queue.py`.
- `console.py`: `ConsoleActions`, the small interface used by the HTTP adapter
  for queue actions. It keeps request routing separate from queue orchestration;
- `translation_attempt.py`: `TranslationAttempt`, the observation and execution
  seam for unfinished translation work, checkpoints, and publication;
- `translation.py`: translation execution and the `gst` work-file protocol,
  including checkpoint interpretation, partial-output cleanup, and publication;
- `tmdb.py`: TMDB lookup and translation description generation;
- `bazarr.py`: Bazarr API refresh, wanted-item lookup, and API-key parsing;
- `backups.py`: server-side backup listing and creation;
- `logs.py`: logging setup, UTC formatting, 5 MiB rotation (three backups),
  bounded event snapshots, and clearing the current log;
- `http.py`: small HTTP client and JSON file cache helpers.

The worker calls the `gst` CLI from `gemini-srt-translator`, writes the target
subtitle, and asks Bazarr to scan the affected series or movie.

`QueueWorker` binds `JobQueue.process_once` to the configured translation
workflow through an execution callback and exposes `ConsoleActions` to the HTTP
adapter. Queue lifecycle tests use the same
interface with a callback and a real temporary directory, without HTTP or TMDB
setup. Recovery is explicit at worker startup, so creating a queue handle does
not recover work that is still running.

Queue snapshots obtain translation progress through the `TranslationAttempt`
interface;
they do not interpret translator filenames or checkpoint fields. Execution and
observation share the translation module's work-file implementation. A visible
checkpoint does not by itself imply resumability: partial output must also exist.

`RuntimeContext` is the composition seam for the running process. It carries the
queue console actions, Bazarr integration, backup maintenance, and HTTP transport
adapters alongside the worker's shared settings and state paths. The legacy
module-level functions remain compatibility entry points for direct callers and
older tests; new runtime composition should depend on the typed context fields.

The direct seam tests in `tests/test_architecture_modules.py` verify policy,
console actions, and translation-attempt delegation independently of the HTTP
server and the complete queue lifecycle tests.

Bazarr remains a separate, dependency-free file producer. Its embedded Python
payload is tested against the worker's admission and retry protocol; it does not
need network access to enqueue work.

### Web Console

`static/` contains a dependency-free HTML/CSS/JavaScript UI. It calls the local
worker API only; it does not talk directly to Bazarr, Gemini, or TMDB.

## Queue Layout

The queue is a set of JSON files in five directories:

```text
queue/
  pending/
  processing/
  deferred/
  done/
  failed/
```

A job file is moved between directories as state changes. Deferred and failed
jobs may also have a sibling `.error` file containing the exception text.
Deferred jobs record `retry_at`; a persisted `provider-pause.json` circuit
breaker prevents other work from consuming requests after daily quota exhaustion.

## Job Shape

```json
{
  "job_id": "sha1",
  "video_path": "/media/Show/Episode.mkv",
  "subtitle_path": "/media/Show/Episode.en.srt",
  "output_path": "/media/Show/Episode.zh.srt",
  "source_code": "ja",
  "source_language": "Japanese",
  "target_code": "zh",
  "target_language": "Simplified Chinese",
  "provider": "embeddedsubtitles",
  "media_type": "series",
  "series_id": "144",
  "media_id": "14672"
}
```

## Translation Flow

1. The worker picks the oldest pending job.
2. Existing output files are skipped to avoid overwriting subtitles.
3. TMDB context is built when `TMDB_API_KEY` is available.
4. The worker executes `gst translate`.
5. A Gemini `503` moves the job to `deferred` for 2, 5, then 15 minutes. After
   three delayed retries it moves to `failed`.
6. A daily quota `429` moves the job and waiting jobs to `failed`, cancels
   automatic retries, and blocks admission and manual retries for 24 hours.
   Content line-count errors alone retry with the smaller batch size.
7. On success, the job moves to `done`.
8. The worker refreshes Bazarr with `scan-disk`; if item IDs are missing, it
   falls back to full subtitle scan tasks.

## Path Model

Bazarr, the post-processing script, and the worker must agree on media paths.
The recommended Docker model is:

```yaml
volumes:
  - /host/media:/media
```

If Bazarr sees a subtitle as `/media/Movie/Movie.en.srt`, this worker must be
able to read and write that exact path inside its container.
