Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot ".."
    )
).Path

Set-Location $projectRoot

& python ".\scripts\meity_manual_pilot_finalize_v3_4_2_0_1.py"

if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.2.0.1 finalization failed."
}
