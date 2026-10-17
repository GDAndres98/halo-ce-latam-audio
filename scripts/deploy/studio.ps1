<#
.SYNOPSIS
  Start, stop and check the Halo Localization Studio production server on this Windows computer
  (docs/deploy-cloudflare.md).

.DESCRIPTION
  One server process (scripts/ui/m4_server.py, Python standard library) serves the built Studio and its API:
    - http://127.0.0.1:8765/  the host's own address (no sign-in; the only place game installs are possible)
    - http://127.0.0.1:8080/  the Cloudflare Tunnel's address (Cloudflare Access verified on every request)
    - http://127.0.0.1:8081/  optional public read-only view for anonymous visitors (docs/public-access.md)
  Both listen on 127.0.0.1 only. Settings: config/studio_server.json (git-ignored).

  .\scripts\deploy\studio.ps1 start [-Build]   start in the background (log: work\studio\server.log)
  .\scripts\deploy\studio.ps1 stop             clean shutdown (waits for a running build or install to end)
  .\scripts\deploy\studio.ps1 restart [-Build]
  .\scripts\deploy\studio.ps1 status           process, listeners, tunnel connector, public address
  .\scripts\deploy\studio.ps1 build            npm install (first time) + production build of the frontend
  .\scripts\deploy\studio.ps1 register-startup start the Studio when you sign in to Windows (Scheduled Task)
  .\scripts\deploy\studio.ps1 unregister-startup

  -Build rebuilds frontend\dist first. start also builds when frontend\dist is missing.
#>
param(
  [Parameter(Position = 0)]
  [ValidateSet("start", "stop", "restart", "status", "build", "register-startup", "unregister-startup")]
  [string]$Command = "status",
  [switch]$Build
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StateDir = Join-Path $Root "work\studio"
$PidFile = Join-Path $StateDir "server.json"
$LogFile = Join-Path $StateDir "server.log"
$Server = Join-Path $Root "scripts\ui\m4_server.py"
$TaskName = "Halo Localization Studio"

function Get-Python {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) { throw "python is not on PATH" }
  return $py.Source
}

function Get-StudioProcess {
  if (-not (Test-Path $PidFile)) { return $null }
  try { $info = Get-Content $PidFile -Raw | ConvertFrom-Json } catch { return $null }
  $p = Get-Process -Id $info.pid -ErrorAction SilentlyContinue
  if ($p -and $p.ProcessName -like "python*") { return @{ Info = $info; Process = $p } }
  return $null
}

function Invoke-Build {
  Push-Location (Join-Path $Root "frontend")
  try {
    if (-not (Test-Path "node_modules")) { npm ci; if ($LASTEXITCODE) { throw "npm ci failed" } }
    npm run build
    if ($LASTEXITCODE) { throw "npm run build failed" }
  } finally { Pop-Location }
}

function Test-Url($url, $hostName = $null) {
  # curl.exe ships with Windows 10+; works the same from Windows PowerShell 5.1 and PowerShell 7.
  $curlArgs = @("-s", "-o", "NUL", "-w", "%{http_code}", "--max-time", "10")
  if ($hostName) { $curlArgs += @("-H", "Host: $hostName") }
  $code = & curl.exe @curlArgs $url
  if ($code -match '^\d{3}$' -and $code -ne "000") { return [int]$code }
  return $null
}

function Start-Studio {
  $running = Get-StudioProcess
  if ($running) { Write-Host "The Studio is already running (pid $($running.Info.pid))."; return }
  if ($Build -or -not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) { Invoke-Build }
  New-Item -ItemType Directory -Force $StateDir | Out-Null
  if (Test-Path $PidFile) { Remove-Item $PidFile }  # left by a crash or a power cut
  $python = Get-Python
  # A hidden window that keeps running after this terminal closes; its output goes to the log.
  $cmd = "`"$python`" -u `"$Server`" --no-open >> `"$LogFile`" 2>&1"
  Start-Process -FilePath "cmd.exe" -ArgumentList "/d /c `"$cmd`"" -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if ((Get-StudioProcess) -and (Test-Url "http://127.0.0.1:8765/api/session") -eq 200) {
      Write-Host "Studio started. This computer: http://127.0.0.1:8765/   Log: $LogFile"
      $info = (Get-StudioProcess).Info
      if ($info.public_url) { Write-Host "Through Cloudflare: $($info.public_url) (tunnel -> $($info.remote))" }
      if ($info.public) { Write-Host "Public read-only view: $($info.public_view_url) (tunnel -> $($info.public))" }
      return
    }
  }
  Write-Host "The Studio did not start. Last lines of $($LogFile):"
  Get-Content $LogFile -Tail 20
  exit 1
}

function Stop-Studio {
  if (-not (Get-StudioProcess)) { Write-Host "The Studio is not running."; if (Test-Path $PidFile) { Remove-Item $PidFile }; return }
  & (Get-Python) $Server --stop
  if ($LASTEXITCODE) { exit $LASTEXITCODE }
}

function Show-Status {
  $running = Get-StudioProcess
  if ($running) {
    $i = $running.Info
    Write-Host "Studio: running (pid $($i.pid), since $($i.started_at))"
    Write-Host ("  local   {0}  -> {1}" -f $i.local, (Test-Url "$($i.local)api/session"))
    if ($i.remote) { Write-Host ("  tunnel  {0}  -> {1} without an Access token (401 expected)" -f $i.remote, (Test-Url "$($i.remote)api/session" ([uri]$i.public_url).Host)) }
    if ($i.public) {
      $pubHost = if ($i.public_view_url) { ([uri]$i.public_view_url).Host } else { $null }
      Write-Host ("  public  {0}  -> {1} anonymous session (200 expected); a save -> {2} (401 expected)" -f $i.public,
        (Test-Url "$($i.public)api/session" $pubHost), (Test-Url "$($i.public)api/save" $pubHost))
    }
  } else { Write-Host "Studio: not running" }
  $svc = Get-Service Cloudflared -ErrorAction SilentlyContinue
  Write-Host "Cloudflare Tunnel connector (service Cloudflared): $(if ($svc) { $svc.Status } else { 'not installed' })"
  try {
    $cfg = (Invoke-WebRequest -Uri "http://127.0.0.1:20241/config" -UseBasicParsing -TimeoutSec 5).Content | ConvertFrom-Json
    foreach ($r in $cfg.config.ingress) { if ($r.hostname) { Write-Host "  route $($r.hostname) -> $($r.service)" } }
  } catch { Write-Host "  (cloudflared metrics not reachable on 127.0.0.1:20241)" }
  $cfgFile = Join-Path $Root "config\studio_server.json"
  if (Test-Path $cfgFile) {
    $doc = Get-Content $cfgFile -Raw | ConvertFrom-Json
    $url = $doc.public_url
    if ($url) { Write-Host ("Editing {0}  -> {1} without signing in (302 to Cloudflare Access expected)" -f $url, (Test-Url $url)) }
    if ($doc.public -and $doc.public.enabled -and $doc.public.url) {
      Write-Host ("Public view {0}  -> page {1} (200 expected), recording {2} (401 expected)" -f $doc.public.url,
        (Test-Url $doc.public.url), (Test-Url "$($doc.public.url.TrimEnd('/'))/audio/mcc?level=a10&lang=spanish&index=0"))
    }
  }
}

function Register-Startup {
  # Runs as you, only while you are signed in (no stored password, no SYSTEM service), 30 s after sign-in.
  $ps = (Get-Process -Id $PID).Path
  $action = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" start" -WorkingDirectory $Root
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
  $trigger.Delay = "PT30S"
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Starts the Halo Localization Studio (scripts/deploy/studio.ps1 start) when $env:USERNAME signs in." -Force | Out-Null
  Write-Host "Scheduled Task '$TaskName' registered: the Studio starts 30 s after you sign in to Windows."
}

switch ($Command) {
  "start" { Start-Studio }
  "stop" { Stop-Studio }
  "restart" { Stop-Studio; Start-Studio }
  "status" { Show-Status }
  "build" { Invoke-Build }
  "register-startup" { Register-Startup }
  "unregister-startup" {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Scheduled Task '$TaskName' removed (if it existed)."
  }
}
