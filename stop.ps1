# Stop the API and dashboard this install started. Never signals any other pid.
$ErrorActionPreference = "Stop"
trap {
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}

if ($PSScriptRoot) {
  $Root = $PSScriptRoot
} else {
  $Root = (Get-Location).Path
}

function Get-TreeIds([int]$ProcessId) {
  $pending = New-Object System.Collections.Generic.Queue[int]
  $ordered = New-Object System.Collections.Generic.List[int]
  $pending.Enqueue($ProcessId)
  while ($pending.Count -gt 0) {
    $cur = $pending.Dequeue()
    $ordered.Add($cur)
    $kids = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId=" + $cur))
    foreach ($kid in $kids) {
      $pending.Enqueue([int]$kid.ProcessId)
    }
  }
  foreach ($item in $ordered) {
    Write-Output $item
  }
}

function Test-OurProcess([int]$ProcessId, [string]$Ticks, [string]$InstallRoot) {
  $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if (-not $proc) { return $false }
  $actual = $proc.StartTime.ToUniversalTime().Ticks.ToString()
  if ($actual -ne $Ticks) { return $false }
  $cim = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $ProcessId)
  if (-not $cim -or -not $cim.CommandLine) {
    throw ("Could not verify process " + $ProcessId + ".")
  }
  $cmd = [string]$cim.CommandLine
  if ($cmd.IndexOf($InstallRoot, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
    return $false
  }
  return $true
}

function Stop-Recorded([string]$PidFile, [string]$InstallRoot) {
  if (-not (Test-Path -LiteralPath $PidFile)) { return }
  $lines = @(Get-Content -LiteralPath $PidFile)
  $pidText = ""
  $ticks = ""
  if ($lines.Count -ge 1) { $pidText = ([string]$lines[0]).Trim() }
  if ($lines.Count -ge 2) { $ticks = ([string]$lines[1]).Trim() }
  $procId = 0
  $parsed = [int]::TryParse($pidText, [ref]$procId)
  if (-not $parsed) {
    Remove-Item -LiteralPath $PidFile -Force
    return
  }
  $alive = Get-Process -Id $procId -ErrorAction SilentlyContinue
  if (-not $alive) {
    Remove-Item -LiteralPath $PidFile -Force
    return
  }
  if (-not (Test-OurProcess $procId $ticks $InstallRoot)) {
    Remove-Item -LiteralPath $PidFile -Force
    return
  }
  $ids = @(Get-TreeIds $procId)
  [array]::Reverse($ids)
  foreach ($id in $ids) {
    Stop-Process -Id $id -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds 400
  foreach ($id in $ids) {
    $still = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($still) {
      Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
  }
  Start-Sleep -Milliseconds 200
  foreach ($id in $ids) {
    if (Get-Process -Id $id -ErrorAction SilentlyContinue) {
      throw ("Could not stop process " + $id + ".")
    }
  }
  Remove-Item -LiteralPath $PidFile -Force
}

$runDir = Join-Path $Root ".run"
Stop-Recorded (Join-Path $runDir "api.pid") $Root
Stop-Recorded (Join-Path $runDir "web.pid") $Root
exit 0
