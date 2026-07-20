# Development

## Local Setup

Use [uv](https://docs.astral.sh/uv/) for local dependency management. The
checked-in lockfile selects Python 3.14 for parity with the Docker image; the
application supports Python 3.12 through 3.14.

```bash
uv sync --locked
```

`uv` downloads the requested Python version when it is not already installed.

## Run Tests

```bash
uv run --locked python -m unittest discover -s tests -t . -v
uv run --locked python -m compileall -q -f worker.py gst_worker
```

## Update the Upstream Translator

The direct dependency allows compatible 3.x releases while `uv.lock` pins the
exact version used by local development, CI, and Docker. To check for a new
release, update the lockfile, and run the verification suite:

```powershell
uv run python scripts/update_upstream.py
```

Dependabot runs the equivalent release check daily and opens a pull request
when a compatible `gemini-srt-translator` release is available. Pull requests
must pass the CI workflow before merging; the existing Docker workflow publishes
the updated image after the change reaches `main`.

## Run Locally

Create `.env`, then run:

```bash
python worker.py --host 127.0.0.1 --port 6789
```

The worker expects the media and Bazarr config paths from your environment to be
valid. For isolated UI work, use `--no-worker` so it does not consume queue
jobs:

```bash
python worker.py --no-worker --host 127.0.0.1 --port 6789
```

## Coding Notes

- Keep Bazarr integration in the post-processing script fast and side-effect
  small.
- Keep Gemini calls in the worker app (`gst_worker/translation.py`); do not
  install dependencies into the Bazarr image.
- Never log Gemini, TMDB, or Bazarr API keys.
- Preserve the no-overwrite rule for existing target subtitle files.
- Prefer focused unittest coverage around path handling, queue transitions,
  command construction, and Bazarr refresh behavior.

## Release Checklist

1. Update `CHANGELOG.md`.
2. Run the test commands above.
3. Build the image:

   ```bash
   docker compose build
   ```

4. Check the example config still renders:

   ```bash
   docker compose --env-file .env.example config
   ```

5. Tag the release.
6. Push `main` or a `v*.*.*` tag and verify the `Docker image` GitHub Actions
   workflow published the GHCR image.
