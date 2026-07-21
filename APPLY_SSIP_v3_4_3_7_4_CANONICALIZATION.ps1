Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$Branch = "ssip-v3.4.3.7.4-organization-canonicalization"
$Database = Join-Path $ProjectRoot "database\ssip_staging_v1.db"
$Script = Join-Path $ProjectRoot "scripts\organization_canonicalization_v3_4_3_7_4.py"

Set-Location $ProjectRoot
$current = git branch --show-current
if ($current -ne $Branch) {
    throw "Expected branch $Branch but found $current"
}
if (-not (Test-Path $Database)) { throw "Database not found: $Database" }
if (-not (Test-Path $Script)) { throw "Canonicalization script not found: $Script" }

$plan = python $Script --project-root "." --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Canonicalization dry run failed" }

$adminQueueChanges = 0
$stagingChanges = 0
if ($plan.table_counts.PSObject.Properties.Name -contains "admin_review_queue") {
    $adminQueueChanges = $plan.table_counts.admin_review_queue
}
if ($plan.table_counts.PSObject.Properties.Name -contains "scheme_staging") {
    $stagingChanges = $plan.table_counts.scheme_staging
}

Write-Host ""
Write-Host "SSIP v3.4.3.7.4 reviewed database plan"
Write-Host "----------------------------------------------------"
Write-Host "Rows to change:               $($plan.change_count)"
Write-Host "Admin queue rows:             $adminQueueChanges"
Write-Host "Staging rows:                 $stagingChanges"
Write-Host "Master IDs preserved:         $($plan.master_ids_preserved)"
Write-Host "Application fields modified:  $($plan.application_fields_modified)"
Write-Host "Publication fields modified:  $($plan.publication_fields_modified)"
Write-Host "Audit history modified:       $($plan.audit_history_modified)"
Write-Host "Plan signature:               $($plan.plan_signature)"
Write-Host ""

if ($plan.change_count -eq 0) {
    Write-Host "No organization metadata changes are required."
    exit 0
}

$planDir = Join-Path $ProjectRoot "data\governance\v3_4_3_7_4\live"
New-Item -ItemType Directory -Path $planDir -Force | Out-Null
$planPath = Join-Path $planDir "organization_canonicalization_live_plan_v3_4_3_7_4.json"
$plan | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $planPath -Encoding UTF8
Write-Host "Reviewed plan saved to: $planPath"

$phrase = "APPLY $($plan.change_count)"
$confirmation = Read-Host "Type '$phrase' to create a backup and apply this exact plan"
if ($confirmation -ne $phrase) {
    throw "Confirmation did not match. No database change was made."
}

$backupDir = (
    "D:\WebSite\DASHBOARD\Code\SSIP_DB_Backup_v3_4_3_7_4_" +
    (Get-Date -Format "yyyyMMdd_HHmmss")
)
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$backupDb = Join-Path $backupDir "ssip_staging_v1.db"

$env:SSIP_SOURCE_DB = $Database
$env:SSIP_BACKUP_DB = $backupDb
@'
import os
import sqlite3
from pathlib import Path

source = Path(os.environ["SSIP_SOURCE_DB"])
target = Path(os.environ["SSIP_BACKUP_DB"])
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
print(f"Consistent SQLite backup created: {target}")
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "Database backup failed" }
Remove-Item Env:SSIP_SOURCE_DB -ErrorAction SilentlyContinue
Remove-Item Env:SSIP_BACKUP_DB -ErrorAction SilentlyContinue

$result = python $Script --project-root "." --apply --signature $plan.plan_signature --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Canonicalization apply failed" }

$post = python $Script --project-root "." --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Post-apply verification failed" }
if ($post.change_count -ne 0) {
    throw "Post-apply verification still finds $($post.change_count) changes"
}

Write-Host ""
Write-Host "Organization canonicalization applied successfully."
Write-Host "Applied rows:       $($result.applied_change_count)"
Write-Host "Audit run ID:       $($result.run_id)"
Write-Host "Database backup:    $backupDb"
Write-Host "Remaining changes:  $($post.change_count)"
Write-Host "Publication action: No"
Write-Host ""
Write-Host "Restart the Admin workspace on port 8505 to refresh the filters."
