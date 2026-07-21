$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python .\scripts\dst_startup_focus_pipeline_v3_4_0_5.py `
  --project-root "$PSScriptRoot" `
  --config .\config\dst_startup_focus_rules_v3_4_0_5.json `
  --deep-search
if ($LASTEXITCODE -ne 0) { throw "Deep search failed." }
& .\VERIFY_v3_4_0_5.ps1
