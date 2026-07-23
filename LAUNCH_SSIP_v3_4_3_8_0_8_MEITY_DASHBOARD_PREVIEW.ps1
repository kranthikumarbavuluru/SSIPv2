Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"

Set-Location $ProjectRoot

python -m streamlit run `
  ".\ui\meity_classification_dashboard_preview_v3_4_3_8_0_8.py" `
  --server.port 8514 `
  --server.address localhost
