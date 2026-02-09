# Extract Python 3.10.19 source
param(
    [string]$SourceFile = "C:\Users\iamth\Downloads\Python-3.10.19.tar.xz",
    [string]$ExtractTo = "C:\temp\python-src"
)

$ErrorActionPreference = "Stop"

Write-Host "Extracting Python source..."
Write-Host "From: $SourceFile"
Write-Host "To: $ExtractTo"

# Create target directory
if (Test-Path $ExtractTo) {
    Remove-Item $ExtractTo -Recurse -Force
}
New-Item -ItemType Directory -Path $ExtractTo -Force | Out-Null

# Try with built-in tar command (Windows 10/11)
Write-Host ""
Write-Host "Attempting extraction with tar command..."
try {
    & tar -xf $SourceFile -C $ExtractTo
    Write-Host "SUCCESS: Extraction complete"
    
    # Verify
    $files = Get-ChildItem $ExtractTo | Measure-Object
    Write-Host "Files extracted: $($files.Count)"
    
    Get-ChildItem $ExtractTo -Directory | ForEach-Object {
        Write-Host "  Dir: $($_.Name)"
    }
    
    exit 0
} catch {
    Write-Host "FAILED: $_"
    exit 1
}
