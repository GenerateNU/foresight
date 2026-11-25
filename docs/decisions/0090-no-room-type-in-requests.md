# 0090. Requests no longer name a room type

**Status:** Accepted · **Date:** 2026-11-25 · Amends [0079](0079-one-main-room-type-double-room-only.md)

## Context
0079 made each model price one room type. Three request parameters still named
one: `room_type_id` on `GET /hotels/{id}/recommendations` (any value but the
priced room type was a 422), the required `room_type_id` in the
`POST /hotels/{id}/feedback` body (the `snapshot_id` sent with it already
fixes the room type), and the `room_type_id` filter on
`GET /hotels/{id}/feedback`. Nothing sent them except to repeat the only valid
value.

## Decision
- Recommendations always price the active model's room type.
- Feedback takes its room type from the snapshot it is about. The request body
  has no `room_type_id`; sending one is a 422, as for any unknown field.
- The feedback list has no room-type filter.
- Responses keep `room_type` and `room_type_id`, so a screen can name the room.
- Feedback rows keep their `room_type_id` column; no schema change.

## Consequences
- A client has one less value to keep in step with the model.
- Pricing a second room type later means bringing a parameter back.
