# 2026-07-21
- Migrated dependency management from `requirements.txt` and pip to
  `pyproject.toml`, uv, and a reproducible `uv.lock`.
- Upgraded gemini-srt-translator to 3.6.1.
- Added a manual upstream dependency update script.
- Added weekly Dependabot dependency update pull requests.
- Added CI checks for the locked environment, test suite, Python compilation,
  and the upstream `gst` CLI.

# 2026-07-01
- Upgraded gemini-srt-translator to 3.5.9 for improved upstream FFmpeg handling
  and correct interrupted-translation exit codes.

# 2026-06-24
- Upgraded gemini-srt-translator to 3.5.8 for upstream package upgrade fixes.

# 2026-06-23
- Added the Docker sidecar worker and Bazarr post-processing enqueue script.
- Added the web console for status, wanted items, local scans, queue, settings,
  logs, backups, and connection tests.
- Added multi-source and multi-target language support using Bazarr's language
  API.
- Added scheduled backups every 7 days with 30-day retention.
- Added secret masking and connection tests for Bazarr, Gemini, and TMDB.
- Added the Gemini model selector and gemini-srt-translator CLI settings.
- Added gemini-srt-translator 3.5.7 token report support.
- Added recommended translation tuning defaults and a configurable 10-minute
  queue settle window.
- Added optional TMDB translation context and Bazarr scan refreshes.
- Added the optional FFmpeg Docker build flag; FFmpeg is disabled by default
  because Bazarr performs subtitle extraction.
- Added project documentation, MIT license, contribution guide, and security
  notes.
- Split backend helpers into modules for config, subtitle paths, queue, Bazarr
  API, TMDB descriptions, translation execution, backups, and HTTP handling.
- Removed the unused Token Stats setting from the web console and translation
  command.
- Fixed the Docker web port mapping to consistently use `6789:6789`.
