Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

python -m pip install requests beautifulsoup4 playwright
python -m playwright install chromium

Write-Host ""
Write-Host "MeitY discovery expansion dependencies: INSTALLED"
