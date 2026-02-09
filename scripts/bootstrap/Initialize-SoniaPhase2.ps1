<#
Initialize-SoniaPhase2.ps1
Seeds starter files/configs/service stubs for FINAL Sonia architecture on S:\

Usage:
  powershell -ExecutionPolicy Bypass -File S:\scripts\bootstrap\Initialize-SoniaPhase2.ps1
  powershell -ExecutionPolicy Bypass -File S:\scripts\bootstrap\Initialize-SoniaPhase2.ps1 -Root "S:\" -Force
  powershell -ExecutionPolicy Bypass -File S:\scripts\bootstrap\Initialize-SoniaPhase2.ps1 -DryRun
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$Root = "S:\",

    [Parameter(Mandatory = $false)]
    [switch]$Force,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Root.EndsWith("\")) { $Root = "$Root\" }

$driveLetter = $Root.Substring(0, 1)
if (-not (Get-PSDrive -Name $driveLetter -ErrorAction SilentlyContinue)) {
    throw "Drive '${driveLetter}:' does not exist. Update -Root."
}

$Created = 0
$Overwritten = 0
$Skipped = 0

function Ensure-Dir {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) { return }
    if ($DryRun) {
        Write-Host "[DRYRUN] mkdir $Path"
        return
    }

    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Write-SeedFile {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Content
    )

    if ($null -eq $Content) { $Content = "" }

    $fullPath = Join-Path $Root $RelativePath
    $parent = Split-Path -Parent $fullPath
    Ensure-Dir -Path $parent

    $exists = Test-Path -LiteralPath $fullPath
    if ($exists -and -not $Force) {
        $script:Skipped++
        Write-Host "SKIP      $RelativePath"
        return
    }

    if ($DryRun) {
        if ($exists -and $Force) {
            $script:Overwritten++
            Write-Host "[DRYRUN] OVERWRITE $RelativePath"
        } else {
            $script:Created++
            Write-Host "[DRYRUN] CREATE    $RelativePath"
        }
        return
    }

    Set-Content -LiteralPath $fullPath -Value $Content -Encoding UTF8

    if ($exists -and $Force) {
        $script:Overwritten++
        Write-Host "OVERWRITE $RelativePath"
    } else {
        $script:Created++
        Write-Host "CREATE    $RelativePath"
    }
}

# Ensure critical folders exist
$requiredDirs = @(
    "config\env",
    "config\models",
    "config\services",
    "config\voice",
    "config\ui",
    "docs\architecture",
    "docs\contracts",
    "docs\runbooks",
    "docs\reports",
    "logs\boot",
    "logs\services",
    "scripts\bootstrap",
    "scripts\diagnostics",
    "scripts\ops",
    "services\model-router",
    "services\memory-engine",
    "services\pipecat",
    "services\openclaw",
    "apps\api\src",
    "apps\api\tests",
    "shared\schemas",
    "state\pids",
    "state\locks",
    "policies\side-effects",
    "policies\permissions"
)

foreach ($d in $requiredDirs) {
    Ensure-Dir -Path (Join-Path $Root $d)
}

# Root/tooling starter files
Write-SeedFile -RelativePath ".gitignore" -Content @'
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.venv/
.pytest_cache/
.mypy_cache/

# Node
node_modules/
dist/
build/

# Env/secrets
.env
.env.*
!.env.template
*.key
*.pem
*.pfx
secrets/local/*

# Logs/state/cache
logs/**
!logs/.gitkeep
cache/**
state/**
tmp/**

# Model and data artifacts
models/**/*
!models/manifests/**
datasets/**/*
data/**/*

# OS
Thumbs.db
Desktop.ini
.DS_Store
'@

Write-SeedFile -RelativePath ".editorconfig" -Content @'
root = true

[*]
charset = utf-8
end_of_line = crlf
insert_final_newline = true
indent_style = space
indent_size = 2
trim_trailing_whitespace = true

[*.py]
indent_size = 4

[*.ps1]
indent_size = 4
'@

Write-SeedFile -RelativePath "README.md" -Content @'
# SONIA (FINAL) — S:\ Root

Canonical root: `S:\`
This is the final clean-drive iteration.

## Core startup
1. Configure environment values in `config/env/.env.template`.
2. Validate system via `scripts/diagnostics/doctor.ps1`.
3. Start service skeletons via `scripts/ops/start-all.ps1`.

## Design principles
- Local-first
- Explicit side effects for destructive actions
- Reproducible folder and config contracts
- Observable runtime via logs and audit trails
'@

Write-SeedFile -RelativePath "logs\.gitkeep" -Content ""
Write-SeedFile -RelativePath "state\.gitkeep" -Content ""

# Config seeds
Write-SeedFile -RelativePath "config\env\.env.template" -Content @'
# ===== SONIA FINAL ENV TEMPLATE =====
# DO NOT commit real secrets.

SONIA_ROOT=S:\
SONIA_ENV=production
SONIA_PROFILE=default
SONIA_TIMEZONE=America/Chicago

# API endpoints
OLLAMA_BASE_URL=http://127.0.0.1:11434
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
ANTHROPIC_BASE_URL=https://api.anthropic.com

# API keys (placeholders only)
OPENROUTER_API_KEY=__REPLACE_ME__
ANTHROPIC_API_KEY=__REPLACE_ME__
HUGGINGFACE_API_KEY=__REPLACE_ME__
GITHUB_TOKEN=__REPLACE_ME__

# Model defaults
SONIA_TEXT_MODEL=qwen3-32b
SONIA_VISION_MODEL=qwen3-vl-32b
SONIA_EMBEDDING_MODEL=bge-m3
SONIA_RERANK_MODEL=bge-reranker-v2

# Storage paths
HF_HOME=S:\cache\hf
TRANSFORMERS_CACHE=S:\cache\transformers
OLLAMA_MODELS=S:\models\llm
VLLM_CACHE_ROOT=S:\cache\vllm
'@

Write-SeedFile -RelativePath "config\runtime.yaml" -Content @'
runtime:
  name: sonia-final
  root: "S:\\"
  timezone: "America/Chicago"
  mode: "local-first"
  profile: "default"

observability:
  logs_dir: "S:\\logs"
  audit_dir: "S:\\audit"
  level: "info"

safety:
  require_confirmation_for:
    - delete_files
    - system_shutdown
    - registry_write
    - destructive_shell
  policy_file: "S:\\policies\\side-effects\\approval-matrix.yaml"

state:
  pid_dir: "S:\\state\\pids"
  lock_dir: "S:\\state\\locks"
  checkpoints_dir: "S:\\state\\checkpoints"
'@

Write-SeedFile -RelativePath "config\models\model-routing.yaml" -Content @'
routing:
  text:
    primary:
      provider: ollama
      model: qwen3-32b
    fallback:
      provider: openrouter
      model: deepseek-r1-distill-qwen-32b

  vision:
    primary:
      provider: ollama
      model: qwen3-vl-32b

  embeddings:
    primary:
      provider: local
      model: bge-m3

  reranker:
    primary:
      provider: local
      model: bge-reranker-v2

  asr:
    primary:
      provider: local
      model: whisper-large-v3

  tts:
    primary:
      provider: local
      model: xtts-v2
'@

Write-SeedFile -RelativePath "config\services\services.yaml" -Content @'
services:
  model_router:
    host: "127.0.0.1"
    port: 7010
  memory_engine:
    host: "127.0.0.1"
    port: 7020
  pipecat:
    host: "127.0.0.1"
    port: 7030
  openclaw:
    host: "127.0.0.1"
    port: 7040
  api_gateway:
    host: "127.0.0.1"
    port: 7000
'@

Write-SeedFile -RelativePath "config\voice\voice-profile.yaml" -Content @'
voice:
  name: "Sonia"
  style: "confident, clear, grounded"
  accent_target: "irish_female"
  sample_rate_hz: 24000
  vad: "silero"
  tts_model: "xtts-v2"
  dataset_dir: "S:\\voice\\datasets"
  recordings_dir: "S:\\voice\\recordings"
'@

Write-SeedFile -RelativePath "config\ui\theme.yaml" -Content @'
theme:
  name: "red-black"
  mode: "dark"
  colors:
    background: "#070707"
    panel: "#111111"
    panel_alt: "#161616"
    accent_primary: "#8B0000"
    accent_secondary: "#B22222"
    text_primary: "#F5F5F5"
    text_muted: "#B0B0B0"
'@

# Policies + docs
Write-SeedFile -RelativePath "policies\side-effects\approval-matrix.yaml" -Content @'
approvals:
  delete_files:
    require_confirmation: true
    reason_required: true
  system_shutdown:
    require_confirmation: true
    reason_required: true
  registry_write:
    require_confirmation: true
    reason_required: true
  shell_exec:
    require_confirmation: false
    reason_required: false
'@

Write-SeedFile -RelativePath "policies\permissions\permissions.yaml" -Content @'
permissions:
  filesystem:
    allow_roots:
      - "S:\\"
    deny_paths:
      - "C:\\Windows\\System32\\"
  network:
    default: "deny"
    allowlist:
      - "127.0.0.1"
      - "localhost"
'@

Write-SeedFile -RelativePath "docs\contracts\RUNTIME_CONTRACT.md" -Content @'
# Runtime Contract (Final)

- Canonical root is `S:\`.
- All Sonia files live under `S:\`.
- Service configs are read from `S:\config`.
- Logs are written to `S:\logs`.
- Audit trails are written to `S:\audit`.
- Destructive actions require explicit user confirmation.
'@

Write-SeedFile -RelativePath "docs\runbooks\BOOTSTRAP_RUNBOOK.md" -Content @'
# Bootstrap Runbook

1. Run folder architecture script.
2. Run `Initialize-SoniaPhase2.ps1`.
3. Fill env placeholders securely.
4. Run diagnostics:
   - `powershell -ExecutionPolicy Bypass -File S:\scripts\diagnostics\doctor.ps1`
5. Start services:
   - `powershell -ExecutionPolicy Bypass -File S:\scripts\ops\start-all.ps1`
'@

# Scripts
Write-SeedFile -RelativePath "scripts\diagnostics\doctor.ps1" -Content @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$checks = @(
  @{ Name = "S drive"; Test = { Test-Path "S:\" } },
  @{ Name = "config/runtime"; Test = { Test-Path "S:\config\runtime.yaml" } },
  @{ Name = "model routing"; Test = { Test-Path "S:\config\models\model-routing.yaml" } },
  @{ Name = "services config"; Test = { Test-Path "S:\config\services\services.yaml" } },
  @{ Name = "logs dir"; Test = { Test-Path "S:\logs" } },
  @{ Name = "state dir"; Test = { Test-Path "S:\state" } }
)

$failed = 0
foreach ($c in $checks) {
  $ok = & $c.Test
  if ($ok) {
    Write-Host "[OK]   $($c.Name)"
  } else {
    Write-Host "[FAIL] $($c.Name)"
    $failed++
  }
}

if ($failed -gt 0) {
  Write-Error "Doctor check failed: $failed issue(s)."
} else {
  Write-Host "Doctor check passed."
}
'@

Write-SeedFile -RelativePath "scripts\ops\start-all.ps1" -Content @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Starting Sonia service skeletons..."

# Placeholder starts; replace with actual launch commands.
Write-Host " -> model-router"
Write-Host " -> memory-engine"
Write-Host " -> pipecat"
Write-Host " -> openclaw"
Write-Host " -> api-gateway"

Write-Host "Done."
'@

Write-SeedFile -RelativePath "scripts\ops\stop-all.ps1" -Content @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Stopping Sonia service skeletons..."

# Placeholder stops; replace with process/service control logic.
Write-Host " -> model-router"
Write-Host " -> memory-engine"
Write-Host " -> pipecat"
Write-Host " -> openclaw"
Write-Host " -> api-gateway"

Write-Host "Done."
'@

Write-SeedFile -RelativePath "scripts\bootstrap\bootstrap.ps1" -Content @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Sonia bootstrap starting..."
& "S:\scripts\diagnostics\doctor.ps1"
Write-Host "Bootstrap complete."
'@

# API + service stubs
Write-SeedFile -RelativePath "apps\api\requirements.txt" -Content @'
fastapi==0.116.1
uvicorn==0.35.0
pydantic==2.11.7
'@

Write-SeedFile -RelativePath "apps\api\src\main.py" -Content @'
from fastapi import FastAPI

app = FastAPI(title="Sonia API Gateway", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True, "service": "api-gateway"}

@app.get("/version")
def version():
    return {"name": "sonia-final", "version": "0.1.0"}
'@

Write-SeedFile -RelativePath "services\model-router\main.py" -Content @'
from fastapi import FastAPI

app = FastAPI(title="Sonia Model Router", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True, "service": "model-router"}

@app.get("/route")
def route():
    return {
        "text": "qwen3-32b",
        "vision": "qwen3-vl-32b",
        "embeddings": "bge-m3"
    }
'@

Write-SeedFile -RelativePath "services\memory-engine\main.py" -Content @'
from fastapi import FastAPI

app = FastAPI(title="Sonia Memory Engine", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True, "service": "memory-engine"}

@app.get("/ledger/status")
def ledger_status():
    return {"ok": True, "ledger": "ready"}
'@

Write-SeedFile -RelativePath "services\pipecat\main.py" -Content @'
from fastapi import FastAPI

app = FastAPI(title="Sonia Pipecat Bridge", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True, "service": "pipecat"}
'@

Write-SeedFile -RelativePath "services\openclaw\main.py" -Content @'
from fastapi import FastAPI

app = FastAPI(title="Sonia OpenClaw Bridge", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True, "service": "openclaw"}
'@

Write-SeedFile -RelativePath "shared\schemas\event.schema.json" -Content @'
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "sonia.event.schema",
  "title": "SoniaEvent",
  "type": "object",
  "required": ["timestamp", "type", "source"],
  "properties": {
    "timestamp": { "type": "string", "format": "date-time" },
    "type": { "type": "string" },
    "source": { "type": "string" },
    "payload": { "type": "object" }
  },
  "additionalProperties": false
}
'@

if (-not $DryRun) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $report = Join-Path $Root "docs\reports\phase2_seed_report_$stamp.txt"
    @"
Sonia Phase 2 seed report
Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Root: $Root
Created: $Created
Overwritten: $Overwritten
Skipped: $Skipped
DryRun: $DryRun
Force: $Force
"@ | Set-Content -LiteralPath $report -Encoding UTF8

    Write-Host "Report: $report"
}

Write-Host ""
Write-Host "Phase 2 complete."
Write-Host "Root:        $Root"
Write-Host "Created:     $Created"
Write-Host "Overwritten: $Overwritten"
Write-Host "Skipped:     $Skipped"
