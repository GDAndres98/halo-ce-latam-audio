# Public read-only Studio

Anyone can open **https://studio.andresgustavo.com** and browse the Studio without signing in: levels, lines,
matching decisions, subtitles, flags, approvals, progress and the build history. Only the owner edits, at
**https://admin.andresgustavo.com**, behind Cloudflare Access, exactly as before. The server enforces this; the
read-only screens only stop people from trying.

- [1. Architecture](#1-architecture)
- [2. What a visitor can and cannot do](#2-what-a-visitor-can-and-cannot-do)
- [3. Endpoint classification](#3-endpoint-classification)
- [4. Security model](#4-security-model)
- [5. Settings](#5-settings)
- [6. Rollout (owner, Cloudflare dashboard)](#6-rollout-owner-cloudflare-dashboard)
- [7. Checks](#7-checks)
- [8. Limitations](#8-limitations)

## 1. Architecture

Two host names, two listeners, one server process. Same Vue app on both; it asks `/api/session` what it is
allowed to do.

```
visitor ──https──> studio.andresgustavo.com  (no Access) ──┐
                                                           ├─ Tunnel "halo-studio" (Cloudflared service)
owner   ──https──> admin.andresgustavo.com ── Access ──────┘
                                                           │
  http://127.0.0.1:8081  public listener   anonymous, read-only allowlist, sanitised answers  (scripts/ui/public_view.py)
  http://127.0.0.1:8080  remote listener   Cloudflare Access JWT verified on every request    (scripts/ui/cf_access.py)
  http://127.0.0.1:8765  local listener    this computer only; the only place game installs work
```

Two host names instead of one host with mixed rules, because:

- **The editing API is never reachable without Access.** The admin host keeps its Access application, and the
  remote listener keeps verifying the token itself (signature, `iss`, `aud`, `type`, times, listed e-mail). The
  public host routes to a different port, and that port has no write code path at all.
- **No identity on the public side.** The public listener never reads cookies, Access tokens or identity
  headers. Nothing a visitor sends can turn it into more than a visitor.
- **Separate origins.** The Access cookie, the CSRF token, the service worker and the installed app of the admin
  host never mix with the public one. No login redirects happen on the public host, so the installed public app
  cannot loop.

## 2. What a visitor can and cannot do

| Visitor can | Visitor cannot |
|---|---|
| Open the Studio without signing in (desktop, phone, installed app) | Save, approve, reject, mark needs rework, unmatch, mute |
| **Only with `public.previews` on:** play (and seek, replay) the **published edited LATAM preview of an approved line** (§2.1) | Play original recordings: MCC Spain / English, unprocessed Campaign Evolved; hear drafts, reworked lines or the owner's editor previews; trigger any rendering |
| Browse levels, MCC lines, Campaign Evolved lines, search and filters | Choose recordings ("Use this recording" is hidden), edit flags, notes, subtitles or recipes |
| See each decision: match, audio source, approvals, flags, subtitle text (SU / SP / EN / CE / custom), the edit recipe as text | Use download buttons or exports (none are shown or served); see waveforms or the editor |
| See progress and statistics | Start builds, change the level setting, install or restore, change the MCC folder |
| See the build list and the history of test installs (sanitised) | Open Data or Network, read build logs, the game folder or file locations |
| | Receive the live change feed (it names who saved) |
| | Read the owner's notes (not public) |

The page shows a **Read-only** badge and **Sign in to edit** (to `sign_in_url`). The decision area ends with a
short read-only notice instead of the save bar. Editing shortcuts (s, Ctrl+S, Ctrl+Enter) and playback keys do
nothing.

### 2.1 Edited LATAM previews (owner request, 2026-10-17)

**What visitors hear.** The approved Campaign Evolved replacement rendered with its saved recipe (trims, cuts,
fades, radio filter, echo, Victor 933's interference, the export gain), exactly as the build renders it, in the
**Edited LATAM preview** block of a line, with the browser's own player (play, pause, seek, replay; desktop, phone,
installed app). Lines without one say why: "Preview unavailable: the audio is not approved yet", and similar.

**How a preview becomes public.**

1. The owner publishes: `python scripts/build/publish_previews.py` (all eligible lines; `--slot <id>` for some;
   `--dry-run` to see what it would do). It renders into `work/public_previews/` (git-ignored) and writes
   `index.json`. Eligible: audio **approved**, one Campaign Evolved source, mono, no fingerprint drift. Files of lines
   that are no longer eligible are removed. Run it again after approving more lines (unchanged lines are not
   rendered again).
2. With `"public": {"previews": true}`, the public listener serves `GET /audio/public?slot=<slot_id>`. On every
   request it checks the line's **current** saved decision: the audio must still be approved and exactly the one
   published (`audio_key`, a hash of the whole audio decision). A line sent to rework, re-edited or un-approved stops
   playing at once, before any republish.

**Guarantees.** Anonymous requests never render, decode or write anything: they read the index and stream a
pre-rendered file. Visitors address previews by slot id only (already public); file names, preview keys and paths
never leave the server. Originals (`/audio/mcc`, `/audio/ce`), waveforms, editor previews (`/audio/preview`) and
the interference reference stay 401. Responses are `Cache-Control: private` (Cloudflare does not cache them) and
rate limited like the API (240 a minute per address, 8 at once).

**Limitation: hiding download buttons is not protection.** Anything a browser can play can be saved, with the
browser's developer tools, a screen or audio recorder, or a script that requests `/audio/public?slot=…` for every
line. `controlslist="nodownload"` and the absence of download buttons only remove the obvious button. Treat every
published preview as distributed to anyone who opens the site.

### 2.2 Copyright and redistribution assessment (not legal advice)

Turning on `public.previews` publishes audio derived from game assets. The rights involved:

| Source | Owner | Relevant terms |
|---|---|---|
| Campaign Evolved es-MX voice recordings (the replacements) | Microsoft / Halo Studios; performances by the dubbing cast and studio | **MCC modding FAQ (343):** *"Only the assets contained within the retail version of MCC are allowed for use in modding efforts"* (feasibility §7). Campaign Evolved is a different game, so its audio in an MCC mod is not covered. **Microsoft Game Content Usage Rules** (https://www.xbox.com/en-US/developers/rules): allow *"derivative works based upon Game Content, strictly for your personal, noncommercial"* use and encourage sharing such items, but *"you can't sell or otherwise earn any compensation"* and *"If we don't let you know, you need permission from a third party"*. Voice performances may carry such third-party rights. |
| Recipes, matching, subtitle choices | The owner | The owner's own work. |

Assessment:

- **Risk: real but bounded.** A non-commercial fan site streaming short, edited dialogue lines of a Microsoft game
  sits closest to the Game Content Usage Rules' fan-creation allowance. But it conflicts with 343's MCC-specific FAQ
  (Campaign Evolved assets in an MCC mod). The rules can be withdrawn at any time, and dubbing performances may need
  separate permission. The likeliest consequence is a takedown request (to the owner, Cloudflare or the domain
  registrar), not a claim for damages. Takedown-request risk rises with publicity and with full-campaign coverage
  (about 1,100 lines today).
- **What reduces it:** stay non-commercial (no ads, no paid access); credit Microsoft / Halo Studios and the
  dubbing cast; keep it to approved lines; don't offer bulk downloads, archives or a public build; respond quickly
  to any request from Microsoft (setting `previews` to `false` and restarting stops it immediately).
- **What it does not change:** the Workshop release (roadmap M8) is still gated on the M8.1 rights memo. Public
  previews are not a release, and they don't make one permitted.

**Decision:** the owner asked for public playback on 2026-10-17. The code ships with `previews: false`; the owner
turns it on after reading this assessment.

## 3. Endpoint classification

Category 1 (public read-only metadata) is an **allowlist** in `public_view.PUBLIC_GETS`. Anything not in it is
refused on the public listener, including endpoints added later.

| Endpoint | Cat. | Public listener | Admin (Access) listener |
|---|---|---|---|
| static files of `frontend/dist` | 1 | yes | Access token |
| `GET /api/session` | 1 | visitor info, all permissions false | token |
| `GET /api/state`, `/api/slots`, `/api/ce`, `/api/ce_line` | 1 | yes; validation findings reduced to counts | token |
| `GET /api/slot` | 1 | yes; notes removed, no interference lane (it decodes audio), no audio decoding | token |
| `GET /api/builds`, `/api/builds/detail` | 1 | yes; no file locations, no log | token |
| `GET /api/deploy/history` | 1 | yes; game folder, backups and paths removed | token |
| `GET /audio/mcc`, `/audio/ce`, `/audio/preview`, `/audio/peaks`, `/api/interference/reference` | 2 | **401** | token |
| `GET /audio/public?slot=` (published edited preview of an approved line) | 1* | with `public.previews`: 200 / 206 (approved and unchanged) or 404 with the reason; otherwise 401 | – |
| `GET /api/events` (live feed, names authors) | 2 | **401** | token |
| `POST /api/save`, `/api/progress`, `/api/validate`, `/api/edit/preview`, `/api/builds/preview` | 3 | **401** | token + CSRF + Origin |
| `POST /api/settings/export`, `/api/builds/start`, `/api/builds/dry-run`, `/api/data/import/preview`, `/api/data/import`, `/api/data/export` | 4 | **401** | token + CSRF + **admin role** |
| `GET /api/settings/export`, `/api/data/status`, `/api/network`, `/api/job`, `/api/deploy/status`, `/api/deploy/plan`, `/api/builds/log` | 4 | **401** | token |
| `POST /api/deploy/install`, `/api/deploy/restore`, `/api/settings/mcc` | 4 | **401** | **403** (local listener only) |
| `/classic` | – | 404 | 404 (local only) |
| PUT / PATCH / DELETE / OPTIONS | – | 401 | 405 / 401 |

GET side effects audited: `/audio/*` decode into `work/` (refused publicly); `/api/slot` decoded the Victor 933
line for its interference lane, so the public path calls `slot(..., with_interference=False)`. The other public
GETs only read.

## 4. Security model

| Concern | What happens |
|---|---|
| Anonymous writes | Every method other than GET/HEAD is refused (401) before the body is read. `_post`, `_events` and `_audio_path` also refuse the public listener themselves (defence in depth). Nothing is written, not even the audit log. |
| Forged identity | The public listener ignores `Cf-Access-Jwt-Assertion` (even a valid one), cookies, `Cf-Access-Authenticated-User-Email`, `Authorization` and the rest. Its session is always the visitor. |
| Proprietary audio | Originals, waveforms, editor previews and downloads are never sent to a visitor; the page does not request them and the server refuses them. With `public.previews`, only pre-rendered previews of approved, unchanged lines are streamed (§2.1). Anyone can capture what plays. |
| Paths and private data | Answers go through `public_view.sanitize`: keys such as `mcc_root`, `path`, `backup*`, `candidate`, `log`, `notes` are removed everywhere, and any absolute path in text becomes `[path hidden]`. Static files come only from `frontend/dist` after path normalisation; `config/`, `mappings/`, databases, backups, logs and keys are never served. |
| Host / origin | The public listener answers only `Host: studio.andresgustavo.com` (and localhost). The admin listener does not answer the public host name. No CORS headers on either. |
| Binding | All listeners are on 127.0.0.1. The settings refuse a public listener on any other address, on a port already in use by another listener, or with the admin host name. |
| Abuse | Per visitor address (Cloudflare's `Cf-Connecting-Ip`), at most 240 API requests a minute (then 429), and at most 8 public API requests at once (then 503), so visitors cannot starve the owner's listeners. Static files are not limited. |
| Expired sign-in | On the admin host an expired or missing Access token is refused (401) for every request, so editing stops at once; the page keeps unsaved edits on the device and offers Cloudflare's sign-in. |
| Fail closed | Bad or incomplete settings stop the server at start. Unknown endpoints are refused publicly. |

Tests: `python -m unittest tests.test_public_access` (handler-level, synthetic data and keys) and
`npm run test:visitor` (browser, disposable data, desktop and phone).

## 5. Settings

`config/studio_server.json` (git-ignored), new block:

```json
"public": {
  "enabled": true,
  "host": "127.0.0.1",
  "port": 8081,
  "url": "https://studio.andresgustavo.com",
  "sign_in_url": "https://admin.andresgustavo.com/"
}
```

| Setting | Meaning |
|---|---|
| `public.enabled` | Start the public listener (off by default; `--public` on the command line). |
| `public.host` | Must be loopback: only `cloudflared` on this computer connects. |
| `public.port` | 8081 by default; must differ from the other listeners. |
| `public.url` | The public https address. It is the only host name the listener answers. It must differ from `public_url`. |
| `public.sign_in_url` | Where **Sign in to edit** goes. Defaults to `public_url`. |
| `public.previews` | `false` (default): visitors hear nothing. `true`: visitors may play the published edited previews of approved lines (§2.1); publish them with `scripts/build/publish_previews.py`. Originals are never public. Read §2.2 first. (`public.audio`, which played the originals for a few hours on 2026-10-17, was removed; the server refuses it.) |

`public_url` stays the **editing** address (the Access protected one). The template is in
`config/studio_server.cloudflare.example.json`.

## 6. Rollout (owner, Cloudflare dashboard)

The order keeps the Studio protected at every step: the public host is opened to everyone only after it already
points at the read-only listener and the admin host works.

**Step 1: settings for the transition.** In `config/studio_server.json`:

```json
"public_url": "https://admin.andresgustavo.com",
"allowed_hosts": ["studio.andresgustavo.com"],
"public": { "enabled": true, "host": "127.0.0.1", "port": 8081,
            "url": "https://studio.andresgustavo.com", "sign_in_url": "https://admin.andresgustavo.com/" }
```

`allowed_hosts` keeps today's route (`studio` → 8080) working until step 4. Then
`.\scripts\deploy\studio.ps1 restart`. `status` should show `public http://127.0.0.1:8081/ -> 200 … save -> 401`.

**Step 2: protect the admin host first.** Zero Trust → Access → Applications → the Studio's application → Edit →
in the application's domains add a second public hostname: subdomain `admin`, domain `andresgustavo.com`
(path empty). Save. Adding it to the **same** application keeps the AUD tag, so no Studio setting changes.
Keep the policy limited to your e-mail address.

**Step 3: route the admin host.** Zero Trust → Networks → Tunnels → `halo-studio` → Public hostname → Add:
subdomain `admin`, domain `andresgustavo.com`, service type `HTTP`, URL `127.0.0.1:8080`. Save (Cloudflare
creates the DNS record). Open https://admin.andresgustavo.com, sign in, open a line and save a draft to check
editing works. Install the phone app from this address if you use it for editing.

**Step 4: point the public host at the read-only listener.** Tunnels → `halo-studio` → Public hostname →
`studio.andresgustavo.com` → Edit → URL `127.0.0.1:8081`. If you turned on *Additional application settings →
Access → Protect with Access* for this hostname, turn it **off** here (leave it on for `admin`). Save.
Access still protects `studio` at this point: sign in there and check you see **Read-only** and no Save.

**Step 5: open the public host.** Access → Applications → the Studio's application → Edit → remove the
`studio.andresgustavo.com` domain (keep `admin`). Save. Make sure no other Access application covers
`studio.andresgustavo.com`. In a private window, https://studio.andresgustavo.com now opens without a login.

**Step 6: tidy up.** Remove `"studio.andresgustavo.com"` from `allowed_hosts`, then `studio.ps1 restart`.

To undo at any time: add `studio.andresgustavo.com` back to the Access application (it is protected again at
once), then point its route back to `127.0.0.1:8080`.

Optional: Security → WAF → Rate limiting rules for `studio.andresgustavo.com/api/*`, as an extra limit at the
edge.

## 7. Checks

```powershell
python -m unittest tests.test_public_access tests.test_cf_access tests.test_remote_access
cd frontend; npm run test:visitor
.\scripts\deploy\studio.ps1 status
```

After step 5, from any computer: `curl -s -o NUL -w "%{http_code}" https://studio.andresgustavo.com/api/state`
gives 200, `…/api/save -X POST -H "Content-Type: application/json" -d "{}"` gives 401,
`…/audio/mcc?level=a10&lang=spanish&index=0` gives 401, and https://admin.andresgustavo.com/ without signing in
gives 302 to Cloudflare Access.

## 8. Limitations

- Public answers include line metadata and subtitle text from both games (the point of the view). With
  `public.previews` on, edited Campaign Evolved audio is public too: see §2.2. Set it to `false` and restart to stop.
- Published previews are as fresh as the last publish: newly approved lines need `publish_previews.py` again.
  Changed lines stop playing on their own, and a changed export gain is picked up by the next publish.
- Visitors do not get live updates; they see changes on reload.
- The owner's notes are not public. To publish them, remove `"notes"` from `public_view.DENY_KEYS`.
- An installed phone app keeps its origin: the app installed from `studio` becomes the read-only view after
  step 4. Install the editing app from `admin`.
