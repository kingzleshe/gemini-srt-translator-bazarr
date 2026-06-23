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
- `queue.py`: queue file naming, creation, skip checks, and snapshots;
- `translation.py`: `gst` command construction and subprocess environment;
- `tmdb.py`: TMDB lookup and translation description generation;
- `bazarr.py`: Bazarr API refresh, wanted-item lookup, and API-key parsing;
- `backups.py`: server-side backup listing and creation;
- `http.py`: small HTTP client and JSON file cache helpers.

The worker calls the `gst` CLI from `gemini-srt-translator`, writes the target
subtitle, and asks Bazarr to scan the affected series or movie.

### Web Console

`static/` contains a dependency-free HTML/CSS/JavaScript UI. It calls the local
worker API only; it does not talk directly to Bazarr, Gemini, or TMDB.

## Queue Layout

The queue is a set of JSON files in four directories:

```text
queue/
  pending/
  processing/
  done/
  failed/
```

A job file is moved between directories as state changes. A failed job may also
have a sibling `.error` file containing the exception text.

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
5. On success, the job moves to `done`.
6. The worker refreshes Bazarr with `scan-disk`; if item IDs are missing, it
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
