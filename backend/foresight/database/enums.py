"""Enumerations stored in database columns.

They live in the database layer because the models depend on them; every
other layer imports them from here. Columns store the member *name*
(`ACTIVE`) as a VARCHAR, so adding a member needs no migration.
"""

from enum import StrEnum


class Source(StrEnum):
    PREDICTHQ = "predicthq"


class EventStatus(StrEnum):
    ACTIVE = "active"
    PROVISIONAL = "provisional"  # predicted upstream, not yet confirmed
    CANCELLED = "cancelled"
    DELETED = "deleted"  # withdrawn upstream


class DatePrecision(StrEnum):
    """How precisely the source pinned the date.

    Anything coarser than DAY is unusable for per-night pricing but still worth
    keeping as early signal, so it is recorded rather than rounded away.
    """

    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"


class EventCategory(StrEnum):
    """PredictHQ's taxonomy, adopted project-wide.

    Text sources classify into these buckets instead of inventing a second
    vocabulary.
    """

    ACADEMIC = "academic"
    AIRPORT_DELAYS = "airport-delays"
    COMMUNITY = "community"
    CONCERTS = "concerts"
    CONFERENCES = "conferences"
    DAYLIGHT_SAVINGS = "daylight-savings"
    DISASTERS = "disasters"
    EXPOS = "expos"
    FESTIVALS = "festivals"
    HEALTH_WARNINGS = "health-warnings"
    OBSERVANCES = "observances"
    PERFORMING_ARTS = "performing-arts"
    POLITICS = "politics"
    PUBLIC_HOLIDAYS = "public-holidays"
    SCHOOL_HOLIDAYS = "school-holidays"
    SEVERE_WEATHER = "severe-weather"
    SPORTS = "sports"
    TERROR = "terror"
    UNKNOWN = "unknown"


class JobKind(StrEnum):
    """What a background job does. Each has one handler in `services/job.py`."""

    WEATHER = "weather"  # Open-Meteo forecast and recorded weather
    EVENTS = "events"  # PredictHQ events
    PERFORMANCE = "performance"  # the hotel's own nightly CSV exports
    TRAIN = "train"  # a new pricing model version


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    STOPPED = "stopped"  # a source's quota or rate limit; resume from `resume_from`
    FAILED = "failed"  # any other error; `resume_from` says where to pick up


class FeedbackVerdict(StrEnum):
    """What the manager thinks of the recommended rate for a night."""

    TOO_HIGH = "too_high"
    TOO_LOW = "too_low"
    ABOUT_RIGHT = "about_right"


class FeedbackTiming(StrEnum):
    """Whether feedback came before or after the night it is about.

    Set by the server from the stay date, never sent by the client. Training
    uses what was said before a night (a prediction) and after it (a
    judgement with the result known) separately.
    """

    BEFORE = "before"
    AFTER = "after"


class FeedbackReasonTag(StrEnum):
    """Why a manager disagrees with the rate, picked from a fixed list.

    Several can apply to one piece of feedback. They sit beside the free-text
    reason, which captures what no tag does.
    """

    GROUP_OR_WEDDING_BLOCK = "group_or_wedding_block"
    VENUE_SOLD_OUT = "venue_sold_out"
    COMPETITOR_PRICING = "competitor_pricing"
    LOCAL_KNOWLEDGE = "local_knowledge"
    OTHER = "other"
