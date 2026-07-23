param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Output "MISSING"
    exit 0
}

$resolvedRoot = (
    Resolve-Path -LiteralPath $Path
).Path

$hashLines = @(
    Get-ChildItem `
      -LiteralPath $resolvedRoot `
      -Recurse `
      -File |
    Sort-Object FullName |
    ForEach-Object {
        $relativePath = $_.FullName.Substring(
            $resolvedRoot.Length
        ).TrimStart("\")

        $fileHash = (
            Get-FileHash `
              -LiteralPath $_.FullName `
              -Algorithm SHA256
        ).Hash.ToLower()

        "$relativePath`t$fileHash"
    }
)

$temporaryFile = [System.IO.Path]::GetTempFileName()

try {
    [System.IO.File]::WriteAllLines(
        $temporaryFile,
        $hashLines,
        [System.Text.UTF8Encoding]::new($false)
    )

    $treeHash = (
        Get-FileHash `
          -LiteralPath $temporaryFile `
          -Algorithm SHA256
    ).Hash.ToLower()

    Write-Output $treeHash
}
finally {
    Remove-Item `
      -LiteralPath $temporaryFile `
      -Force `
      -ErrorAction SilentlyContinue
}
