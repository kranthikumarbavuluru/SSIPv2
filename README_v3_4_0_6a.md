# SSIP v3.4.0.6a — XML Warning Hotfix

This hotfix fixes the Windows PowerShell `NativeCommandError` caused when
BeautifulSoup emits `XMLParsedAsHTMLWarning` while the sector agent reads an
official XML sitemap/feed.

It replaces only:

- `scripts/sector_verification_agent_v3_4_0_6.py`
- `RUN_SECTOR_VERIFICATION_v3_4_0_6.ps1`

The Python fix suppresses only `XMLParsedAsHTMLWarning`. The runner also checks
the real Python exit code instead of treating harmless stderr warnings as fatal.

Extract into the SSIP project root and rerun the same PowerShell command.
