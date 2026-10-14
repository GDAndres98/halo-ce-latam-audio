# Remote access: using the Studio from other computers

The host computer runs the Studio server. It holds the database, the game files, the extracted audio and
the tools (vgmstream, ffmpeg, libcelt). Other computers only need a browser. They never get copies of the
game, the recordings or the database: every page, decision and recording is served by the host.

- [1. How it works](#1-how-it-works)
- [2. Start the host](#2-start-the-host)
- [3. Accounts](#3-accounts)
- [4. LAN access](#4-lan-access)
- [5. Secure internet access (Tailscale, recommended)](#5-secure-internet-access-tailscale-recommended)
- [6. Connect from a second computer](#6-connect-from-a-second-computer)
- [7. Working together](#7-working-together)
- [8. Security model](#8-security-model)
- [9. Settings reference](#9-settings-reference)
- [10. Troubleshooting](#10-troubleshooting)
- [11. For developers](#11-for-developers)

## 1. How it works

One Python process (`scripts/ui/m4_server.py`, standard library only) has two listeners. Both share one
application and one decisions database (`mappings/manual_mappings.db`).

| Listener | Address (default) | Who | Sign-in | Can install into / restore the game |
|---|---|---|---|---|
| **local** | `http://127.0.0.1:8765/` | the host computer only | no | **yes** (the only place) |
| **remote** | port `8766`, off unless enabled | other computers (LAN, Tailscale) | **yes** | **never**, whatever the role |

Both serve the built Studio (`frontend/dist`) and the API from the same address, so no development proxy is
needed. The classic page is at `/classic`, on the local listener only.

The local listener only accepts loopback addresses (`local.host` must be `127.0.0.1`, `::1` or `localhost`).
It refuses proxied requests (`X-Forwarded-For`, `Forwarded`, `Tailscale-User-Login`, …), so a reverse proxy
pointed at the wrong port cannot make a remote visitor look like the host's owner.

## 2. Start the host

From `frontend/`, once after each update:

```sh
npm install          # first time only
npm run build        # builds frontend/dist
```

Then start the server:

```sh
npm run serve        # this computer only: http://127.0.0.1:8765/
npm run host         # builds, then also listens for other computers (sign-in required)
```

`npm run host` is `python scripts/ui/m4_server.py --lan --no-open`. You can run the server directly, with these
options:

```sh
python scripts/ui/m4_server.py --lan                        # remote listener on 0.0.0.0:8766
python scripts/ui/m4_server.py --lan --remote-host 192.168.1.10 --remote-port 8766
python scripts/ui/m4_server.py --config path/to/studio_server.json
```

The server prints the addresses to give to the other computers. They are also on the **Network** page of the
Studio. The server refuses to start the remote listener while no account exists.

`npm run dev`, the Vite development server, is for working on the Studio's code. It listens on `localhost`
only and must never be exposed to other computers.

## 3. Accounts

Accounts are kept on the host, in `config/studio_users.json` (git-ignored; passwords are stored only as scrypt
hashes). They are managed from a terminal on the host:

```sh
python scripts/ui/studio_users.py add andy --role admin    # asks for the password twice (10+ characters)
python scripts/ui/studio_users.py add sofia                # role "editor"
python scripts/ui/studio_users.py list
python scripts/ui/studio_users.py sessions                 # who is signed in, from where
python scripts/ui/studio_users.py passwd sofia             # also signs sofia out everywhere
python scripts/ui/studio_users.py role sofia admin
python scripts/ui/studio_users.py signout sofia
python scripts/ui/studio_users.py remove sofia
```

Changes apply at once, without restarting the server.

| Role | Can do |
|---|---|
| **editor** | Everything in Matching: browse, search, listen, edit audio, previews, subtitles, save drafts, approve, Needs rework, flags, notes, level status. Read Build & Test and Data. |
| **admin** | Also: start builds, change the audio level setting, import or export the mappings JSON. |

Neither role can install a build into MCC, restore the original game files, or change the MCC folder. Those
stay on the host's own address (`http://127.0.0.1:8765/`). Keep the hash verification, backups and rollback
of `m6_install.py` under the owner's direct control.

## 4. LAN access

For computers on the same home network:

1. Create an account (section 3).
2. Start the host with `npm run host`.
3. Allow the port through Windows Firewall, for private networks only (PowerShell **as administrator**, once):

   ```powershell
   New-NetFirewallRule -DisplayName "Halo Localization Studio (LAN)" -Direction Inbound -Protocol TCP `
     -LocalPort 8766 -Profile Private -RemoteAddress LocalSubnet -Action Allow
   ```

   If Windows asked about Python when the server started, choose **Private networks** only. Check that your
   home network is marked *Private* (Settings → Network & internet → your connection → Network profile type).
4. On the other computer, open `http://<host LAN address>:8766/` (for example `http://192.168.1.10:8766/`) and
   sign in.

Plain LAN access is **not encrypted** (HTTP): someone on the same network could read the traffic, including
the password when signing in. The sign-in page says so. Use it only on a network you trust, or use Tailscale
(section 5) on the LAN too. Tailscale encrypts traffic between your own devices even when they are on the same
network.

To remove the firewall rule later:

```powershell
Remove-NetFirewallRule -DisplayName "Halo Localization Studio (LAN)"
```

## 5. Secure internet access (Tailscale, recommended)

**Never forward a router port to the Studio, and never put it on the public internet.**

[Tailscale](https://tailscale.com/kb/1151/what-is-tailscale) makes a private, encrypted network (a
*tailnet*) of your own devices. With **Tailscale Serve**, the Studio gets a valid HTTPS address, such as
`https://studio-pc.tail1234.ts.net/`, that only devices signed in to your tailnet can open. Nothing is
reachable from the public internet. The Studio's own sign-in still applies on top of that.

Do **not** use **Tailscale Funnel**: Funnel makes a service public on the internet
([Tailscale: Funnel](https://tailscale.com/kb/1223/funnel)).

### One-time setup (needs your Tailscale account)

These steps need your own account and devices, so they are yours to do:

1. Install Tailscale on the host and on each computer that will use the Studio, and sign in with the same
   account (or invite the other person to your tailnet).
2. In the Tailscale admin console, under **DNS**, enable **MagicDNS** and **HTTPS Certificates**
   ([Tailscale: Enabling HTTPS](https://tailscale.com/kb/1153/enabling-https)).
3. Find the host's name: `tailscale status` (for example `studio-pc`), and your tailnet name in the admin
   console (for example `tail1234.ts.net`).

### Configure the Studio for Tailscale

Copy `config/studio_server.example.json` to `config/studio_server.json` and change these settings:

```json
{
  "schema": "studio-server/1",
  "local": { "host": "127.0.0.1", "port": 8765 },
  "remote": { "enabled": true, "host": "127.0.0.1", "port": 8766, "tls_cert": null, "tls_key": null },
  "allowed_hosts": ["studio-pc.tail1234.ts.net"],
  "allowed_origins": [],
  "public_url": "https://studio-pc.tail1234.ts.net",
  "session": { "idle_hours": 72, "max_days": 14 },
  "secure_cookies": true,
  "users_file": "config/studio_users.json",
  "sessions_file": "work/studio/sessions.sqlite",
  "audit_file": "work/studio/audit.jsonl",
  "static_dir": "frontend/dist"
}
```

- `remote.host` is `127.0.0.1`. The remote listener is then reachable **only** through Tailscale Serve on
  this computer, not directly from the LAN. No firewall rule is needed.
- `secure_cookies: true`. The session cookie is only ever sent over HTTPS.
- `public_url` is shown on the Network page, and its host is accepted in `Host` and `Origin`.

Start the Studio (`npm run host`), then publish the remote listener to your tailnet, once:

```sh
tailscale serve --bg http://127.0.0.1:8766
tailscale serve status          # shows https://studio-pc.tail1234.ts.net/ -> http://127.0.0.1:8766
```

`--bg` keeps it published across restarts until you remove it with `tailscale serve reset`
([Tailscale: `tailscale serve` command](https://tailscale.com/kb/1242/tailscale-serve)). Always point
Tailscale Serve at the **remote** port (8766), never at 8765: the local listener refuses proxied requests.

### Alternative: HTTPS directly from the Studio

If you prefer not to use Serve, the remote listener can serve HTTPS itself with a certificate you provide.
For example, use `tailscale cert studio-pc.tail1234.ts.net`, which writes a `.crt` and a `.key` file for your
tailnet name ([Tailscale CLI: cert](https://tailscale.com/kb/1080/cli#cert)). Put them in `config/` (both are
git-ignored) and set:

```json
"remote": { "enabled": true, "host": "0.0.0.0", "port": 8766,
            "tls_cert": "config/studio-pc.tail1234.ts.net.crt", "tls_key": "config/studio-pc.tail1234.ts.net.key" },
"allowed_hosts": ["studio-pc.tail1234.ts.net"],
"public_url": "https://studio-pc.tail1234.ts.net:8766"
```

Tailscale certificates expire after 90 days. Run `tailscale cert` again before then and restart the Studio.
With `host` set to `0.0.0.0`, the Windows Firewall rule from section 4 is needed. Tailscale Serve (above)
renews certificates by itself and needs no firewall rule, which is why it is the recommended route.

## 6. Connect from a second computer

1. Get the address from the host's **Network** page (or from the server's start-up message).
   - LAN: `http://192.168.1.10:8766/`
   - Tailscale: `https://studio-pc.tail1234.ts.net/` (the second computer must be signed in to Tailscale)
2. Open it in any current browser (Edge, Chrome, Firefox or Safari, on Windows, macOS or Linux) and sign in.
3. Use the Studio as on the host. Recordings, waveforms and previews stream from the host on demand. Nothing is
   downloaded in advance, and nothing needs installing.

Signing out is at the top right. Unsaved typing stays in that browser's session if the session ends; sign in
again and it is still there.

Phones and tablets connect the same way and get a touch layout, and can install the Studio as an app from the
https (Tailscale) address: see [mobile.md](mobile.md).

## 7. Working together

- **One database.** Every computer reads and writes the host's `mappings/manual_mappings.db`. There is nothing
  to synchronise.
- **Live updates.** When any computer saves, the others update within about a second, through Server-Sent
  Events (`/api/events`). That covers the MCC list, the Dashboard counters, the "hide used recordings" filter,
  and the open line if it has no unsaved changes ("This line was just updated by sofia"). Changes made by tools
  run on the host are announced too: the server watches the database's history, not just its own requests.
- **Per-line protection.** Each save carries the version of *that line* the page loaded. Two people can work on
  different lines at the same time. If someone else saved the same line in the meantime, the save is refused
  (409) and nothing is written. Your edits stay on screen. Use *Reload and keep my edits*, check them, and save
  again. If the line changes while you have unsaved edits, a warning says who changed it before you even try to
  save.
- Approvals and Needs rework follow the same rules as on the host: approved decisions are read-only until marked
  Needs rework, and every change is recorded in the database history.
- Every write request (who, from where, what, result) is appended to `work/studio/audit.jsonl` on the host.

## 8. Security model

| Concern | What the Studio does |
|---|---|
| Who can connect | Remote listener off by default. Sign-in required for every API and audio request; only the sign-in page and the built page's static files are public. The server will not start the remote listener without an account. |
| Passwords | scrypt (N=2^17, r=8, p=1, per the [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)) with a random salt, standard library `hashlib.scrypt`. At least 10 characters. Never logged. |
| Sessions | 256-bit random tokens (`secrets`), in an `HttpOnly; SameSite=Strict` cookie (`Secure` over HTTPS). Only their SHA-256 is stored. They expire after 72 h idle and 14 days at most, and end on sign-out, password change, role change or account removal. |
| Guessing | 5 failed sign-ins per address or per account in 15 minutes lock it for 15 minutes. The answer is the same for a wrong name or a wrong password. |
| CSRF | Every remote POST needs the session's own token in `X-Studio-CSRF` (constant-time compare). Also a SameSite=Strict cookie, JSON-only bodies, and an `Origin` check. |
| CORS, DNS rebinding | No CORS headers: only same-origin pages can call the API. `Host` must be a name or address of this computer, or one in `allowed_hosts`. `Origin` must match. |
| Files | Audio is served only for catalogue entries and content-hashed preview keys; there are no path parameters. Static files are served only from `frontend/dist`, after path normalisation. The database, mappings, backups, config, sessions and accounts are never served. |
| Commands | No endpoint runs arbitrary commands. Builds run the fixed `m6_build.py` with validated arguments (admin only). |
| Game files | Install, restore and MCC folder changes are refused on the remote listener for every role, and are only possible on the local listener. `m6_install.py`'s hash checks, backups and rollback are unchanged. |
| Page | `Content-Security-Policy` (own scripts only, no framing), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`. |
| Transport | HTTPS through Tailscale Serve (recommended) or the listener's own TLS 1.2+. Plain HTTP only for a trusted LAN, with a warning. |

## 9. Settings reference

`config/studio_server.json` (git-ignored; copy `config/studio_server.example.json`). Unknown settings are
refused, so a typo never silently keeps a default. Command-line options override the file.

| Setting | Default | Meaning |
|---|---|---|
| `local.host`, `local.port` | `127.0.0.1`, `8765` | The host's own address (loopback only). `--port` |
| `remote.enabled` | `false` | Listen for other computers. `--lan` |
| `remote.host`, `remote.port` | `0.0.0.0`, `8766` | `0.0.0.0` means every network; `127.0.0.1` means through Tailscale Serve only. `--remote-host`, `--remote-port` |
| `remote.tls_cert`, `remote.tls_key` | `null` | HTTPS on the remote listener (PEM files). |
| `allowed_hosts` | `[]` | Extra host names to accept (for example the Tailscale name). `--allowed-host` |
| `allowed_origins` | `[]` | Extra browser origins (`https://name`). `--allowed-origin` |
| `public_url` | `null` | The address to show to other computers; its host and origin are accepted. |
| `session.idle_hours`, `session.max_days` | `72`, `14` | Session lifetime. |
| `secure_cookies` | `"auto"` | `"auto"`: Secure over HTTPS (own TLS, or `X-Forwarded-Proto: https` from a proxy on this computer). `true`: always. |
| `users_file`, `sessions_file`, `audit_file` | `config/studio_users.json`, `work/studio/sessions.sqlite`, `work/studio/audit.jsonl` | Accounts, sessions, and the log of write requests. `--state-dir` (tests) moves the last two. |
| `static_dir` | `frontend/dist` | The built Studio. `--static-dir` |

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| The other computer cannot connect (timeout) | Is the server started with `--lan`? Is the firewall rule there (`Get-NetFirewallRule -DisplayName "Halo Localization Studio (LAN)"`)? Is the network profile *Private*? Are both computers on the same network? On the host, does `Test-NetConnection 192.168.1.10 -Port 8766` succeed? |
| `bad Host header` (403) | You used a name the server does not know (for example a new DNS name). Add it to `allowed_hosts`. |
| `cross-origin request refused` (403) | The page was opened under one name and calls another. Use one address, or add the origin to `allowed_origins`. |
| Sign-in works but you are signed out at once | `secure_cookies: true` over plain HTTP: the browser drops Secure cookies on HTTP. Use the HTTPS address or `"auto"`. |
| `too many failed sign-ins` | Wait 15 minutes, or restart the server (the lock is in memory). Reset the password with `studio_users.py passwd`. |
| `remote access needs at least one account` | Create one: `python scripts/ui/studio_users.py add <name> --role admin`. |
| The page says the Studio is not built | Run `npm run build` in `frontend/` on the host. |
| `tailscale serve` address does not load | `tailscale serve status`; MagicDNS and HTTPS Certificates enabled in the admin console; the other device signed in to the same tailnet; Serve points at `http://127.0.0.1:8766`, not 8765. |
| Install buttons are disabled on another computer | By design. Install and restore on the host, at `http://127.0.0.1:8765/`. |
| "Live updates" is not "connected" on the Network page | Something between the computers buffers streaming responses. The page still works; reload to see others' changes. |
| Port already in use | Another Studio is running, or choose other ports (`--port`, `--remote-port`). |

## 11. For developers

| Part | File |
|---|---|
| Listeners, routing, permissions, static files, audio ranges, gzip, SSE | `scripts/ui/m4_server.py` |
| Accounts, password hashing, sessions, throttling, CSRF | `scripts/ui/studio_auth.py`, CLI `scripts/ui/studio_users.py` |
| Settings, Host / Origin policy, connection info | `scripts/ui/studio_net.py` |
| Change notifications (database history watch) | `scripts/ui/live_feed.py` |
| Waveform peaks | `scripts/common/wav_peaks.py` (`GET /audio/peaks`), `frontend/src/audio/peaks.ts` |
| Per-line versions | `slot_version()` and `loaded_slot_sha256` in `scripts/ui/m4_app.py` |
| Session, sign-in, live updates (UI) | `frontend/src/auth/session.ts`, `frontend/src/live/changes.ts`, `views/LoginView.vue`, `views/NetworkView.vue` |

Everything server-side stays standard library only (`tests/test_m4.py` checks the imports).

Tests:

```sh
python -m unittest tests.test_remote_access     # accounts, sessions, CSRF, permissions, files, ranges, feed
cd frontend && npm run test:remote              # two browser sessions over the LAN address (disposable data)
```

`npm run test:remote` builds the Studio and makes a disposable copy of the mappings with two throw-away
accounts. It starts the server with `--lan` on this computer's LAN address and drives two separate browser
sessions through it. It never touches the game folder or the real mappings.

**Audio delivery.** Clips are decoded on the host on demand. Waveforms are drawn from server peaks (a few KB),
and the audio itself streams with HTTP range requests, so seeking works before the whole file arrives.
Decoded clips are cached by the browser for 10 minutes with ETag revalidation. Previews are content-addressed
(the key is a hash of what they were rendered from) and cached as immutable. JSON and static files are
gzip-compressed, and connections are kept alive.

A newer edit cancels the preview request in flight (`useEditPreview.ts`). The host still finishes rendering
the cancelled one, and caches it under its key.
