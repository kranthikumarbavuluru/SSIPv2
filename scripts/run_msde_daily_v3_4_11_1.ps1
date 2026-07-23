param(
    [string]$RunDate = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    if ($RunDate) {
        python scripts/run_msde_daily_v3_4_11_1.py --date $RunDate
    } else {
        python scripts/run_msde_daily_v3_4_11_1.py
    }
} finally {
    Pop-Location
}
