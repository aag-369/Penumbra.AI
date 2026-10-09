<#
  PENUMBRA.AI - one-click local launcher for Windows.

  Double-click start.bat in the project folder (or start-website-only.bat).
  The first run installs everything and takes a few minutes; later runs start
  in seconds. Two windows open - the API and the website - and closing them
  stops the servers.

  Kept to plain ASCII on purpose: Windows PowerShell 5.1 reads scripts without
  a byte-order mark as ANSI, and a stray typographic dash would break parsing.
#>
param([switch]$WebsiteOnly)

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$Frontend = Join-Path $Root 'frontend'
$Backend = Join-Path $Root 'backend'
$SiteUrl = 'http://localhost:3000'
$ApiUrl = 'http://localhost:8000'

function Say([string]$Message, [string]$Color = 'Gray') { Write-Host $Message -ForegroundColor $Color }
function Step([string]$Message) { Write-Host ''; Write-Host "==> $Message" -ForegroundColor Cyan }

function Stop-WithMessage([string]$Message) {
  Write-Host ''
  Write-Host "  $Message" -ForegroundColor Red
  Write-Host ''
  Read-Host 'Press Enter to close'
  exit 1
}

function Test-Url([string]$Url) {
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    return ($response.StatusCode -lt 500)
  } catch {
    return $false
  }
}

function Wait-ForUrl([string]$Url, [int]$Seconds) {
  for ($i = 0; $i -lt $Seconds; $i++) {
    if (Test-Url $Url) { return $true }
    Start-Sleep -Seconds 1
  }
  return $false
}

# TenSEAL 0.3.17 publishes Windows wheels for Python 3.11 to 3.14 only.
function Find-Python {
  $candidates = @()
  if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($version in @('3.13', '3.12', '3.11', '3.14')) {
      $candidates += , @('py', "-$version")
    }
  }
  foreach ($name in @('python', 'python3')) {
    if (Get-Command $name -ErrorAction SilentlyContinue) { $candidates += , @($name) }
  }
  foreach ($candidate in $candidates) {
    $exe = $candidate[0]
    $pyArgs = @($candidate | Select-Object -Skip 1)
    $found = & $exe @pyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $found) {
      $parts = "$found".Trim().Split('.')
      $major = [int]$parts[0]
      $minor = [int]$parts[1]
      if ($major -eq 3 -and $minor -ge 11 -and $minor -le 14) {
        return @{ Exe = $exe; Args = $pyArgs; Label = "Python $major.$minor" }
      }
    }
  }
  return $null
}

function New-JwtSecret {
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_').TrimEnd('=')
}

Write-Host ''
Write-Host '  PENUMBRA.AI  -  local launcher' -ForegroundColor Magenta
Write-Host '  Your portfolio. Encrypted. Always.' -ForegroundColor DarkGray

# -- 1. Node.js -----------------------------------------------------------------
Step 'Checking Node.js'
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Stop-WithMessage 'Node.js is not installed. Install the LTS version from https://nodejs.org, then run start.bat again.'
}
$nodeVersion = "$(& node --version)".Trim().TrimStart('v')
if ([int]($nodeVersion.Split('.')[0]) -lt 18) {
  Stop-WithMessage "Node.js $nodeVersion is too old. Install Node 20 LTS from https://nodejs.org, then run start.bat again."
}
Say "  Node.js $nodeVersion" 'Green'

# -- 2. Website dependencies ----------------------------------------------------
Step 'Preparing the website'
$lockHash = (Get-FileHash (Join-Path $Frontend 'package-lock.json') -Algorithm SHA256).Hash
$lockStamp = Join-Path $Frontend 'node_modules\.penumbra-lock'
$installed = (Test-Path $lockStamp) -and ((Get-Content $lockStamp -Raw).Trim() -eq $lockHash)
if (-not $installed) {
  Say '  Installing website dependencies (about a minute the first time)...'
  Push-Location $Frontend
  & npm ci --no-audit --no-fund
  $npmExit = $LASTEXITCODE
  Pop-Location
  if ($npmExit -ne 0) {
    Stop-WithMessage 'Installing the website dependencies failed. Check your internet connection and run start.bat again.'
  }
  Set-Content -Path $lockStamp -Value $lockHash
}
Say '  Website dependencies ready.' 'Green'

# -- 3. Backend -----------------------------------------------------------------
$apiState = 'skipped'
if ($WebsiteOnly) {
  Step 'Skipping the backend (website-only mode)'
  Say '  The site runs standalone: encryption is still real, storage stays in your browser.'
} elseif (Test-Url "$ApiUrl/health") {
  Step 'Backend'
  Say '  An API is already answering on port 8000 - using it.' 'Green'
  $apiState = 'running'
} else {
  Step 'Preparing the backend (Python API)'
  $python = Find-Python
  if (-not $python) {
    Say '  Python 3.11 - 3.14 was not found, so the API will not start.' 'Yellow'
    Say '  The website still works in demo mode. To add the API, install Python 3.12 from' 'Yellow'
    Say '  https://www.python.org/downloads/ (tick "Add python.exe to PATH") and run start.bat again.' 'Yellow'
  } else {
    Say "  Using $($python.Label)"
    $venv = Join-Path $Backend '.venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
      Say '  Creating a virtual environment in backend\.venv ...'
      $venvArgs = @($python.Args) + @('-m', 'venv', $venv)
      & $python.Exe @venvArgs
    }
    if (-not (Test-Path $venvPython)) {
      Say '  Could not create the virtual environment; continuing without the API.' 'Yellow'
    } else {
      $reqFile = Join-Path $Backend 'requirements.txt'
      $reqHash = (Get-FileHash $reqFile -Algorithm SHA256).Hash
      $reqStamp = Join-Path $venv '.penumbra-requirements'
      $reqReady = (Test-Path $reqStamp) -and ((Get-Content $reqStamp -Raw).Trim() -eq $reqHash)
      if (-not $reqReady) {
        Say '  Installing backend packages - TenSEAL, NumPy, SciPy, FastAPI.'
        Say '  The first run takes a few minutes; later runs skip this.'
        & $venvPython -m pip install --upgrade pip --quiet --disable-pip-version-check
        & $venvPython -m pip install -r $reqFile --disable-pip-version-check
        if ($LASTEXITCODE -eq 0) {
          Set-Content -Path $reqStamp -Value $reqHash
          $reqReady = $true
        } else {
          Say '  Installing the backend packages failed; continuing without the API.' 'Yellow'
        }
      }

      if ($reqReady) {
        $envFile = Join-Path $Backend '.env'
        if (-not (Test-Path $envFile)) {
          $secret = New-JwtSecret
          $lines = Get-Content (Join-Path $Backend '.env.example') | ForEach-Object {
            if ($_ -match '^JWT_SECRET=') { "JWT_SECRET=$secret" } else { $_ }
          }
          # UTF-8 without a byte-order mark, which python-dotenv reads cleanly.
          [System.IO.File]::WriteAllLines($envFile, [string[]]$lines)
          Say '  Created backend\.env with a fresh random JWT secret.'
        }

        Say '  Starting the API in a new window...'
        Start-Process -FilePath 'cmd.exe' -WorkingDirectory $Backend -ArgumentList '/k title PENUMBRA API - close this window to stop && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000'
        if (Wait-ForUrl "$ApiUrl/health" 90) {
          Say "  API is up at $ApiUrl  (docs: $ApiUrl/docs)" 'Green'
          $apiState = 'running'
        } else {
          Say '  The API did not answer within 90 seconds - check the "PENUMBRA API" window.' 'Yellow'
          $apiState = 'failed'
        }
      }
    }
  }
}

# -- 4. Website -----------------------------------------------------------------
Step 'Starting the website'
if (Test-Url $SiteUrl) {
  Say "  Something is already serving $SiteUrl - opening it." 'Green'
} else {
  Start-Process -FilePath 'cmd.exe' -WorkingDirectory $Frontend -ArgumentList '/k title PENUMBRA website - close this window to stop && npm run dev'
  if (-not (Wait-ForUrl $SiteUrl 90)) {
    Stop-WithMessage 'The website did not start within 90 seconds - check the "PENUMBRA website" window for errors.'
  }
}
Start-Process $SiteUrl

Write-Host ''
Write-Host '  ------------------------------------------------------------' -ForegroundColor DarkGray
Write-Host "  Website   $SiteUrl" -ForegroundColor Green
if ($apiState -eq 'running') {
  Write-Host "  API       $ApiUrl/docs   (status on the site: Online)" -ForegroundColor Green
} else {
  Write-Host '  API       not running    (status on the site: Demo Mode)' -ForegroundColor Yellow
}
Write-Host '  To stop:  close the "PENUMBRA" windows.' -ForegroundColor Gray
Write-Host '  ------------------------------------------------------------' -ForegroundColor DarkGray
Write-Host ''
Read-Host 'Press Enter to close this window (the servers keep running)'
