# Audiobooks Path 2 — Sonos Cloud Control API (per-book selection)

## Why this is needed

The local bridge (`node-sonos-http-api`) only sees the legacy **`FV:2`** favorites
container. We confirmed (browsing all three speakers' ContentDirectory directly)
that the **new Sonos app saves audiobook favorites to a cloud store that does NOT
sync down to `FV:2`** — so per-book audiobook favorites are invisible to anything
local. `Audible.com` (a service *container*, Audible service id `61191`) is the
only Audible item in `FV:2`; that's what **Path 1 / "continue my book"** plays to
resume the active book (see `docs/audible.md`).

To select a **specific** book by name ("audible warriors book three"), we have to
use the **Sonos Cloud Control API**, whose `/households/{id}/favorites` endpoint
returns *all* favorites, including the cloud audiobook ones.

Trade-offs (already accepted): needs internet, a Sonos developer app, OAuth2
tokens stored on the box, and a token-refresh loop. It's the only path to name
selection.

> **Scope caveat (re-verified 2026-07-18).** This path plays a book **only if it's
> been saved as a Sonos favorite**, and it gives **no true chapter selection**
> (only `skipToNextTrack` through chapters). It does **not** browse the Audible
> library. So it delivers "pick from a **parent-curated, favorited** shelf by
> name" — not "any book + any chapter." For the full-library + arbitrary-chapter
> ideal, see **Path C** in `docs/audible.md` (experimental; hinges on an
> unidentified URI constant). The favorites *do* have to be created in the Sonos
> app first; the Cloud API reads them, it doesn't create them.

---

## What YOU do (one-time, in a browser) — then hand me the result

### Step 1 — Create a Sonos developer integration
1. Go to **https://developer.sonos.com/** and sign in with your normal Sonos
   account. Open the **Control** integrations area ("Integrations" → create new
   **Control Integration**).
2. Give it a name (e.g. "Jetson Jukebox").
3. It generates a **Key (Client ID)** and **Secret (Client Secret)** — you'll give
   me both.
4. Set a **Redirect URI**. Sonos requires HTTPS. Use exactly:
   **`https://jetson-orin-nano.local/sonos/callback`**
   (You don't need a server there — see Step 3 for how we capture the code from
   the address bar. If the portal rejects `.local`, use
   `https://localhost/sonos/callback` instead and tell me which you used — it must
   match byte-for-byte in Step 2/4.)

### Step 2 — Authorize it once (mint the tokens)
Open this URL in a browser (I'll generate the exact one for you once I have your
Client ID; the shape is):

```
https://api.sonos.com/login/v3/oauth?client_id=YOUR_CLIENT_ID
  &response_type=code
  &state=jukebox
  &scope=playback-control-all
  &redirect_uri=https%3A%2F%2Fjetson-orin-nano.local%2Fsonos%2Fcallback
```

- Sign in / approve access to your Sonos household.
- The browser redirects to your Redirect URI with **`?code=...&state=jukebox`** in
  the address bar. The page itself will fail to load (nothing is hosted there) —
  **that's fine**. Copy the **`code`** value out of the address bar.
- The code is single-use and expires in ~30 seconds, so exchange it promptly
  (Step 4 / hand it to me right away).

### Step 3 — Give me three things
- **Client ID**
- **Client Secret**
- the **`code`** from the redirect (fresh — within ~30s)

(Or, if you'd rather not paste the code in chat: I'll put a ready-made helper on
the box — `setup/sonos_oauth.py` — that takes the code and does the exchange
locally so the tokens never transit the chat. Your call.)

### Step 4 — (what happens with the code, for reference)
I exchange the code for tokens:

```
POST https://api.sonos.com/login/v3/oauth/access
  Authorization: Basic base64(CLIENT_ID:CLIENT_SECRET)
  Content-Type: application/x-www-form-urlencoded
  grant_type=authorization_code
  &code=THE_CODE
  &redirect_uri=https://jetson-orin-nano.local/sonos/callback
```

Response → `access_token` (expires in ~24 h), `refresh_token` (long-lived),
`expires_in`. We store these in **`config/sonos-cloud-tokens.json`** (gitignored;
already added). The box renews the access token via the refresh token:

```
POST https://api.sonos.com/login/v3/oauth/access
  Authorization: Basic base64(CLIENT_ID:CLIENT_SECRET)
  grant_type=refresh_token&refresh_token=THE_REFRESH_TOKEN
```

---

## What I build (on the box) once tokens exist

Endpoints (base `https://api.ws.sonos.com/control/api/v1`, `Authorization: Bearer
<access_token>`):

- `GET /households` → `householdId`
- `GET /households/{hh}/groups` → groups + players (we map room → `groupId`)
- `GET /households/{hh}/favorites` → **all favorites incl. audiobooks**
  (`{id, name, ...}`) — this is the list local FV:2 can't see
- `POST /groups/{groupId}/favorites` body `{"favoriteId": "<id>",
  "playOnCompletion": true}` → loads & plays a favorite
- playback: `POST /groups/{groupId}/playback/play | pause | skipToNextTrack`

Module plan: `src/sonos_cloud.py` — token load/refresh, `list_audiobooks()`,
`play_favorite(room, favorite_id)`. Then `audible_resolve.resolve_audiobook()`
gains a cloud source: fuzzy-match the spoken title against the cloud favorites and
play by `favoriteId`. Routing/UX stays identical — "audible <book>" just starts
working for real, and "continue my book" keeps using the local resume path.

Config (gitignored): `config/sonos-cloud.json` = `{clientId, clientSecret,
redirectUri, householdId}`; `config/sonos-cloud-tokens.json` = the tokens.

## Security notes
- Client secret + tokens live only in gitignored `config/sonos-cloud*.json`
  (never committed — same rule as the Spotify keys).
- Scope is `playback-control-all` (playback only; no account/billing access).
- Tokens can be revoked anytime from the Sonos developer portal.
