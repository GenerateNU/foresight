from enum import StrEnum


class Source(StrEnum):
    """Where an event came from."""

    PREDICTHQ = "predicthq"


class EventStatus(StrEnum):
    """Whether an event is still on.

    PROVISIONAL is predicted upstream but not yet confirmed; DELETED was
    withdrawn upstream.
    """

    ACTIVE = "active"
    PROVISIONAL = "provisional"
    CANCELLED = "cancelled"
    DELETED = "deleted"


class DatePrecision(StrEnum):
    """How precisely the source pinned an event's date.

    Anything coarser than DAY can't price a night, but is kept as an early
    signal rather than rounded away.
    """

    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"


class EventCategory(StrEnum):
    """PredictHQ's event categories, used for every source."""

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
    """What a background job does; each has a handler in `services/handlers.py`.

    WEATHER, ACTUAL_FORECAST and PRICE are no longer queued; they stay so old
    job rows still load.
    """

    WEATHER = "weather"
    EVENTS = "events"
    ACTUAL_FORECAST = "actual_forecast"
    RESERVATIONS = "reservations"
    CANCELLATIONS = "cancellations"
    TRAIN = "train"
    PRICE = "price"
    TUNE = "tune"


class JobStatus(StrEnum):
    """Where a job is in its life.

    STOPPED means a source's quota or rate limit ended it; FAILED, any other
    error. Both keep `resume_from`. CANCELLED was taken out of the queue before
    it ran.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    STOPPED = "stopped"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FeedbackReasonTag(StrEnum):
    """Why the manager changed a rate, from a fixed list.

    ONE_OFF marks something that won't happen again (a buyout, a private
    event), so the model learns nothing from that night.
    """

    GROUP_OR_WEDDING_BLOCK = "group_or_wedding_block"
    VENUE_SOLD_OUT = "venue_sold_out"
    COMPETITOR_PRICING = "competitor_pricing"
    LOCAL_KNOWLEDGE = "local_knowledge"
    GUT_FEEL = "gut_feel"
    ONE_OFF = "one_off"
    OTHER = "other"
