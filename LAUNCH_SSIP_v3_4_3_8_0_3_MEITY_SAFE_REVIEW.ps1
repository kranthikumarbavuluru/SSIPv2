Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"

Set-Location $ProjectRoot

python -m streamlit run `
  ".\ui\meity_safe_family_review_v3_4_3_8_0_3.py" `
  --server.port 8509 `
  --server.address localhost
