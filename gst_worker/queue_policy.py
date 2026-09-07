"""Pure queue lifecycle decisions."""
from dataclasses import dataclass

PROVIDER_RETRY_DELAYS = (120, 300, 900)
DAILY_QUOTA_PAUSE_SECONDS = 86_400

@dataclass(frozen=True)
class RetryDecision:
    state: str
    retry_at: float | None = None
    retry_count: int | None = None

def provider_retry_decision(retry_count: int, now: float) -> RetryDecision:
    next_count = retry_count + 1
    if next_count <= len(PROVIDER_RETRY_DELAYS):
        return RetryDecision("deferred", now + PROVIDER_RETRY_DELAYS[next_count - 1], next_count)
    return RetryDecision("failed")

def daily_quota_retry_at(now: float) -> float:
    return now + DAILY_QUOTA_PAUSE_SECONDS
