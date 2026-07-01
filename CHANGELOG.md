# Changelog

All notable changes to this project will be documented in this file.

The format follows Keep a Changelog style, and this project uses semantic
versioning once tagged releases begin.

## Unreleased

### Added

- Docker sidecar worker for Bazarr and gemini-srt-translator.
- Bazarr post-processing enqueue script.
- Web console for status, wanted items, local scans, queue, settings, and logs.
- Multi-target-language queue support.
- Multi-source and multi-target language selection from Bazarr's language API.
- System backups page with server-side backup creation and listing.
- Automatic scheduled backups every 7 days with 30-day backup retention.
- API key masking and connection test buttons for Bazarr, Gemini, and TMDB.
- Gemini model dropdown and gemini-srt-translator CLI settings in the web console.
- Token report setting for gemini-srt-translator 3.5.7 `--token-report`.
- gemini-srt-translator 3.5.9 dependency update for upstream FFmpeg handling
  and interrupted-translation exit-code fixes.
- Recommended gemini-srt-translator tuning defaults for automated subtitle
  translation.
- Configurable 10-minute default queue settle window to avoid translating while
  Bazarr is still extracting target-language embedded subtitles.
- Logs page clear action and `/api/logs/clear` endpoint.
- Optional TMDB context for translation descriptions.
- Bazarr scan refresh after successful translation.
- Fixed Docker web port mapping to `6789:6789`.
- Removed the unused Token Stats setting from the web console and translation
  command.
- Split backend package modules for config, subtitle paths, queue, Bazarr API,
  TMDB descriptions, translation execution, backups, and HTTP helpers.
- Optional FFmpeg build flag; the default Docker image leaves FFmpeg out because
  Bazarr extracts subtitles.
- Open-source project documentation, MIT license, contribution guide, and
  security notes.
