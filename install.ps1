# One-line Windows installer. Safe when piped (irm URL | iex) and when run from a checkout.
# Windows PowerShell 5.1 and PowerShell 7. No administrator rights.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
trap {
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
  $PSNativeCommandUseErrorActionPreference = $false
}

$DefaultInstallDir = Join-Path $env:USERPROFILE "autonomous-company"
$DefaultRepoUrl = "https://github.com/lalalaoneplus-dev/autonomous-company.git"
$DefaultZipUrl = "https://github.com/lalalaoneplus-dev/autonomous-company/archive/refs/heads/main.zip"

function Die([string]$Message) {
  [Console]::Error.WriteLine($Message)
  exit 1
}

function Test-Repo([string]$Dir) {
  if (-not $Dir) { return $false }
  $example = Join-Path $Dir ".env.example"
  $api = Join-Path (Join-Path $Dir "apps") "api"
  $web = Join-Path (Join-Path $Dir "apps") "web"
  return ((Test-Path -LiteralPath $example) -and (Test-Path -LiteralPath $api) -and (Test-Path -LiteralPath $web))
}

function Test-SamePath([string]$A, [string]$B) {
  $fa = [System.IO.Path]::GetFullPath($A).TrimEnd('\', '/')
  $fb = [System.IO.Path]::GetFullPath($B).TrimEnd('\', '/')
  return [string]::Equals($fa, $fb, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-ArchiveUrl([string]$RepoUrl, [string]$Fallback) {
  if ($RepoUrl -match '^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$') {
    return ("https://github.com/" + $Matches[1] + "/" + $Matches[2] + "/archive/refs/heads/main.zip")
  }
  return $Fallback
}

function Copy-Tree([string]$Src, [string]$Dest) {
  if (-not (Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Path $Dest | Out-Null
  }
  & robocopy $Src $Dest /E /XD .git .venv node_modules .node .run .next __pycache__ .pytest_cache /XF *.pyc *.log .env /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) {
    Die ("Could not copy sources into " + $Dest)
  }
}

function Sync-Source([string]$Dest) {
  if ($env:REPO_URL) { $url = $env:REPO_URL } else { $url = $DefaultRepoUrl }
  if (-not (Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Path $Dest | Out-Null
  }
  if (Test-Path -LiteralPath $url -PathType Container) {
    if (Test-SamePath $url $Dest) { return }
    Copy-Tree $url $Dest
    return
  }
  $git = Get-Command git -ErrorAction SilentlyContinue
  if ($git) {
    if (Test-Path -LiteralPath (Join-Path $Dest ".git")) {
      & git -C $Dest pull --ff-only
      if ($LASTEXITCODE -ne 0) { Die ("git pull failed in " + $Dest) }
      return
    }
    $children = @(Get-ChildItem -Force -LiteralPath $Dest)
    if ($children.Count -eq 0) {
      & git clone $url $Dest
      if ($LASTEXITCODE -ne 0) { Die ("git clone failed for " + $url) }
      return
    }
    return
  }
  $zipUrl = Get-ArchiveUrl $url $DefaultZipUrl
  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("src-" + [guid]::NewGuid().ToString("n"))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  try {
    $zip = Join-Path $tmp "src.zip"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
    $unpack = Join-Path $tmp "unpack"
    Expand-Archive -LiteralPath $zip -DestinationPath $unpack -Force
    $inner = @(Get-ChildItem -LiteralPath $unpack -Directory)
    if ($inner.Count -lt 1) { Die "Downloaded archive was empty." }
    Copy-Tree $inner[0].FullName $Dest
  } finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force
  }
}

function Ensure-Uv {
  $bin = Join-Path (Join-Path $env:USERPROFILE ".local") "bin"
  $uvExe = Join-Path $bin "uv.exe"
  if (Test-Path -LiteralPath $uvExe) {
    $env:PATH = $bin + ";" + $env:PATH
  }
  if (Get-Command uv -ErrorAction SilentlyContinue) { return }
  irm https://astral.sh/uv/install.ps1 | iex
  if ($env:XDG_BIN_HOME -and (Test-Path -LiteralPath (Join-Path $env:XDG_BIN_HOME "uv.exe"))) {
    $env:PATH = $env:XDG_BIN_HOME + ";" + $env:PATH
  }
  if (Test-Path -LiteralPath $uvExe) {
    $env:PATH = $bin + ";" + $env:PATH
  }
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Die ("uv is required. It installs into " + $bin + ".")
  }
}

function Get-NodeArch {
  $arch = $env:PROCESSOR_ARCHITECTURE
  if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
  switch ($arch) {
    "AMD64" { return "x64" }
    "ARM64" { return "arm64" }
    default { Die ("This installer needs x64 or arm64. Detected " + $arch + ".") }
  }
}

function Get-NodeMajor {
  $raw = & node --version
  if ($LASTEXITCODE -ne 0) { Die "Could not read the Node.js version." }
  if (([string]$raw).Trim() -notmatch '^v([0-9]+)\.') { Die "Could not parse the Node.js version." }
  return [int]$Matches[1]
}

function Ensure-Node([string]$Repo) {
  $bundled = Join-Path $Repo ".node"
  $bundledExe = Join-Path $bundled "node.exe"
  if (Test-Path -LiteralPath $bundledExe) {
    $env:PATH = $bundled + ";" + $env:PATH
  }
  if (Get-Command node -ErrorAction SilentlyContinue) {
    if ((Get-NodeMajor) -ge 20) { return }
  }
  $arch = Get-NodeArch
  $releases = Invoke-RestMethod -Uri "https://nodejs.org/dist/index.json"
  $ver = $null
  foreach ($rel in $releases) {
    if ($rel.lts) { $ver = [string]$rel.version; break }
  }
  if (-not $ver) { Die "Could not resolve the Node.js LTS version from nodejs.org." }
  $url = "https://nodejs.org/dist/" + $ver + "/node-" + $ver + "-win-" + $arch + ".zip"
  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("node-" + [guid]::NewGuid().ToString("n"))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  try {
    $zip = Join-Path $tmp "node.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $unpack = Join-Path $tmp "unpack"
    Expand-Archive -LiteralPath $zip -DestinationPath $unpack -Force
    $inner = @(Get-ChildItem -LiteralPath $unpack -Directory)
    if ($inner.Count -lt 1) { Die "Node.js archive was empty." }
    if (Test-Path -LiteralPath $bundled) { Remove-Item -LiteralPath $bundled -Recurse -Force }
    New-Item -ItemType Directory -Path $bundled | Out-Null
    & robocopy $inner[0].FullName $bundled /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) { Die "Could not unpack Node.js." }
  } finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force
  }
  $env:PATH = $bundled + ";" + $env:PATH
  if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Die "Node.js is required." }
  if ((Get-NodeMajor) -lt 20) { Die "Node.js 20 or newer is required." }
}

function Ensure-Pnpm {
  $pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
  if ($pnpm) {
    $script:PnpmCommand = $pnpm.Source
    $script:PnpmViaCorepack = $false
    return
  }
  $corepack = Get-Command corepack.cmd -ErrorAction SilentlyContinue
  if ($corepack) {
    & $corepack.Source prepare pnpm@latest --activate
    if ($LASTEXITCODE -ne 0) { Die "corepack prepare failed." }
    & $corepack.Source pnpm --version
    if ($LASTEXITCODE -ne 0) { Die "corepack could not run pnpm." }
    $script:PnpmCommand = $corepack.Source
    $script:PnpmViaCorepack = $true
    return
  }
  irm https://get.pnpm.io/install.ps1 | iex
  if (-not $env:LOCALAPPDATA) {
    $env:LOCALAPPDATA = Join-Path (Join-Path $env:USERPROFILE "AppData") "Local"
  }
  $pnpmHome = Join-Path $env:LOCALAPPDATA "pnpm"
  if ($env:PNPM_HOME) { $pnpmHome = $env:PNPM_HOME }
  $env:PNPM_HOME = $pnpmHome
  $env:PATH = $pnpmHome + ";" + (Join-Path $pnpmHome "bin") + ";" + $env:PATH
  $pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
  if (-not $pnpm) { Die "pnpm.cmd is required." }
  $script:PnpmCommand = $pnpm.Source
  $script:PnpmViaCorepack = $false
}

function Write-EnvIfMissing([string]$Repo) {
  $envFile = Join-Path $Repo ".env"
  if (Test-Path -LiteralPath $envFile) { return }
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  $token = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
  $utf8 = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList @($false, $true)
  $source = [System.IO.File]::ReadAllBytes((Join-Path $Repo ".env.example"))
  $offset = 0
  if ($source.Length -ge 3 -and $source[0] -eq 239 -and $source[1] -eq 187 -and $source[2] -eq 191) {
    $offset = 3
  }
  $content = $utf8.GetString($source, $offset, $source.Length - $offset)
  $pattern = '(?m)^OWNER_TOKEN=[^\r\n]*'
  if ([regex]::IsMatch($content, $pattern)) {
    $content = [regex]::Replace($content, $pattern, 'OWNER_TOKEN=' + $token)
  } else {
    if ($content -match '\r\n') { $newline = "`r`n" } else { $newline = "`n" }
    if ($content.Length -gt 0 -and -not $content.EndsWith("`n")) { $content += $newline }
    $content += 'OWNER_TOKEN=' + $token + $newline
  }
  $tempFile = Join-Path $Repo (".env." + [guid]::NewGuid().ToString("n") + ".tmp")
  try {
    [System.IO.File]::WriteAllText($tempFile, $content, $utf8)
    Move-Item -LiteralPath $tempFile -Destination $envFile
  } finally {
    if (Test-Path -LiteralPath $tempFile) { Remove-Item -LiteralPath $tempFile -Force }
  }
}

$scriptPath = $PSCommandPath
if (-not $scriptPath) { $scriptPath = $MyInvocation.MyCommand.Path }
$checkout = ""
if ($scriptPath) {
  $checkout = Split-Path -Parent $scriptPath
  if (-not (Test-Repo $checkout)) { $checkout = "" }
}

if ($checkout -and -not $env:INSTALL_DIR) {
  $RepoDir = $checkout
} elseif (-not $env:INSTALL_DIR -and -not $env:REPO_URL -and (Test-Repo (Get-Location).Path)) {
  $RepoDir = (Get-Location).Path
} else {
  if ($env:INSTALL_DIR) { $RepoDir = $env:INSTALL_DIR } else { $RepoDir = $DefaultInstallDir }
  Sync-Source $RepoDir
}

if (-not (Test-Repo $RepoDir)) { Die ("autonomous-company files were not found in " + $RepoDir) }

Ensure-Uv
$apiDir = Join-Path (Join-Path $RepoDir "apps") "api"
$venv = Join-Path $apiDir ".venv"
$py = Join-Path (Join-Path $venv "Scripts") "python.exe"
if (-not (Test-Path -LiteralPath $py)) {
  & uv venv --python 3.12 $venv
  if ($LASTEXITCODE -ne 0) { Die "uv venv failed." }
}
Ensure-Node $RepoDir
Ensure-Pnpm
Write-EnvIfMissing $RepoDir

& uv sync --python 3.12 --project $apiDir --extra test
if ($LASTEXITCODE -ne 0) { Die "uv sync failed." }
Push-Location $apiDir
try {
  & uv run alembic upgrade head
  if ($LASTEXITCODE -ne 0) { Die "Database migration failed." }
} finally {
  Pop-Location
}
$webDir = Join-Path (Join-Path $RepoDir "apps") "web"
Push-Location $webDir
try {
  if ($PnpmViaCorepack) {
    & $PnpmCommand pnpm install
  } else {
    & $PnpmCommand install
  }
  if ($LASTEXITCODE -ne 0) { Die "pnpm install failed." }
} finally {
  Pop-Location
}

if ($env:WEB_PORT) { $WebPort = [string]$env:WEB_PORT } else { $WebPort = "3000" }

if ($env:NO_START -ne "1") {
  $shell = (Get-Process -Id $PID).Path
  & $shell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $RepoDir "start.ps1")
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
  Write-Host ("Dashboard URL: http://127.0.0.1:" + $WebPort)
  Write-Host ("Start with: " + (Join-Path $RepoDir "start.ps1"))
  Write-Host ("Stop with: " + (Join-Path $RepoDir "stop.ps1"))
  Write-Host ("Owner token file: " + (Join-Path $RepoDir ".env"))
}
exit 0
