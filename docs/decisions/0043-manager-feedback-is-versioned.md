# 0043. Manager feedback is added to, never changed

**Status:** Accepted · **Date:** 2026-10-31

## Context
The manager knows things the data doesn't: a wedding block, a venue that sold
out, a rate they'd never charge. They need to tell us before a night and after
it, and to change their mind. Training on feedback (#105) needs to know what
was said and when, and to tell what was said before a night from what was said
after it.

## Decision
- Feedback lives in `feedback`, one row per version, per room type and night
  (`hotel_id`, `room_type_id`, `stay_date`, `version`). Changing feedback adds
  the next version. Nothing is updated or deleted; the highest version is
  current and every earlier one keeps its `created_at`. A unique constraint on
  those four columns stops two simultaneous edits becoming the same version.
- `verdict` is required: `TOO_HIGH`, `TOO_LOW` or `ABOUT_RIGHT`. `rate`, the
  rate the manager would charge, is optional and must be above 0, checked by
  the database as well as the request.
- The reason is given two ways, both optional: `reason_tags`, chosen from a
  fixed list (`GROUP_OR_WEDDING_BLOCK`, `VENUE_SOLD_OUT`,
  `COMPETITOR_PRICING`, `LOCAL_KNOWLEDGE`, `OTHER`), and free `reason_text`.
  Tags are easy to count and to train on; the text keeps what no tag says.
- `timing` is `BEFORE` or `AFTER` the night. The server sets it from the stay
  date: a night before today is over, so `AFTER`; today and later are still
  ahead, so `BEFORE`. "Today" is today in the hotel's timezone
  ([0023](0023-stay-nights-are-local-dates.md)). The client can't send it. It
  is stored, so a version keeps the timing it was given with as time passes.
- `snapshot_id` is the recommendation snapshot the manager saw, from `GET
  /hotels/{id}/recommendations`
  ([0038](0038-recommendations-reused-while-inputs-hold.md)). It is null for a
  past night that was never saved. Deleting the snapshot clears the link and
  keeps the feedback.
- `user_id` is who gave it. It is null for now and filled once sign-in is
  required on every route. Deleting the user clears it.
- Tags are stored as `FeedbackReasonTag` names in a `VARCHAR[]` and checked by
  the request schema, not by the database, so adding a tag needs no migration
  (the convention in `database/enums.py`). A tag sent twice is kept once.
- `POST /hotels/{id}/feedback` takes the room type and night in the body and
  returns 201 with the version saved. `GET /hotels/{id}/feedback?start=&end=`
  (at most 366 nights) returns each night's current version, or every version
  with `include_history=true`. A snapshot must be the hotel's, for the same room
  type and night (404 if it isn't the hotel's, 422 if it is for another night);
  a room type must be the hotel's (404). Two edits saved at the same moment
  give the second a 409 asking it to be sent again.

## Consequences
- The current feedback for a night is the row with its highest version. The
  list endpoint has to pick it, and can also return the history.
- A hotel's `room_type_id` isn't checked against `hotel_id` by the database;
  the service must check the room type belongs to the hotel.
- Tags can't be checked by the database, so a bad one written outside the API
  would only show up when read.
- History grows by one row per edit; feedback is small, so we don't prune.
