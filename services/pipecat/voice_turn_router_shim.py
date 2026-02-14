"""
Import shim for VoiceTurnRouter and VoiceTurnRecord.

Legacy tests (v2.7-v2.8) import from `app.voice_turn_router`, which
collides with api-gateway's `app/` package when pytest collects tests
from multiple service directories. This shim re-exports the canonical
classes without requiring sys.path manipulation.

Usage in tests:
    from voice_turn_router_shim import VoiceTurnRouter, VoiceTurnRecord

Tracked under: LEGACY-IMPORT-VOICE-TURN-ROUTER
"""

import sys
import importlib.util

# Load the real module by absolute file path to avoid app/ package collision.
_spec = importlib.util.spec_from_file_location(
    "pipecat_voice_turn_router",
    r"S:\services\pipecat\app\voice_turn_router.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["pipecat_voice_turn_router"] = _mod
_spec.loader.exec_module(_mod)

# Re-export canonical classes
VoiceTurnRouter = _mod.VoiceTurnRouter
VoiceTurnRecord = _mod.VoiceTurnRecord
