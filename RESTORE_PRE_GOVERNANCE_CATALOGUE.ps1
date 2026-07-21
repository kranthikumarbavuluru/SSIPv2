$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "SSIP Emergency Catalogue Recovery" -ForegroundColor Cyan
Write-Host "Project root: $PSScriptRoot" -ForegroundColor DarkGray

$active = Join-Path $PSScriptRoot "data\catalogue_preview\v3_3_2\catalogue_preview_v3_3_2.csv"
$manifestPath = Join-Path $PSScriptRoot "data\governance\current_manifest.json"

if (-not (Test-Path $active)) {
    throw "Active catalogue not found: $active"
}

function Get-CsvRowCount {
    param([Parameter(Mandatory=$true)][string]$Path)
    try {
        return @((Import-Csv -LiteralPath $Path)).Count
    }
    catch {
        return -1
    }
}

$currentCount = Get-CsvRowCount -Path $active
Write-Host "Current active catalogue rows: $currentCount" -ForegroundColor Yellow

# Preserve the current filtered catalogue before restoring.
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$emergencyDir = Join-Path $PSScriptRoot "backups\emergency_recovery\$stamp"
New-Item -ItemType Directory -Force -Path $emergencyDir | Out-Null
Copy-Item -LiteralPath $active `
    -Destination (Join-Path $emergencyDir "filtered_catalogue_before_restore.csv") `
    -Force

Write-Host "Saved current filtered catalogue to:" -ForegroundColor DarkGray
Write-Host "  $emergencyDir" -ForegroundColor DarkGray

$candidates = @()

# First preference: backup associated with the current governance manifest.
if (Test-Path $manifestPath) {
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($manifest.run_id) {
            $manifestBackup = Join-Path $PSScriptRoot `
                ("backups\governance\" + $manifest.run_id + "\catalogue_preview_v3_3_2.csv")
            if (Test-Path $manifestBackup) {
                $candidates += Get-Item -LiteralPath $manifestBackup
            }
        }
    }
    catch {
        Write-Host "Warning: could not read governance manifest." -ForegroundColor Yellow
    }
}

# Search all known backup locations.
$searchRoots = @(
    (Join-Path $PSScriptRoot "backups\governance"),
    (Join-Path $PSScriptRoot "backups\agent_platform"),
    (Join-Path $PSScriptRoot "backups\sector_verification"),
    (Join-Path $PSScriptRoot "backups")
)

foreach ($searchRoot in $searchRoots) {
    if (Test-Path $searchRoot) {
        $candidates += Get-ChildItem `
            -LiteralPath $searchRoot `
            -Recurse `
            -File `
            -Filter "catalogue_preview_v3_3_2.csv" `
            -ErrorAction SilentlyContinue
    }
}

$candidates = $candidates |
    Sort-Object FullName -Unique |
    ForEach-Object {
        [PSCustomObject]@{
            Path = $_.FullName
            Rows = Get-CsvRowCount -Path $_.FullName
            LastWriteTime = $_.LastWriteTime
        }
    } |
    Where-Object { $_.Rows -gt $currentCount } |
    Sort-Object `
        @{Expression="LastWriteTime";Descending=$true}, `
        @{Expression="Rows";Descending=$true}

if (-not $candidates -or @($candidates).Count -eq 0) {
    Write-Host "`nNo larger catalogue backup was found automatically." -ForegroundColor Red
    Write-Host "Available catalogue-like backups:" -ForegroundColor Yellow
    Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "backups") `
        -Recurse -File -Filter "*.csv" -ErrorAction SilentlyContinue |
        Select-Object FullName, LastWriteTime |
        Format-Table -AutoSize
    throw "Automatic recovery stopped without modifying the active catalogue."
}

Write-Host "`nRecovery candidates:" -ForegroundColor Green
$candidates |
    Select-Object Rows, LastWriteTime, Path |
    Format-Table -AutoSize -Wrap

$selected = $candidates | Select-Object -First 1
Write-Host "`nSelected backup:" -ForegroundColor Green
Write-Host "  Rows: $($selected.Rows)"
Write-Host "  Path: $($selected.Path)"

Copy-Item -LiteralPath $selected.Path -Destination $active -Force

$restoredCount = Get-CsvRowCount -Path $active
if ($restoredCount -ne $selected.Rows -or $restoredCount -le $currentCount) {
    throw "Restore verification failed. Expected $($selected.Rows) rows, found $restoredCount."
}

Write-Host "`nCatalogue restored successfully." -ForegroundColor Green
Write-Host "Restored rows: $restoredCount" -ForegroundColor Green

# Disable SSIP nightly tasks to prevent another overwrite.
Write-Host "`nDisabling SSIP nightly tasks during recovery..." -ForegroundColor Yellow
try {
    $tasks = Get-ScheduledTask -ErrorAction SilentlyContinue |
        Where-Object { $_.TaskName -like "SSIP Nightly*" }

    foreach ($task in $tasks) {
        try {
            Disable-ScheduledTask -TaskName $task.TaskName -ErrorAction Stop | Out-Null
            Write-Host "Disabled task: $($task.TaskName)" -ForegroundColor Green
        }
        catch {
            Write-Host "Could not disable task '$($task.TaskName)'. Run PowerShell as Administrator." `
                -ForegroundColor Yellow
        }
    }
}
catch {
    Write-Host "Could not inspect scheduled tasks. Disable SSIP nightly tasks manually." `
        -ForegroundColor Yellow
}

# Clear cache and restart the actual dashboard.
Write-Host "`nRestarting dashboard..." -ForegroundColor Yellow
$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & python -m streamlit cache clear
}
finally {
    $ErrorActionPreference = $previousPreference
}

$port = 8502
Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        try {
            Stop-Process -Id $_.OwningProcess -Force -ErrorAction Stop
        }
        catch {}
    }

Start-Sleep -Seconds 2

$dashboardApp = Join-Path $PSScriptRoot "apps\public_dashboard_app_v2_9.py"
if (Test-Path $dashboardApp) {
    Start-Process `
        -FilePath "python" `
        -ArgumentList @(
            "-m", "streamlit", "run",
            ".\apps\public_dashboard_app_v2_9.py",
            "--server.address", "127.0.0.1",
            "--server.port", "8502"
        ) `
        -WorkingDirectory $PSScriptRoot

    Write-Host "Dashboard restarted: http://localhost:8502" -ForegroundColor Green
}
else {
    Write-Host "Dashboard app not found; catalogue restoration is still complete." `
        -ForegroundColor Yellow
}

Write-Host "`nIMPORTANT: Do not rerun v3.4.2.0/v3.4.2.1 governance agents." `
    -ForegroundColor Red
