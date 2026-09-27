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
The period after every configured model has exhausted its daily Gemini quota
during which new translation jobs and retries are blocked; waiting jobs are
failed rather than automatically resumed. Exhausting only one model's quota
pauses that model alone.

**Fallback model**:
An optional second Gemini model that continues a translation job from its
checkpoint when the primary model stays unavailable through every delayed retry
or has exhausted its own daily quota.

**Queue lifecycle**:
The rules that move a translation job through the job queue, including settling,
recovery, retries, quota pauses, and terminal outcomes.

**Translation attempt**:
One execution of translation work, including its unfinished work files,
checkpoint, partial output, and publication of a completed target subtitle.
