# Bazarr Integration

## Goal

Bazarr should keep doing what it is good at: tracking wanted subtitles,
extracting embedded source subtitles, and indexing local subtitles. This worker
only adds the translation step.

## Required Bazarr Settings

Enable the Embedded Subtitles provider so Bazarr can extract `.srt` files from
video containers for the source languages you configure in the worker console.

Then enable:

```text
Settings -> Subtitles -> Use Custom Post-Processing
```

Use this command:

```bash
/config/postprocess/gst_enqueue.sh "{{episode}}" "{{subtitles}}" "{{subtitles_language_code2}}" "{{provider}}" "{{series_id}}" "{{episode_id}}" 2>&1
```

Bazarr's post-processing command field requires careful quoting. Keep each
placeholder in double quotes, and keep `2>&1` at the end so output is captured
in Bazarr logs.

## Docker Mounts

The Bazarr container needs the enqueue script inside its `/config` tree:

```yaml
volumes:
  - /opt/docker/bazarr/config:/config
  - /opt/docker/bazarr/postprocess:/config/postprocess
```

The worker needs the same post-processing directory and queue:

```yaml
volumes:
  - /opt/docker/bazarr/postprocess:/bazarr-postprocess
  - /opt/docker/bazarr/postprocess/queue:/state/queue
```

## What Gets Queued

The script queues jobs only when all checks pass:

- `provider` is `embeddedsubtitles`;
- subtitle language is one of the configured source languages;
- at least one enabled target output does not exist;
- the same job is not already pending or processing.

This means normal downloaded subtitles from other providers are ignored by the
automatic post-processing hook. Only configured source languages extracted by
Bazarr are used as translation sources.

## Manual Wanted Workflow

When you click Search All in Bazarr, Bazarr may extract a source subtitle from
the video. If that extraction triggers post-processing, the script writes a job
immediately.

For already-existing source subtitle files, use the worker console:

```text
Wanted -> Load Wanted -> Enqueue
Scan -> Load Scan -> Enqueue All
```

This avoids running a timer that constantly walks the whole media library.

## Refresh Behavior

After translation, the worker asks Bazarr to rescan the item:

```text
PATCH /api/series?seriesid=<series_id>&action=scan-disk
PATCH /api/movies?radarrid=<radarr_id>&action=scan-disk
```

If an item ID is missing, it falls back to Bazarr's full subtitle scan task for
series or movies.
