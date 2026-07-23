$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$summary = ".\data\catalogue_preview\v3_4_0_4\dst_dashboard_integration_summary_v3_4_0_4a.json"
if (-not (Test-Path $summary)) { throw "Integration summary missing. Run RUN_DST_DASHBOARD_INTEGRATION_v3_4_0_4a.ps1 first." }
Get-Content $summary -Raw -Encoding UTF8

python -c "import csv; rows=list(csv.DictReader(open(r'data/catalogue_preview/v3_3_2/catalogue_preview_v3_3_2.csv',encoding='utf-8-sig'))); dst=[r for r in rows if (r.get('source') or '').strip().upper()=='DST']; print({'all_rows':len(rows),'dst_rows':len(dst),'unique_dst_ids':len(set(r.get('master_id','') for r in dst)),'schemes':sum(1 for r in dst if (r.get('scheme_type') or '').strip().lower()=='scheme'),'programmes':sum(1 for r in dst if (r.get('scheme_type') or '').strip().lower()=='programme')})"
