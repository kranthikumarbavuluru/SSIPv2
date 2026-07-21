Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"

Set-Location $ProjectRoot

python -m streamlit run `
  ".\ui\meity_family_review_v3_4_3_8_0_2.py" `
  --server.port 8508 `
  --server.address localhost
