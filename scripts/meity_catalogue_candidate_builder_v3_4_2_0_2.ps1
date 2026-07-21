Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

& python ".\scripts\meity_catalogue_candidate_builder_v3_4_2_0_2.py"
if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.2.0.2 candidate build failed."
}
