# SSIP v3.4.0.6c — PowerShell Runner Hotfix

This drop-in hotfix replaces only `RUN_SECTOR_REPAIR_v3_4_0_6b.ps1`.

It fixes the Windows PowerShell parser failure caused by `$LASTEXITCODE:` inside a double-quoted string. It also passes Python arguments as arrays and judges native command success by exit code.

Extract into the SSIP root and replace the existing runner.
