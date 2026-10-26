# 0035. Users are identified by their Google account id

**Status:** Accepted · **Date:** 2026-10-25

## Context
The API has no idea who is calling it, so it can't limit what someone sees or
record who made a decision. Sign-in will be Google only.

## Decision
- A user is one Google account, identified by Google's account id (the `sub`
  claim), stored as `users.google_id` and unique. Never by email: an address
  can change.
- `users.email` is not unique. An address can pass to another person before
  its previous owner signs in again and the row is updated, and a unique
  constraint would then fail that person's sign-in. Anything that finds a user
  by email (`just link-user`) ignores case and refuses to choose when more than
  one user matches, because picking one would grant a hotel's access to the
  wrong person.
- `user_hotels` links users to hotels. Its primary key is (user_id, hotel_id),
  so a pair can be linked only once, and it records when. Deleting a user or a
  hotel removes its links. There are no roles yet.
- A user with no hotel is valid: they have signed up and aren't linked yet.
- There are no passwords.

## Consequences
- Linking is idempotent: linking the same pair again changes nothing.
- A hotel can have several users and a user can belong to several hotels.
  Adding roles later is a column on `user_hotels`.
- This is storage only. Signing in, and checking who is calling (which
  replaces [0026](0026-no-authentication.md)), come later.
