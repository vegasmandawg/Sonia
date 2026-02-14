<#
.SYNOPSIS
    Lock immutable baseline for v2.10.0 GA release.
#>
$ErrorActionPreference = "Stop"
$ver = "v2.10.0"
$root = "S:\releases\$ver"
$imm  = Join-Path $root "immutable"
$hashFile = Join-Path $imm "immutable-hashes.txt"

New-Item -ItemType Directory -Force -Path $imm | Out-Null

# Required artifacts from GA run
$required = @(
    "$root\gate-report.json",
    "$root\release-manifest.json",
    "$root\env\conda-list.txt",
    "$root\env\pip-freeze.txt"
)

foreach ($f in $required) {
    if (!(Test-Path $f)) { throw "Missing required artifact: $f" }
}

# Snapshot key system files into immutable bundle
$toArchive = @(
    "S:\scripts\promotion-gate-v210.ps1",
    "S:\scripts\ops\prune-empty-sessions.ps1",
    "S:\tests\integration\test_v210_mcp_hardening.py",
    "S:\tests\integration\test_v210_vlm_robustness.py",
    "S:\tests\integration\test_v210_chunker_edge_cases.py",
    "S:\config\sonia-config.json"
)

foreach ($f in $toArchive) {
    if (Test-Path $f) {
        Copy-Item -Path $f -Destination (Join-Path $imm (Split-Path $f -Leaf)) -Force
    }
}

# Hash everything in immutable folder + core release artifacts
$hashTargets = @()
$hashTargets += Get-ChildItem $imm -File -Recurse | Select-Object -ExpandProperty FullName
$hashTargets += $required

$lines = foreach ($f in ($hashTargets | Sort-Object -Unique)) {
    $h = Get-FileHash -Algorithm SHA256 -Path $f
    "{0}  {1}" -f $h.Hash, $f
}
$lines | Set-Content -Path $hashFile -Encoding UTF8

Write-Host "Immutable baseline complete: $imm"
Write-Host "Hash ledger: $hashFile"
