Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot
$env:PYTHONUNBUFFERED = "1"

& python -u ".\scripts\meity_publication_candidate_preview_v3_4_3_4.py"

if ($LASTEXITCODE -eq 2) {
    throw "MeitY v3.4.3.4 completed safely, but release-readiness validation failed."
}

if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.3.4 publication-candidate build failed."
}
