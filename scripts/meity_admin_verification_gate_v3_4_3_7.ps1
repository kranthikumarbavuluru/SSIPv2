[CmdletBinding()]
param(
    [switch]$Evaluate,
    [switch]$Strict,
    [string]$Decisions = "",
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot
$env:PYTHONUNBUFFERED = "1"

$scriptPath = ".\scripts\meity_admin_verification_gate_v3_4_3_7.py"

Write-Host "Compiling SSIP v3.4.3.7 admin gate..." -ForegroundColor Cyan
& python -m py_compile $scriptPath
if ($LASTEXITCODE -ne 0) {
    throw "Python compilation failed."
}

Write-Host "Running isolated self-test..." -ForegroundColor Cyan
& python -u $scriptPath --self-test
if ($LASTEXITCODE -ne 0) {
    throw "MeitY v3.4.3.7 self-test failed."
}

$arguments = @($scriptPath)
if ($Evaluate) {
    $arguments += "--evaluate"
    if ($Decisions) {
        $arguments += @("--decisions", $Decisions)
    }
}
else {
    $arguments += "--prepare"
}
if ($Strict) {
    $arguments += "--strict"
}
if ($OutputDir) {
    $arguments += @("--output-dir", $OutputDir)
}

Write-Host "Running governed admin-gate workflow..." -ForegroundColor Cyan
& python -u @arguments
$exitCode = $LASTEXITCODE

if ($exitCode -eq 3) {
    throw "Admin gate is waiting for administrator decisions (strict mode)."
}
if ($exitCode -ne 0) {
    throw "MeitY v3.4.3.7 admin gate failed with exit code $exitCode."
}
