# Builds the Windows distribution: dist\QuranReadingClub\QuranReadingClub.exe (+ zip).
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1 [-SkipTests]
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

# Tools: Python 3.11+ and Node 20+ (user installs under %LOCALAPPDATA%\Programs are picked up too).
$extra = @("$env:LOCALAPPDATA\Programs\nodejs", "$env:LOCALAPPDATA\Programs\Python\Python313")
$env:Path = ($extra -join ";") + ";" + $env:Path
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "Python not found. Install Python 3.11+ from python.org." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Node.js not found. Install Node 20+ from nodejs.org." }

Step "Python environment"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $python -m venv .venv; Check "venv" }
$py = Join-Path $root ".venv\Scripts\python.exe"
& $py -m pip install -q --upgrade pip; Check "pip"
& $py -m pip install -q -r backend\requirements-dev.txt; Check "pip install"

Step "Web interface"
Push-Location frontend
npm ci --no-fund --no-audit; Check "npm ci"
npm run build; Check "frontend build"
if (-not $SkipTests) { npx vitest run; Check "frontend tests" }
Pop-Location

if (-not $SkipTests) {
    Step "Backend tests"
    Push-Location backend
    & $py -m pytest -q; Check "backend tests"
    Pop-Location
}

Step "Windows executable"
if (-not (Test-Path packaging\app.ico)) { & $py packaging\make_icon.py; Check "icon" }
& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\QuranReadingClub.spec; Check "PyInstaller"

$out = Join-Path $root "dist\QuranReadingClub"
Copy-Item README.md, LICENSE, THIRD-PARTY-NOTICES.md, docs\*.md $out -Force
New-Item -ItemType Directory -Force (Join-Path $out "data") | Out-Null

Step "Zip"
$zip = Join-Path $root "dist\QuranReadingClub-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $out -DestinationPath $zip
Write-Host "`nDone: $out\QuranReadingClub.exe" -ForegroundColor Green
Write-Host "      $zip" -ForegroundColor Green
