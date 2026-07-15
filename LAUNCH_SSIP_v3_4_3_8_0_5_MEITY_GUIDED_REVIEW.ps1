Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"

Set-Location $ProjectRoot

python -m streamlit run `
  ".\ui\meity_guided_review_v3_4_3_8_0_5.py" `
  --server.port 8511 `
  --server.address localhost
