# Project Collaboration Rules

## Runtime Environment

- The service runs in Docker on `192.168.1.1`, with container name `gemini-srt-translator-bazarr` and web port `6789`.
- SSH command: `ssh root@192.168.1.1`. Run SSH connections to the device outside the sandbox, subject to the current tool permission settings.
- Service data directory on the host: `/opt/docker/gemini-srt-translator-bazarr`.
- Queue directory on the host: `/opt/docker/bazarr/postprocess/queue`, mapped to `/queue` in the container.
- Bazarr enqueue script: `/opt/docker/bazarr/postprocess/gst_enqueue.sh`.

## Build and Deployment

- Images are built through GitHub. The default scope is to modify repository code, run relevant tests, and report results; do not build images locally or on the remote device.
- Use read-only SSH checks when the live service state is needed. A code change request does not authorize deployment. Modify container files, replace remote scripts, or restart or recreate containers only when the user explicitly requests an update to the running service.
- Deploy using images built through GitHub. If the user explicitly requests a temporary direct container modification, back up the affected files first and explain that a normal restart preserves the changes, while recreating the container from an image overwrites changes made inside the container.
- Clearly distinguish repository code changes, completed GitHub image builds, and running container updates in reports. Claim only states that have been verified.

## Development Commands

Dependencies are managed with `uv` (`uv sync --locked`); tests use stdlib `unittest`, not pytest. CI (`.github/workflows/ci.yml`) runs:

```bash
uv run --locked python -m unittest discover -s tests -t . -v
uv run --locked python -m compileall -q -f worker.py gst_worker
uv run --locked gst --help
```

Run one module or test by dotted name:

```bash
uv run --locked python -m unittest tests.test_worker_queue
uv run --locked python -m unittest tests.test_worker_queue.TestWorkerQueueTests.test_enqueue_translation_jobs_for_enabled_targets
```

Local console preview on Windows: `scripts/start-local.ps1 [-Demo] [-NoWorker]` runs against an isolated `local-state/` directory instead of the Docker `/state` and `/queue` mounts. `-NoWorker` keeps the process from consuming queue jobs.

To bump the upstream `gemini-srt-translator` pin: `uv run python scripts/update_upstream.py`.

## Architecture

Read `docs/ARCHITECTURE.md` before changing queue, translation, or Bazarr behavior; it is the source of truth for module responsibilities, queue layout, and job shape. Domain vocabulary (translation job, translation attempt, checkpoint, daily quota pause, queue lifecycle) is defined in `CONTEXT.md`; use those terms in code and reports. HTTP endpoints are in `docs/API.md`, settings in `docs/CONFIGURATION.md`.

The end-to-end flow spans three independent pieces:

1. `bazarr-postprocess/gst_enqueue.sh` runs inside the Bazarr container, writes one queue JSON per missing target, and returns fast. It stays dependency-free and network-free; its embedded Python payload is tested against the worker's admission and retry protocol, so queue format changes must update both sides.
2. `worker.py` + `gst_worker/` consume the queue one job at a time, call the `gst` CLI, write the target `.srt` beside the media, and ask Bazarr to rescan.
3. `static/` is a dependency-free web console that talks only to the worker's own API.

Seams to respect when adding code:

- `RuntimeContext` (`gst_worker/runtime.py`) is the composition seam for the running process. New runtime wiring depends on its typed fields; the legacy module-level functions are compatibility entry points for older callers and tests.
- `queue_policy.py` holds pure retry/quota decisions; filesystem moves stay in `queue.py` (`JobQueue`). The HTTP layer reaches the queue only through `ConsoleActions`.
- Queue snapshots read translation progress through `TranslationAttempt`; translator work-file and checkpoint details stay in `translation.py`. A checkpoint alone does not imply resumability: partial output must also exist.
- Queue recovery runs explicitly at worker startup; creating a `JobQueue` handle must not recover in-flight work.

Invariants:

- An existing target subtitle is never overwritten.
- Gemini, TMDB, and Bazarr API keys are never logged or returned unmasked.
- Bazarr and the worker must see identical media paths (`/media/...`).
