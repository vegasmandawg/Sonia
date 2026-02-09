$ErrorActionPreference = "Stop"
$rcDir = "S:\artifacts\phase3\rc-1"
$out = @()
$out += "=== RC-1 MANIFEST DIRECTORY ==="
$out += "Location: $rcDir"
$out += ""

Get-ChildItem $rcDir -Recurse | ForEach-Object {
    $type = if ($_.PSIsContainer) { "DIR " } else { "FILE" }
    $rel = $_.FullName.Replace("$rcDir\", "")
    if ($_.PSIsContainer) {
        $out += "$type  $rel\"
    } else {
        $size = "{0:N0}" -f $_.Length
        $out += "$type  $rel  ($size bytes)"
    }
}

$out += ""
$totalFiles = @(Get-ChildItem $rcDir -File -Recurse).Count
$totalDirs = @(Get-ChildItem $rcDir -Directory -Recurse).Count
$out += "Total: $totalFiles files, $totalDirs directories"

$out | Out-File -FilePath "S:\artifacts\phase3\rc1-verify.txt" -Encoding UTF8
