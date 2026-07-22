param(
    [ValidateSet("discover","verify","candidate","publish","full","status","rollback")]
    [string]$Mode = "candidate",
    [switch]$Publish,
    [switch]$DryRun,
    [string]$RunId,
    [int]$MaxPages = 50,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
if ($Publish -and $Mode -eq "candidate") { $Mode = "publish" }
$Arguments = @("scripts\run_msme_agent_v3_4_6_0.py", "--mode", $Mode, "--max-pages", $MaxPages)
if ($DryRun) { $Arguments += "--dry-run" }
if ($RunId) { $Arguments += @("--run-id", $RunId) }
Push-Location $ProjectRoot
try { & $Python @Arguments; exit $LASTEXITCODE }
finally { Pop-Location }
