$ErrorActionPreference = "Stop"
$rel = "S:\releases\v3.1.0-rc1"
New-Item -ItemType Directory -Force -Path $rel | Out-Null

# Gate report
Copy-Item "S:\reports\gate-v31\gate-report.json" $rel -Force

# Chaos artifacts
$chaosDir = "S:\reports\chaos-v31"
if (Test-Path $chaosDir) {
    Get-ChildItem "$chaosDir\*.json" | Copy-Item -Destination $rel -Force
}

# Hardening test transcripts
Get-ChildItem "S:\reports\gate-v31\hardening_*.txt" -ErrorAction SilentlyContinue | Copy-Item -Destination $rel -Force

# Docs
Copy-Item "S:\docs\V3_1_H1_HARDENING_PLAN.md" $rel -Force
Copy-Item "S:\docs\V3_1_GATE_SPEC.md" $rel -Force

# Commit manifest
Set-Location S:\
$sha = git rev-parse HEAD
$sha | Set-Content "$rel\COMMIT.txt" -Encoding utf8
$branch = git rev-parse --abbrev-ref HEAD
$branch | Set-Content "$rel\BRANCH.txt" -Encoding utf8
git status --porcelain | Set-Content "$rel\WORKTREE_STATUS.txt" -Encoding utf8
git log --oneline -10 | Set-Content "$rel\RECENT_COMMITS.txt" -Encoding utf8

# SHA256 manifest
Get-ChildItem $rel -File -Recurse |
  Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
  Get-FileHash -Algorithm SHA256 |
  Sort-Object Path |
  ForEach-Object { "$($_.Hash)  $($_.Path)" } |
  Set-Content "$rel\SHA256SUMS.txt" -Encoding utf8

Write-Host "Bundle assembled at: $rel"
Write-Host "Commit: $sha"
Write-Host "Branch: $branch"
Get-ChildItem $rel -File | Select-Object Name, Length | Format-Table -AutoSize
