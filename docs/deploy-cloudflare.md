# Internet access through Cloudflare Tunnel and Cloudflare Access

The Studio can be opened at **https://studio.andresgustavo.com**, from a desktop browser or as the installed
phone app ([mobile.md](mobile.md)). Cloudflare Access signs people in, a Cloudflare Tunnel carries the traffic
to this computer, and the Studio checks Cloudflare's signed token on every request. Nothing listens on a public
network interface, and no router port is open.

> **Public read-only view (2026-10-17):** the plan is for `studio.andresgustavo.com` to become an anonymous,
> read-only view (port 8081) and editing to move to `admin.andresgustavo.com` (this page's setup, unchanged).
> See [public-access.md](public-access.md) for the design and the dashboard steps. Until those steps are done,
> everything below is still what runs.

- [1. How it fits together](#1-how-it-fits-together)
- [2. Start, stop, status](#2-start-stop-status)
- [3. Start after a reboot](#3-start-after-a-reboot)
- [4. Settings](#4-settings)
- [5. Cloudflare configuration](#5-cloudflare-configuration)
- [6. Security model](#6-security-model)
- [7. Checks](#7-checks)
- [8. Troubleshooting](#8-troubleshooting)

## 1. How it fits together

```
phone / browser ──https──> Cloudflare edge ── Access: sign-in, policy ──> Tunnel "halo-studio"
                                                                              │ (outbound connection made by
                                                                              │  the Cloudflared service here)
                                                                              v
             http://127.0.0.1:8080  remote listener  ── verifies Cf-Access-Jwt-Assertion on EVERY request
             http://127.0.0.1:8765  local listener   ── this computer only; the only place game installs work
                       └── one process: scripts/ui/m4_server.py (Python standard library), frontend/dist + API
```

- **One process, one origin per listener.** `m4_server.py` serves the built Vue app (`frontend/dist`), the JSON
  API, the audio (with HTTP range requests), waveform peaks and editor previews from the same address. There is
  no development server and no separate proxy. The Vite dev server (`npm run dev`) is never used in production.
- **Port 8080** is used because the tunnel's public hostname was already routed to `http://localhost:8080` in the
  Cloudflare dashboard. Keeping that route meant no dashboard change was needed.
- **Routes.** The app uses hash routes (`/#/match`, `/#/build`, …). Opening or refreshing any of them loads `/`,
  so direct links and reloads always work.

## 2. Start, stop, status

From the repository root, in PowerShell:

```powershell
.\scripts\deploy\studio.ps1 start            # background; builds frontend\dist first if it is missing
.\scripts\deploy\studio.ps1 start -Build     # rebuild the frontend first (after pulling changes)
.\scripts\deploy\studio.ps1 status           # process, both listeners, tunnel connector + route, public URL
.\scripts\deploy\studio.ps1 stop             # clean shutdown
.\scripts\deploy\studio.ps1 restart          # after changing config\studio_server.json
```

- The server's output goes to `work\studio\server.log`. `work\studio\server.json` records which process is
  running.
- **Clean shutdown:** `stop` runs `python scripts/ui/m4_server.py --stop`. That writes `work\studio\server.stop`,
  which the server watches. The server waits for any running build or install to finish (so an install's backup
  and rollback are never cut short), then closes its listeners and exits. Database writes are transactions
  either way.
- Running in the foreground also works: `python scripts/ui/m4_server.py --no-open` (Ctrl+C stops it).

## 3. Start after a reboot

The tunnel connector is already a Windows service (`Cloudflared`, automatic start). For the Studio itself:

```powershell
.\scripts\deploy\studio.ps1 register-startup     # once
.\scripts\deploy\studio.ps1 unregister-startup   # to undo
```

This registers a Scheduled Task, **"Halo Localization Studio"**. It runs `studio.ps1 start` as you, 30 seconds
after you sign in to Windows, with normal (not elevated) rights and no stored password. It is not a Windows
service: the Studio runs only while you are signed in, and you can see or delete the task in Task Scheduler.
Without the task, run `.\scripts\deploy\studio.ps1 start` after signing in.

## 4. Settings

`config/studio_server.json` (git-ignored). A template is in `config/studio_server.cloudflare.example.json`.

```json
"remote": { "enabled": true, "host": "127.0.0.1", "port": 8080, "auth": "cloudflare_access" },
"public_url": "https://studio.andresgustavo.com",
"secure_cookies": true,
"cloudflare_access": {
  "team_domain": "summer-math-c05e.cloudflareaccess.com",
  "aud": ["40a2f228…1386"],
  "users": { "you@example.com": "admin" }
}
```

| Setting | Meaning |
|---|---|
| `remote.auth` | `"cloudflare_access"`: every request needs a valid Access token, and password sign-in is off. `"password"` (default) is the LAN / Tailscale mode of [remote-access.md](remote-access.md). |
| `remote.host` | Must be loopback in this mode; the server refuses to start otherwise. Only `cloudflared` on this computer connects. |
| `cloudflare_access.team_domain` | Your Zero Trust team domain. It is also the token's issuer (`https://<team_domain>`). |
| `cloudflare_access.aud` | The Access application's **Application Audience (AUD) Tag**. |
| `cloudflare_access.users` | The Access e-mail addresses allowed in, each with a Studio role (`admin` or `editor`, see [remote-access.md §3](remote-access.md#3-accounts)). Lower case. |

None of these values is a secret: the team domain and the AUD tag appear in Cloudflare's own login redirect. The
tunnel token stays in `C:\ProgramData\cloudflared\token`, read only by the Cloudflared service. The Studio never
reads it, and it is never in this repository. Missing or invalid settings stop the server at start-up (fail
closed). Restart after changing them.

To let another person in: add them to the Access policy in Cloudflare **and** to `cloudflare_access.users`, then
`.\scripts\deploy\studio.ps1 restart`.

## 5. Cloudflare configuration

Already in place (checked on 2026-10-14 from the connector's local metrics, `http://127.0.0.1:20241/config`, and
by unauthenticated requests to the public address):

- Tunnel `halo-studio`, run by the `Cloudflared` Windows service with a token file, so it is dashboard-managed.
  4 edge connections.
- Public hostname `studio.andresgustavo.com` → `http://localhost:8080`. The only other rule is the catch-all
  `http_status:404`.
- Access application on that hostname. Every path tried (`/`, `/api/*`, `/audio/*`, `/assets/*`,
  `/manifest.webmanifest`, `/sw.js`, `/classic`) redirects to the team's login page. Plain HTTP redirects to
  HTTPS.

Optional hardening in the dashboard (Zero Trust → Networks → Tunnels → `halo-studio` → Public hostname →
`studio.andresgustavo.com` → Edit):

- **Service URL** `http://127.0.0.1:8080` instead of `http://localhost:8080`. It avoids an IPv6 attempt first
  (`::1`), which the Studio does not listen on. It works either way.
- **Additional application settings → Access → Protect with Access**: on, with your team name and the same AUD
  tag. `cloudflared` then also rejects requests without a valid token before they reach the Studio, as a second
  check.

In the Access application, keep the policy limited to your own e-mail address(es). Don't add **Bypass** or
**Service Auth** policies, and don't create a second application on a path of this hostname that has a looser
policy. The Studio refuses tokens without an e-mail address (service tokens) and tokens for any other
application anyway.

## 6. Security model

| Concern | What happens |
|---|---|
| Reaching the Studio without Access | The remote listener is bound to 127.0.0.1. Each request must carry `Cf-Access-Jwt-Assertion`, which the Studio verifies itself (`scripts/ui/cf_access.py`): an RS256 signature against the team's keys (from `https://<team>/cdn-cgi/access/certs`, over verified HTTPS, cached and fetched again when Cloudflare rotates them), `iss`, `aud`, `type == "app"`, `exp` / `nbf` / `iat`, and an `email` listed in the settings. Otherwise it answers 401/403. That includes the page's own files: nothing is served without a token. |
| Forged identity headers | `Cf-Access-Authenticated-User-Email`, cookies and the like are ignored. Only the verified token counts. |
| The local administrator address | `127.0.0.1:8765` refuses any request with proxy or tunnel headers (`Cf-Connecting-Ip`, `Cf-Ray`, `Cf-Access-Jwt-Assertion`, `X-Forwarded-For`, …), so a tunnel pointed at the wrong port cannot make a visitor look local. |
| Game files | Installing into MCC, restoring it, and changing the MCC folder are refused on the tunnel listener for every account. They remain possible only at `http://127.0.0.1:8765/` on this computer. |
| Writes / CSRF | Every POST needs `X-Studio-CSRF`, a per-account HMAC token from `/api/session` (key in git-ignored `work/studio/access_csrf.key`). Bodies must be JSON, and `Origin` must be the Studio's own. Access's cookie is `SameSite=Lax`. |
| CORS / DNS rebinding | No CORS headers. `Host` must be `studio.andresgustavo.com` or a name of this computer. |
| Files | Audio is served only for catalogue entries and content-hashed preview keys, never by path. Static files come only from `frontend/dist`, after path normalisation. `config/`, `mappings/`, databases, backups and logs are never served. `/classic` is not served on this listener. |
| Debug / development | No debug endpoints. Test-only options (`--mcc-root`, `--deploy-state`, `--state-dir`) are never used by `studio.ps1`. The Vite dev server is not used. |
| Secrets | No secret is in the repository, the settings or the logs. The token itself is never logged. Every write is recorded (who, from where, what, result) in `work/studio/audit.jsonl`. |
| If Access keys cannot be fetched | Remote requests are refused (503) until they can be fetched. The local address keeps working. |

## 7. Checks

```powershell
python -m unittest tests.test_cf_access tests.test_remote_access   # verifier, settings, real handler
.\scripts\deploy\studio.ps1 status
```

Expected from `status`: local 200, tunnel 401 without a token, public 302 to Cloudflare Access.

After signing in on the phone, `http://127.0.0.1:20241/metrics` (on this computer) shows
`cloudflared_tunnel_total_requests` going up and `cloudflared_tunnel_request_errors 0`.

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| Cloudflare error 502 / 1033 after signing in | The Studio is not running: `.\scripts\deploy\studio.ps1 status`, then `start`. Check `work\studio\server.log`. |
| "signed in to Cloudflare Access as X, which is not a Studio account" | Add X (lower case) to `cloudflare_access.users`, then `restart`. |
| "this address only answers requests that come through Cloudflare Access" | A request reached port 8080 without passing Access (for example a local test, or Access is off for the hostname). Check the Access application. |
| "Your Cloudflare Access sign-in has expired" in the app | Tap **Sign in with Cloudflare Access**. Unsaved edits on the device are kept. The session length is the Access application's *Session Duration*. |
| "missing or wrong CSRF token" | Reload the page (the server's CSRF key changed, for example `work/studio/` was cleaned). |
| The phone app does not offer installing | Open it in the browser while signed in, then Install / Add to Home Screen ([mobile.md §9](mobile.md)). The manifest is requested with credentials (`crossorigin="use-credentials"`) so Access lets it through. |
| `the remote listener needs …` / settings errors at start | Read the message: the server refuses incomplete Cloudflare settings on purpose. |
