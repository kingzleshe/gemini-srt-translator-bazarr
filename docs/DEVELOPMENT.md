# Development

## Local Setup

Use Python 3.12 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run Tests

```bash
python -m unittest discover -s tests -t . -v
python -m py_compile worker.py gst_worker/*.py
```

From the parent workspace on Windows:

```powershell
py -3 -m unittest discover -s .\gemini-srt-translator-bazarr\tests -t .\gemini-srt-translator-bazarr -v
$files = @('.\gemini-srt-translator-bazarr\worker.py') + (Get-ChildItem .\gemini-srt-translator-bazarr\gst_worker -Filter *.py | ForEach-Object { $_.FullName })
py -3 -m py_compile @files
```

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
