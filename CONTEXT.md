# Subtitle Translation

Translate source subtitles into missing target languages for Bazarr-managed media.

## Language

**Translation job**:
A request to translate one source subtitle into one target language for a media item.
_Avoid_: Batch (a batch is only part of a translation attempt).

**Job queue**:
The collection of translation jobs awaiting execution, running, deferred for a
later attempt, completed, or failed.

**Translation work files**:
The unfinished subtitle output and recorded translation progress associated with
a translation attempt. They are distinct from a completed target subtitle.

**Checkpoint**:
A recorded position in subtitle translation progress. A checkpoint alone does
not establish that unfinished subtitle output is available for resuming.

**Daily quota pause**:
The period after daily Gemini quota exhaustion during which new translation jobs
and retries are blocked; waiting jobs are failed rather than automatically resumed.
