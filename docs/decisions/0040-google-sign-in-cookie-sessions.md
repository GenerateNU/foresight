# 0040. Google sign-in, with a signed session cookie

**Status:** Accepted · **Date:** 2026-10-31

## Context
Users exist ([0035](0035-users-keyed-on-google-id.md)) but nobody can sign in,
and the API can't tell who is calling. The frontend and the API may be on
different domains in production, and hosting isn't chosen yet. Anyone with a
Google account can sign up, so a new user must see nothing until they are linked
to a hotel.

## Decision
- **Google OAuth 2.0 / OpenID Connect, authorization-code flow, through
  Authlib.** The library does the state, nonce and ID-token checks (signature,
  issuer, audience, expiry); we hand-roll none of them. PKCE (S256) is on.
  The scopes are `openid email profile`.
- **The session is a signed cookie** (Starlette's `SessionMiddleware`, key
  `SESSION_SECRET`). It holds only the user's id. The flow's state and nonce
  live in the same cookie while a sign-in is under way. The cookie is
  HTTP-only, Secure by default, and expires: it is re-issued on every response,
  so a session ends `SESSION_MAX_AGE_SECONDS` (14 days) after the user's last
  request. A missing, expired or tampered cookie reads as an empty session and
  is a 401.
- **Sign-in creates or refreshes the user in one statement**
  (`INSERT … ON CONFLICT (google_id) DO UPDATE`), setting email, name and
  `last_signed_in_at` every time. Two sign-ins at once can't make two users.
  `create_user` keeps its conflict, which 0035 relies on.
- **The email must be verified.** Hotels are granted by email
  (`just link-user`), so an address Google hasn't verified can't become a user.
  That is a 403. Identity itself is still the Google id, never the email.
- **The Authlib client lives in `routes/auth.py`.** It reads and writes the HTTP
  session, and services don't know about HTTP ([0012](0012-layered-architecture.md)).
  `services/domain/user.py` gets plain values (`sign_in`) and
  `get_signed_in_user`.
- **Two domain errors:** `NotSignedInError` (401) and `ForbiddenError` (403),
  mapped like the others ([0014](0014-services-raise-domain-errors.md)). A failed
  callback (bad or missing state, Google refused, bad ID token) is a 400 from
  the routes layer, as JSON with the usual `{"detail"}`, not a redirect.
- **Where the browser goes is fixed:** `FRONTEND_URL`, with no `next`
  parameter, so sign-in can't be turned into an open redirect.
- **CORS** allows `FRONTEND_URL` only, with credentials, and the methods and
  header the API uses.
- **Cookie flags are settings.** `SESSION_COOKIE_SAMESITE` is `lax` unless the
  frontend and API are on different sites, when it must be `none` (and the
  cookie Secure; the settings reject `none` without it). `GOOGLE_REDIRECT_URI`
  is configured rather than derived, because behind a proxy the request looks
  like plain http and Google rejects a redirect URI that differs.

## Consequences
- **Sign-in exists; protection doesn't.** No existing route requires a session,
  so [0026](0026-no-authentication.md) still stands until the work that
  requires a login and limits each user to their hotels replaces it. Until then
  a signed-in user with no hotel gets `hotels: []` from `/auth/me` and nothing
  more.
- **Logout only deletes the browser's cookie.** There is no server-side session
  to revoke, so a copied cookie works until it expires. Changing
  `SESSION_SECRET` signs everyone out. A `sessions` table would give revocation
  and costs a migration and a query per request.
- **The cookie is signed, not encrypted.** Its contents are readable, which is
  why it holds nothing but an id.
- **`SameSite=None` means cross-site requests carry the cookie**, so a future
  state-changing route would need CSRF protection. Putting the frontend and API
  on subdomains of one domain avoids it and keeps `lax`.
- Without `SESSION_SECRET` the app still starts, signing with a throwaway key
  nothing outside the process can forge, and the sign-in routes answer 503.
- The `userinfo` claims are Google's, so a changed name or email arrives at the
  next sign-in, not before.
