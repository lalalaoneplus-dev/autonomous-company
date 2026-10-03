# Start the local API and dashboard in the background.
# Restarts only processes recorded in .run\*.pid. A port held by anything else stops the launch.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
  $PSNativeCommandUseErrorActionPreference = $false
}

if ($PSScriptRoot) {
  $Root = $PSScriptRoot
} else {
  $Root = (Get-Location).Path
}

function Die([string]$Message) {
  [Console]::Error.WriteLine($Message)
  exit 1
}

if ($env:API_PORT) { $ApiPort = [string]$env:API_PORT } else { $ApiPort = "8000" }
if ($env:WEB_PORT) { $WebPort = [string]$env:WEB_PORT } else { $WebPort = "3000" }
if ($ApiPort -notmatch '^[0-9]+$') { Die "API_PORT must be a number." }
if ($WebPort -notmatch '^[0-9]+$') { Die "WEB_PORT must be a number." }
$ApiUrl = "http://127.0.0.1:" + $ApiPort
$WebUrl = "http://127.0.0.1:" + $WebPort

$bundled = Join-Path $Root ".node"
if (Test-Path -LiteralPath (Join-Path $bundled "node.exe")) {
  $env:PATH = $bundled + ";" + $env:PATH
}
$localBin = Join-Path (Join-Path $env:USERPROFILE ".local") "bin"
if (Test-Path -LiteralPath $localBin) {
  $env:PATH = $localBin + ";" + $env:PATH
}
if (-not $env:PNPM_HOME) {
  $env:PNPM_HOME = Join-Path $env:LOCALAPPDATA "pnpm"
}
$env:PATH = $env:PNPM_HOME + ";" + (Join-Path $env:PNPM_HOME "bin") + ";" + $env:PATH

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Die "uv is required. Re-run install.ps1." }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { Die "pnpm is required. Re-run install.ps1." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Die "Node.js is required. Re-run install.ps1." }
$envFile = Join-Path $Root ".env"
if (-not (Test-Path -LiteralPath $envFile)) { Die ("Missing " + $envFile + ". Re-run install.ps1.") }
$apiDir = Join-Path (Join-Path $Root "apps") "api"
$py = Join-Path (Join-Path (Join-Path $apiDir ".venv") "Scripts") "python.exe"
if (-not (Test-Path -LiteralPath $py)) { Die "Python 3.12 virtualenv is missing. Re-run install.ps1." }

function Test-PortListen([string]$Port) {
  $pattern = ":" + $Port + "\s"
  $lines = netstat -ano | Select-String -Pattern $pattern
  if (-not $lines) { return $false }
  foreach ($line in @($lines)) {
    if ($line -and ($line.Line -match "LISTENING")) { return $true }
  }
  return $false
}

function Wait-Http([string]$Url) {
  $i = 0
  while ($i -lt 180) {
    try {
      $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
      if ([int]$resp.StatusCode -eq 200) { return }
    } catch {
    }
    Start-Sleep -Seconds 1
    $i++
  }
  Die ("Timed out waiting for " + $Url + " (see " + (Join-Path $Root "api.log") + " and " + (Join-Path $Root "web.log") + ")")
}

try {
  & (Join-Path $Root "stop.ps1")
} catch {
  Die $_.Exception.Message
}
Start-Sleep -Milliseconds 300
if (Test-PortListen $ApiPort) { Start-Sleep -Milliseconds 500 }
if (Test-PortListen $ApiPort) {
  Die ("Port " + $ApiPort + " is in use. Choose another with API_PORT=<port>.")
}
if (Test-PortListen $WebPort) { Start-Sleep -Milliseconds 500 }
if (Test-PortListen $WebPort) {
  Die ("Port " + $WebPort + " is in use. Choose another with WEB_PORT=<port>.")
}

$runDir = Join-Path $Root ".run"
if (-not (Test-Path -LiteralPath $runDir)) {
  New-Item -ItemType Directory -Path $runDir | Out-Null
}
$utf8 = New-Object System.Text.UTF8Encoding $false

function Write-PidFile([string]$Path, $Process) {
  $ticks = $Process.StartTime.ToUniversalTime().Ticks
  [System.IO.File]::WriteAllText($Path, ([string]$Process.Id) + "`n" + ([string]$ticks) + "`n", $utf8)
}

$apiProc = Start-Process -FilePath $py -ArgumentList @(
  "-m", "uvicorn", "app.main:app", "--reload", "--port", $ApiPort
) -WorkingDirectory $apiDir -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $Root "api.log") `
  -RedirectStandardError (Join-Path $Root "api.err.log") -PassThru
Write-PidFile (Join-Path $runDir "api.pid") $apiProc

$webDir = Join-Path (Join-Path $Root "apps") "web"
$nextJs = Join-Path $webDir "node_modules\next\dist\bin\next"
if (-not (Test-Path -LiteralPath $nextJs)) {
  Die "next is required. Re-run install.ps1."
}
$node = (Get-Command node).Source
$env:BROWSER = "none"
$webProc = Start-Process -FilePath $node -ArgumentList @($nextJs, "dev", "-p", $WebPort) -WorkingDirectory $webDir -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $Root "web.log") `
  -RedirectStandardError (Join-Path $Root "web.err.log") -PassThru
Write-PidFile (Join-Path $runDir "web.pid") $webProc

Wait-Http ($ApiUrl + "/docs")
Wait-Http ($WebUrl + "/")

if ($env:NO_OPEN -ne "1") {
  Start-Process $WebUrl | Out-Null
}

Write-Host ("Dashboard: " + $WebUrl)
Write-Host ("API docs: " + $ApiUrl + "/docs")
Write-Host ("Owner token file: " + $envFile)
Write-Host ("Stop with: " + (Join-Path $Root "stop.ps1"))
