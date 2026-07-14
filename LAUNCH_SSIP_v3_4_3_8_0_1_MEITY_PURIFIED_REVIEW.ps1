Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"

Set-Location $ProjectRoot

python -m streamlit run `
  ".\ui\meity_purified_review_v3_4_3_8_0_1.py" `
  --server.port 8507 `
  --server.address localhost
