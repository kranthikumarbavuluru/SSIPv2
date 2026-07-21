Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"

Set-Location $ProjectRoot

python -m streamlit run `
  ".\ui\meity_transparent_classification_review_v3_4_3_8_0_7.py" `
  --server.port 8513 `
  --server.address localhost
