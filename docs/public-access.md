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
| **Only with `public.audio` on:** play the original recordings (MCC Spain / English, Campaign Evolved es-MX / EN / es-ES), their waveforms, and A/B compare with the unedited replacement | Hear editor previews (rendering one is a write), download any file |
| Browse levels, MCC lines, Campaign Evolved lines, search and filters | Choose recordings ("Use this recording" is hidden), edit flags, notes, subtitles or recipes |
| See each decision: match, audio source, approvals, flags, subtitle text (SU / SP / EN / CE / custom), the edit recipe as text | Play any recording or waveform (unless `public.audio` is on); download anything; hear editor previews |
| See progress and statistics | Start builds, change the level setting, install or restore, change the MCC folder |
| See the build list and the history of test installs (sanitised) | Open Data or Network, read build logs, the game folder or file locations |
| | Receive the live change feed (it names who saved) |
| | Read the owner's notes (not public) |

The page shows a **Read-only** badge and **Sign in to edit** (to `sign_in_url`). The decision area ends with a
short read-only notice instead of the save bar. Editing shortcuts (s, Ctrl+S, Ctrl+Enter) and playback keys do
nothing.

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
| Proprietary audio | Never sent to a visitor: no streams, peaks, previews or downloads. The page does not request them (players and download links are not rendered) and the server refuses them anyway. |
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
| `public.audio` | `false` (default): visitors hear nothing. `true`: visitors may play `/audio/mcc`, `/audio/ce` and `/audio/peaks` (rate limited; previews and downloads stay refused). **Turned on by the owner on 2026-10-17, accepting that anything a browser plays can be saved and that this publishes MCC and Campaign Evolved audio.** |

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
  `public.audio` on (owner decision, 2026-10-17) the original recordings of both games are also playable by anyone,
  so they can be saved: the asset question in CLAUDE.md (343 MCC modding FAQ, M8.1) applies. Set it to `false` and
  restart to stop.
- Visitors hear the unedited Campaign Evolved recording as B, not the edited result (previews are rendered on
  request, which is a write).
- Visitors do not get live updates; they see changes on reload.
- The owner's notes are not public. To publish them, remove `"notes"` from `public_view.DENY_KEYS`.
- An installed phone app keeps its origin: the app installed from `studio` becomes the read-only view after
  step 4. Install the editing app from `admin`.
