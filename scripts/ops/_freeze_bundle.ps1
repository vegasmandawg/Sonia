$ErrorActionPreference = "Stop"
$root = "S:\"
if ($root -match '^[A-Za-z]:\\Sonia(\\|$)') { throw "FATAL: forbidden nested Sonia root: $root" }
Set-Location $root

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$bundle = "S:\releases\v3.4.0-audit-closure-$ts"
New-Item -ItemType Directory -Path $bundle -Force | Out-Null

$artifacts = @(
    "S:\reports\audit\FINAL_SCORECARD-20260215-213441.json",
    "S:\reports\audit\FINAL_SUMMARY-20260215-213441.md",
    "S:\reports\audit\FINAL_SCORECARD.md",
    "S:\docs\changelog\CHG-fullbuild-20260215-213441.md",
    "S:\reports\audit\evidence-manifest-20260215-220444.sha256",
    "S:\reports\audit\remediation-log-20260215-213441.md",
    "S:\reports\audit\integration-live-delta-20260215-220444.json",
    "S:\reports\audit\consolidated-preaudit-20260215-154042.json",
    "S:\reports\audit\fullbuild-preflight-20260215-213441.json"
)

foreach ($a in $artifacts) {
    if (Test-Path $a) {
        Copy-Item $a -Destination $bundle -Force
        Write-Host "  Copied: $(Split-Path $a -Leaf)"
    } else {
        Write-Host "  WARN: Not found: $a"
    }
}

# Bundle-local manifest
$manifest = Join-Path $bundle "bundle-manifest-$ts.sha256"
Get-ChildItem $bundle -File -Recurse |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object { "{0}  {1}" -f $_.Hash.ToLower(), (Split-Path $_.Path -Leaf) } |
    Set-Content -Encoding UTF8 $manifest

Write-Host ""
Write-Host "Frozen bundle: $bundle"
Write-Host "Manifest: $manifest"
Write-Host "Files in bundle: $((Get-ChildItem $bundle -File).Count)"
