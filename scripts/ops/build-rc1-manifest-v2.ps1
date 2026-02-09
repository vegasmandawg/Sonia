$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$rcDir = "S:\artifacts\phase3\rc-1"

# Step 1: Create directory
try {
    if (Test-Path $rcDir) {
        Remove-Item $rcDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $rcDir -Force | Out-Null
    "STEP 1 OK: Created $rcDir" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Encoding UTF8
} catch {
    "STEP 1 FAIL: $_" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Encoding UTF8
    exit 1
}

# Step 2: Copy top-level files
try {
    Copy-Item "S:\artifacts\phase3\BOOT_CONTRACT.md" -Destination "$rcDir\BOOT_CONTRACT.md" -Force
    Copy-Item "S:\artifacts\phase3\gate-status.json" -Destination "$rcDir\gate-status.json" -Force
    Copy-Item "S:\artifacts\phase3\go-no-go-20260208_164811.log" -Destination "$rcDir\go-no-go-20260208_164811.log" -Force
    Copy-Item "S:\artifacts\phase3\go-no-go-summary-20260208_164811.json" -Destination "$rcDir\go-no-go-summary-20260208_164811.json" -Force
    Copy-Item "S:\scripts\testing\phase3-go-no-go.ps1" -Destination "$rcDir\phase3-go-no-go.ps1" -Force
    "STEP 2 OK: Copied top-level files" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
} catch {
    "STEP 2 FAIL: $_" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
    exit 1
}

# Step 3: Copy evidence bundles
try {
    $freezeStamp = "20260208-172235"
    foreach ($gate in @("gate1", "gate2", "gate2b", "gate3")) {
        $src = "S:\artifacts\phase3\gate-results\$gate-$freezeStamp"
        $dst = "$rcDir\evidence\$gate"
        New-Item -ItemType Directory -Path $dst -Force | Out-Null
        Get-ChildItem $src -File | ForEach-Object {
            Copy-Item $_.FullName -Destination $dst -Force
        }
        # Handle subdirectories (gate3 has release-bundle)
        Get-ChildItem $src -Directory | ForEach-Object {
            Copy-Item $_.FullName -Destination $dst -Recurse -Force
        }
        $count = @(Get-ChildItem $dst -File -Recurse).Count
        "STEP 3 OK: evidence\$gate ($count files)" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
    }
} catch {
    "STEP 3 FAIL: $_" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
    exit 1
}

# Step 4: Copy release bundle
try {
    $bundleSrc = "S:\artifacts\phase3\bundle-20260208_164811"
    $bundleDst = "$rcDir\release-bundle"
    New-Item -ItemType Directory -Path $bundleDst -Force | Out-Null
    Get-ChildItem $bundleSrc -File | ForEach-Object {
        Copy-Item $_.FullName -Destination $bundleDst -Force
    }
    Get-ChildItem $bundleSrc -Directory | ForEach-Object {
        Copy-Item $_.FullName -Destination $bundleDst -Recurse -Force
    }
    $count = @(Get-ChildItem $bundleDst -File -Recurse).Count
    "STEP 4 OK: release-bundle ($count files)" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
} catch {
    "STEP 4 FAIL: $_" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
    exit 1
}

# Step 5: Generate SHA256 manifest
try {
    $allFiles = @(Get-ChildItem $rcDir -File -Recurse)
    $hashLines = @()
    foreach ($f in $allFiles) {
        $hash = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
        $rel = $f.FullName.Replace("$rcDir\", "")
        $hashLines += "$hash  $rel"
    }
    $hashLines | Out-File -FilePath "$rcDir\SHA256SUMS.txt" -Encoding UTF8
    "STEP 5 OK: SHA256SUMS.txt ($($allFiles.Count) files hashed)" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
} catch {
    "STEP 5 FAIL: $_" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
    exit 1
}

"BUILD COMPLETE" | Out-File -FilePath "S:\artifacts\phase3\build-rc1-log.txt" -Append -Encoding UTF8
Write-Output "BUILD COMPLETE"
