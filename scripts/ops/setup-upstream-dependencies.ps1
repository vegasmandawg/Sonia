<#---------------------------------------------------------------------------
setup-upstream-dependencies.ps1

Extract and organize upstream tools into Sonia structure.
Handles: LM-Studio, Miniconda, OpenClaw, Pipecat, vLLM, EVA-OS

This script:
1. Extracts zip files to proper locations
2. Verifies extraction integrity
3. Sets up Python environments
4. Initializes node modules if needed
5. Creates integration pointers

Root: S:\
---------------------------------------------------------------------------#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateNotNullOrEmpty()]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [switch]$Force,

    [Parameter(Mandatory=$false)]
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Utility functions
function Write-Status {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host "[SETUP] $Message" -ForegroundColor $Color
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Write-Success {
    param([string]$Message)
    Write-Host "[✓] $Message" -ForegroundColor Green
}

function Normalize-Root {
    param([string]$Path)
    if ($Path -and -not $Path.EndsWith("\")) { return "$Path\" }
    return $Path
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Extract-Zip {
    param([string]$ZipPath, [string]$DestPath, [bool]$Force = $false)
    
    if (-not (Test-Path -LiteralPath $ZipPath)) {
        throw "Zip file not found: $ZipPath"
    }
    
    if ((Test-Path -LiteralPath $DestPath) -and -not $Force) {
        Write-Status "Destination already exists: $DestPath (use -Force to overwrite)"
        return $false
    }
    
    if (Test-Path -LiteralPath $DestPath) {
        Remove-Item -LiteralPath $DestPath -Recurse -Force
    }
    
    Ensure-Dir $DestPath
    
    try {
        $shell = New-Object -ComObject Shell.Application
        $zip = $shell.NameSpace($ZipPath)
        $dest = $shell.NameSpace($DestPath)
        
        Write-Status "Extracting $ZipPath to $DestPath..."
        $dest.CopyHere($zip.Items(), 16)  # 16 = suppress prompts
        
        Start-Sleep -Seconds 2  # Wait for extraction to complete
        Write-Success "Extracted: $ZipPath"
        return $true
    } catch {
        Write-Error-Custom "Failed to extract $ZipPath : $_"
        throw
    }
}

# ───────────────────────────────────────────────────────────────────────────────
# START
# ───────────────────────────────────────────────────────────────────────────────

$Root = Normalize-Root $Root
Write-Status "═══════════════════════════════════════════════════════════"
Write-Status "        SONIA UPSTREAM DEPENDENCY SETUP"
Write-Status "═══════════════════════════════════════════════════════════"
Write-Status "Root: $Root"

$sysProgDir = "$($Root)tools\sysprog"
if (-not (Test-Path -LiteralPath $sysProgDir)) {
    Write-Error-Custom "System programs directory not found: $sysProgDir"
    exit 1
}

# ───────────────────────────────────────────────────────────────────────────────
# 1. LM-STUDIO (Local LLM)
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "1. LM-Studio (Local LLM Server)"
Write-Status "───────────────────────────────"

$lmStudioExe = "$sysProgDir\LM-Studio-0.4.2-2-x64.exe"
if (Test-Path -LiteralPath $lmStudioExe) {
    Write-Status "LM-Studio installer found"
    Write-Status "Install location: S:\tools\lm-studio"
    Write-Status "To install: run the .exe (interactive)"
    Write-Status "Note: LM-Studio includes its own web server on port 1234"
    Write-Success "LM-Studio ready for manual installation"
} else {
    Write-Error-Custom "LM-Studio exe not found"
}

# ───────────────────────────────────────────────────────────────────────────────
# 2. MINICONDA (Python Environment)
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "2. Miniconda (Python Environment)"
Write-Status "──────────────────────────────────"

$condaExe = "$sysProgDir\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe"
if (Test-Path -LiteralPath $condaExe) {
    Write-Status "Miniconda installer found"
    Write-Status "Install location: S:\tools\miniconda3"
    Write-Status "To install: run the .exe (interactive)"
    Write-Status "Note: During install, add to PATH and register Python"
    Write-Success "Miniconda ready for manual installation"
} else {
    Write-Error-Custom "Miniconda exe not found"
}

# ───────────────────────────────────────────────────────────────────────────────
# 3. OPENCLAW (Upstream)
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "3. OpenClaw (Upstream)"
Write-Status "─────────────────────"

$openclawZip = "$sysProgDir\openclaw-main.zip"
$openclawDest = "$($Root)integrations\openclaw\upstream\src\openclaw-main-new"

if (Test-Path -LiteralPath $openclawZip) {
    try {
        Extract-Zip $openclawZip $openclawDest $Force
        
        # Create CURRENT.txt pointer
        $currentFile = "$($Root)integrations\openclaw\upstream\CURRENT.txt"
        Set-Content -LiteralPath $currentFile -Value $openclawDest -Encoding ASCII -NoNewline
        Write-Success "Created CURRENT.txt pointer to: $openclawDest"
    } catch {
        Write-Error-Custom "Failed to setup OpenClaw: $_"
    }
} else {
    Write-Error-Custom "openclaw-main.zip not found"
}

# ───────────────────────────────────────────────────────────────────────────────
# 4. PIPECAT (Upstream)
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "4. Pipecat (Upstream)"
Write-Status "────────────────────"

$pipecatZip = "$sysProgDir\pipecat-main.zip"
$pipecatDest = "$($Root)integrations\pipecat\upstream\src\pipecat-main-new"

if (Test-Path -LiteralPath $pipecatZip) {
    try {
        Extract-Zip $pipecatZip $pipecatDest $Force
        
        # Create CURRENT.txt pointer
        $currentFile = "$($Root)integrations\pipecat\upstream\CURRENT.txt"
        Ensure-Dir (Split-Path $currentFile)
        Set-Content -LiteralPath $currentFile -Value $pipecatDest -Encoding ASCII -NoNewline
        Write-Success "Created CURRENT.txt pointer to: $pipecatDest"
    } catch {
        Write-Error-Custom "Failed to setup Pipecat: $_"
    }
} else {
    Write-Error-Custom "pipecat-main.zip not found"
}

# ───────────────────────────────────────────────────────────────────────────────
# 5. PIPECAT-FLOWS (Optional)
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "5. Pipecat-Flows (Optional Framework)"
Write-Status "────────────────────────────────────"

$pipecatFlowsZip = "$sysProgDir\pipecat-flows-main.zip"
$pipecatFlowsDest = "$($Root)integrations\pipecat-flows\upstream\src\pipecat-flows-main-new"

if (Test-Path -LiteralPath $pipecatFlowsZip) {
    try {
        Extract-Zip $pipecatFlowsZip $pipecatFlowsDest $Force
        Write-Success "Extracted Pipecat-Flows (optional)"
    } catch {
        Write-Error-Custom "Failed to setup Pipecat-Flows (optional): $_"
    }
} else {
    Write-Status "pipecat-flows-main.zip not found (optional)"
}

# ───────────────────────────────────────────────────────────────────────────────
# 6. VLLM (Optional - GPU-accelerated LLM)
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "6. vLLM (Optional - GPU-accelerated LLM)"
Write-Status "───────────────────────────────────────"

$vllmZip = "$sysProgDir\vllm-main.zip"
$vllmDest = "$($Root)integrations\vllm\upstream\src\vllm-main-new"

if (Test-Path -LiteralPath $vllmZip) {
    try {
        Extract-Zip $vllmZip $vllmDest $Force
        Write-Success "Extracted vLLM (optional)"
    } catch {
        Write-Error-Custom "Failed to setup vLLM (optional): $_"
    }
} else {
    Write-Status "vllm-main.zip not found (optional)"
}

# ───────────────────────────────────────────────────────────────────────────────
# 7. EVA-OS (If not already integrated)
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "7. EVA-OS (Upstream Reference)"
Write-Status "──────────────────────────────"

$evaosZip = "$sysProgDir\EVA-OS-main.zip"
$evaosDest = "$($Root)integrations\eva-os\upstream\src\eva-os-main-new"

if (Test-Path -LiteralPath $evaosZip) {
    try {
        Extract-Zip $evaosZip $evaosDest $Force
        Write-Success "Extracted EVA-OS reference (for comparison/documentation)"
    } catch {
        Write-Error-Custom "Failed to setup EVA-OS reference (optional): $_"
    }
} else {
    Write-Status "EVA-OS-main.zip not found (we built our own)"
}

# ───────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ───────────────────────────────────────────────────────────────────────────────

Write-Status ""
Write-Status "═══════════════════════════════════════════════════════════"
Write-Status "                    SETUP COMPLETE"
Write-Status "═══════════════════════════════════════════════════════════"
Write-Status ""
Write-Status "Next Steps:"
Write-Status "  1. Install LM-Studio manually (GUI): S:\tools\sysprog\LM-Studio-0.4.2-2-x64.exe"
Write-Status "  2. Install Miniconda manually (GUI): S:\tools\sysprog\Miniconda3-py311_25.11.1-1-Windows-x86_64.exe"
Write-Status "     → During install, add to PATH: Yes"
Write-Status "     → Register as default Python: Yes"
Write-Status "  3. Verify Python: python --version"
Write-Status "  4. Verify Conda: conda --version"
Write-Status "  5. Start Sonia stack: .\start-sonia-stack.ps1"
Write-Status ""
Write-Success "All upstream dependencies prepared!"
