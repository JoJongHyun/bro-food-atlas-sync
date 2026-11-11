# Work handoff: Naver Map saved-place hours → Bro Food Atlas

## Goal
Maintain the user's existing saved restaurants/cafés in the site without repeatedly
sending XML exports to ChatGPT. Retain the current site URL, existing data,
filters, and backward-compatible GET /api/data response.

**Status:** The Android accessibility XML parsing is proven for one manually
opened, expanded place. This does **not** prove that unattended navigation of
thousands of Naver Map pages is possible, permitted, or stable. Naver's 429
response must not be bypassed.

## Code already prepared
- scripts/parse_naver_layout.py: user-exported Naver Map XML → weeklyHours JSON;
  7 weekdays are required for scheduleComplete=true. Does not obtain an SID.
- scripts/match_site_place.py: extraction JSON + *actual site snapshot JSON* →
  candidate for exactly one SID, ONLY if normalized name AND address match.
  Ambiguous or missing matches are pending. This tool **never writes** the site.
- tests/test_pipeline.py: no network, fake records only.

Quick local usage:

~~~sh
python3 scripts/parse_naver_layout.py layout.xml --output extracted.json
python3 scripts/match_site_place.py extracted.json site-api-snapshot.json --output candidate.json
python3 -m unittest discover -s tests -v
~~~

Warning: real XML may contain phone numbers, reviews and other personal data.
Do NOT commit raw XML, publicly store it, or log full screen layouts.
A sample extracted.json can be used after reviewing/redacting its fields.

## Work tasks: site integration
1. Establish **actual** source repository / deploy access for
   https://bro-food-atlas.faseion0913.chatgpt.site/ .
   This repository currently contains experimental parsers/workflows, NOT
   verified deployed site source. Do not claim site updates until re-reading
   /api/data confirms persistence.
2. Read the live site's /api/data and inspect the exact place schema, with
   special attention to "sid", "hours.rules", "verifiedAt",
   "hoursCoverage", "sync.sources", and source timestamps. The exact live
   shape has not been available from the Chat environment; do not assume a
   field exists merely because the matcher accepts it.
3. Provide a secured ingestion entry point (e.g. authenticated POST endpoint)
   which accepts ONLY fields needed for one SID and weekly schedule, never raw
   XML/reviews. Require API-token authentication and TLS, with a server-side
   SID/name/address confirmation and scoped write permission. Credentials
   belong in server secrets, not in a public GitHub workflow or APK log.
4. Each candidate must carry source type, source collection time, matched SID,
   matching basis, per-day opening/closing times, explicit closure,
   overnight flag, optional break/last-order (null if unknown),
   deterministic fingerprint, and an ingestion audit record.
5. On each write, re-check the site's current unique SID and prevent data
   regression: do not replace valid times with partial/failed extraction;
   mark mismatch/ambiguous/stale records pending; idempotent same-fingerprint
   writes; log changes; allow rollback. Never infer "saved place deleted"
   from failed origin synchronization. Keep existing verified data intact.
6. Compute display status in Asia/Seoul from saved weekly rules. Handle
   previous-day overnight business across midnight, explicit closure, and
   exceptional holiday overrides when reliably available. Unknown schedule
   => "영업시간 확인 필요", not a fabricated open/closed state.
7. Verify with authorized test data and **actual site API read-back**
   that the correct SID changed and that reported coverage is derived from
   persisted hours.rules rather than simply fetched XML.

## Data ownership and source constraints
- This is a proof of *on-screen accessibility text extraction*, not a new
  official Naver API. Confirm applicable Naver terms and consent before
  unattended large-scale collection or redistribution.
- Respect 429, CAPTCHA, account/anti-bot controls and robots/site rules.
  Do not rotate IPs, forge requests or automate bypasses.
- Preferred long-term feed: an authorized Naver data integration. If not
  available, describe the practical scope of opt-in, user-visible local
  collection rather than promising 4,325-place unattended extraction.
- Work can build local, opt-in Automate→authenticated service transmission
  for future *permitted* captures. This avoids sending each XML to ChatGPT,
  but is NOT proof of bulk navigation capability.
- Do not start or revive the prior Work scheduled job for hourly AI checks.
  The user's existing Chat automation remains separate until the user
  instructs otherwise.

## Acceptance test
1. Expanding the sample place shows Monday closed and Tue–Sun 11:00–15:00.
2. Missing day, duplicate match, SID conflict, mismatched address,
   inaccessible source → **pending**, no write.
3. Known correct data → authenticated import, audit log, then independent
   read-back of the exact SID in /api/data and accurate hoursCoverage change.
4. Re-import identical fingerprint → no duplicate; a failed source call
   never erases prior data. Status updates from site-local time without AI calls.

Do not mark integration complete before #3 and #4 succeed.
