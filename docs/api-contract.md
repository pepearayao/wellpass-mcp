# Wellpass API contract (reverse engineered)

Status (2026-10-04): studio search complete (no auth). Class search complete
and LIVE VERIFIED (session auth). Both shipped in the MCP.

## Two separate backends, two separate auth models

1. Studio finder — `gymfinder.int.api.egym.com` — NO auth (see below).
2. Class API — `qualitrain.netpulse.com` — SESSION auth (see "Classes").

Firebase note: the gym finder web app uses Firebase (project `prod-egym-id`)
for favourites only. The class API does NOT use Firebase; it uses Netpulse
session login. Do not build Firebase auth.

## Which studios have structured classes (measured)

The class API only covers Netpulse-NATIVE studios. Most studios use external
booking the app just links to (no structured data).
- Predictor: `GET /np/schedule/forClub/{clubUuid}` → `source == "NATIVE"` marks
  studios with queryable classes. Others error / return "Wrong club".
- Measured near Munich: ~2 of 15 nearest studios are NATIVE (both Fitness
  First). The gym-finder flags (`cbc.e`, `cbc.brc`, `studio_type`) do NOT
  predict this.
- Online/virtual classes (the user's home club) are always structured (575+).

Note: the studio search below needs NO auth.

## Studio search (gym finder) — NO AUTH

Base URL: `https://gymfinder.int.api.egym.com`

Search profile param `searchFilter` selects the region catalog:
- `wellpass` = DACH (Germany/Austria/Switzerland). Use this for Munich.
- `wellpass-all`, `wellpass-us`, `wellpass-fr-be`, `wellpass-dach-and-us`.

### Endpoints

1. List (compact, for the map):
   `GET /v1/gym/overview?searchFilter=wellpass&limit=20000&filter=<slug>&filter=<slug>`
   - Returns `{ "gyms": [ <compact gym> ] }`.
   - NO geo param. The frontend loads all, then filters by map bounds on the
     client. We compute distance in memory from each gym `lat`/`lng`.
   - `limit` caps the result. The frontend uses 20000 (all).

   - CONFIRMED: no server-side geo. `latitude`/`longitude`/`radius` are ignored
     even with `searchFilter`. A Munich point returned Kiel/Berlin/Mainz, all
     with distance -0.001. So geo MUST be computed in memory from `lat`/`lng`.
   - CONFIRMED: `filter=wellpass` is redundant. The `wellpass` profile already
     scopes to Wellpass gyms (count is 17895 with or without it).

2. Count:
   `GET /v1/gym/count?searchFilter=wellpass&filter=<slug>` → an integer.

3. Detail (full):
   `GET /v1/gym?slug=<gym-slug>` → `[ <full gym> ]` (array, one element).
   - Also `GET /v1/gym?...` is the full-schema list variant.

4. Filter vocabulary:
   `GET /v1/search-filter/wellpass` → the filter groups and slugs (localized
   text de/en/fr/nl). Groups (live counts): Activities (42), Services (40), Plus1 (button),
   EGYM Products (button), Wellpass (always-on button).

5. Activity taxonomy:
   `GET /v1/activities?locale=de_DE` → 10 categories → 42 activity types
   (e.g. `YOGA_PILATES_AND_MOBILITY` → `YOGA`, `PILATES`, ...). This is the
   enum behind the `activity-*` filter slugs.

### Filter semantics (confirmed by count probes)

- Filter by `filter=<slug>`, repeatable.
- Same facet = OR. (yoga 5556, swimming 1965, yoga+swimming 7401.)
- Across facets = AND. (yoga + service-sauna = 1342.)
- Slugs: `activity-yoga`, `activity-swimming`, `service-sauna`,
  `service-free-parking`, `wellpass-plus-one`, `egym-products`, ...

### Compact gym object (overview) — key map

- `id` gym uuid · `g` gymUUID · `egi` numeric gym id · `slug`
- `a` name · `bimg` image url · `slug`
- `lat` `lng` · `d` distance (=-1 when no search point) · `n` network (DACH)
- `st` studioType (WELLNESS/PILATES/...) · `sp` state code · `tz` timezone
- `ac` activities: `[{a: ACTIVITY_TYPE, c?: bool}]`
- `o` opening hours (compact ms) · `ov2` opening hours (structured) · `eo` exceptions
- `op` options/gym-info: e.g. `ACCESSIBLE_TO_PREGNANT_WOMEN`, `COURSES_IN_ENGLISH`
- `mt` membershipTypes: `UNLIMITED`, `PLUS_1`
- `cbc` classBookingConfig flags → marks gyms that support class booking.
  BRIDGE TO CLASSES. Decoded from the full detail object:
  - `e`   = `enabled` (CONFIRMED: a Munich yoga studio had enabled=True)
  - `brc` = `bookingRequiredForCheckin`
  - `cmac`= `createMemberAccountForCheckin`
  - `hap` = `hasAccessPass`
  - `cog` = `checkinOnlyGym`
  - `che` = `checkinHandledExternally`
  - `scrma`=`skipCheckinRequiredForMmsAccess`
  - `ace` = autoCheckinMode (likely)
  The full detail also has `externalBookingInfo`, which may name the external
  booking system a gym uses (null for the studios checked).
- `qtpone` plus-one · `us` wellpassUS · `ppp` profilePagePublic

### Full gym object (detail) extra keys

`address`, `description`, `email`, `phone`, `website`, `openingHours`,
`membershipTypes`, `options`, `externalBookingInfo`, `classBookingConfig`,
`gymImages`, `qualitrainOfferDescription`, `exceptionalOpeningHours`, `geofence`.

## Geocoding (city → lat/lon)

The MCP must turn a city name into lat/lon. Plan: OpenStreetMap Nominatim
(free, no key, self-hostable). Cache results. Low rate. Munich is the default.

## Classes / courses — reverse engineered + LIVE VERIFIED (NO MITM needed)

Source: static analysis of `com.qualitrain.fitness` 6.6.1 (jadx), confirmed by a
live login + class query on 2026-10-04. The app is a native Android app on the
**Netpulse** platform (`com.netpulse.mobile`).

Backend host for the `/np/` endpoints: **`https://qualitrain.netpulse.com`**
(BuildConfig `SERVER_URL_BASE`). NOTE: `mobile-api.int.api.egym.com` is a
DIFFERENT EGYM API; the Netpulse class/login endpoints are NOT there (they 403).

### Auth — session based (simple)

- Login: `POST /np/exerciser/login` — body is **form-urlencoded** (NOT JSON;
  JSON returns 401 "Required parameters are missing"):
  - `username` = email, `password` = password (minimal set works).
  - Content-Type: `application/x-www-form-urlencoded`.
  - Response: JSON profile (`uuid`, `homeClubUuid`, `homeClubName`, `chainUuid`,
    `membershipType`, ...) plus `Set-Cookie: JSESSIONID=...`. VERIFIED 200.
- Authorized requests send the session as a header: `Cookie: JSESSIONID=...`.
  (`HeaderSessionIdInterceptor` adds the stored cookie string. No HMAC, no
  Bearer, no OAuth client secret for the native login.)
- Global headers on every request (`HeadersInterceptor`):
  - `X-NP-User-Agent: <app user agent>`
  - `X-NP-API-Version: 1.5`
  - `X-NP-APP-Version: <app version>`
- There is also an OAuth2 login path (`/np/exerciser/oauth2/login`) used for
  SSO/relogin. The password login above is the primary path.

### Class search (the user's core ask)

`GET /np/company/{clubUuid}/classes` with query params:
- `startDateTime` = epoch milliseconds (date range start) — SERVER-SIDE
- `endDateTime` = epoch milliseconds (date range end) — SERVER-SIDE
- `type` = class category (optional, omitted if null) — SERVER-SIDE
- `exerciserUuid` = the user `uuid` from login

Returns `GroupXClass[]`. Each class has `brief`, `details`, `attendeeDetails`.
VERIFIED `brief` fields (live):
- `id` ("clubId:classId"), `name`, `startDateTime`, `endDateTime` (epoch ms)
- `instructor` `{id, fullName}` — the TEACHER
- `activity` `{id, description}` — the CATEGORY (e.g. "Body & Mind"). `type` is
  often null for in-person clubs; use `activity` for the category.
- `maxCapacity`, `totalBooked` — AVAILABILITY = maxCapacity - totalBooked
  (`availableSpots` is usually null; compute it).
- `free`, `reservable`, `cancelled`, `booked`, `childCare`
- `waitlistCapacity`, `waitlistBooked`, `waitlisted`
- `liveStreamClass` — ONLINE (true) vs in-person (false)
- `clubUuid`
`details` adds: `description`, `room`, `level`, `webCapacity`, `webBooked`,
`imageUrl`, `videoUrl`, `liveStreamLink`, booking window.

Filter mapping for `search_classes`:
- date/time -> `startDateTime`/`endDateTime` (server params)
- category -> `brief.activity.description` (client-side; server `type` varies)
- teacher -> `brief.instructor.fullName` (client-side)
- availability -> `maxCapacity - totalBooked > 0` (client-side)
- online/in-person -> `brief.liveStreamClass` (client-side)

Club resolution (VERIFIED):
- The gym finder `gymUUID` (`g`) IS the Netpulse `clubUuid` for native clubs.
  Fitness First München returned 56 real classes.
- Non-native clubs return HTTP 400 `{"message":"Wrong club"}`.
- Online/virtual classes: query the user's `homeClubUuid` (Qualitrain virtual
  club) — returned 575 online classes (`liveStreamClass=true`).

Other read endpoints (same auth):
- Class detail: `GET /np/company/{clubUuid}/class/{classId}`
- My schedule: `GET /np/exerciser/{uuid}/schedule?startDateTime=&endDateTime=`
- Schedule metadata: `GET /np/schedule/forClub/{clubUuid}` → `{source, type, url}`.
  `source` = NATIVE / PDF / URL / DATATRACK. Only NATIVE clubs have structured
  classes via the `/classes` endpoint above. PDF/URL clubs only link out.
- Allowed options: `GET /np/company/{clubUuid}/allowedOptions`.

### Booking (write) — built as two-step tools

- Book: `POST /np/company/{clubUuid}/class/{classId}/addExerciser`
  - Body: form-urlencoded `exerciserUuid=<uuid>` (+ optional `spot`).
  - `classId` = the full `brief.id` (e.g. "1248796313:2713172922"). The app
    books with this exact id (GroupXClient.addToClass).
- Cancel: `POST /np/company/{clubUuid}/class/{classId}/removeExerciser`
  (form `exerciserUuid`). Waitlist add/remove exist too (not built).
- POST bodies are form-urlencoded (Call.execute builds a FormBody from params).
- CAVEAT: the per-class detail GET `/np/company/{club}/class/{id}` returns 400
  for these ids (all variants tried). The MCP preview instead finds the class
  in the class LIST (which carries `details.cancellationWindowEnd`).
- Booking is UNVERIFIED. One test book returned HTTP 523
  `externalServiceFailure.400` (request passed auth, reached the booking
  handler, external system rejected it). No booking was created. BUT the test
  account was not active at the time, so this is inconclusive. Retest with an
  active membership.
- Observation: the classes seen were all `reservable=false` with
  `availableOptions=null` (check-in based). Booking may only apply to studios
  that REQUIRE reservation (`cbc.brc=true`). The book/cancel tools are built
  and structured correctly; whether a given class is bookable depends on the
  studio and an active membership.

### Open items to confirm with ONE live login (needs user credentials)

- Confirm `POST /np/exerciser/login` returns JSESSIONID + uuid for this account.
- Confirm the `clubUuid` for `/np/company/{clubUuid}/classes` equals the gym
  finder `gymUUID` (`g`). If not, find the mapping (login gives `homeClubUuid`).
- Enumerate the accepted `type` (category) values.
- Save a redacted `GroupXClass` fixture and build `search_classes` + tests.

### Why no MITM

The `adb pull` gave the full native Netpulse API: host, login, session auth,
and the class endpoint with its exact params and model. MITM is only a fallback
if the live login behaves differently than the decompiled code shows.
