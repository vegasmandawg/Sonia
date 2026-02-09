"""Database layer for Memory Engine."""

import sys
from pathlib import Path

# The db.py module at the service root contains get_db and MemoryDatabase.
# Since this db/ package shadows it, re-export from the module file directly.
_service_root = str(Path(__file__).parent.parent)
if _service_root not in sys.path:
    sys.path.insert(0, _service_root)

# Load the actual db module (db.py in parent dir) by importing directly
import importlib.util
_spec = importlib.util.spec_from_file_location("_db_module", Path(__file__).parent.parent / "db.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

get_db = _mod.get_db
MemoryDatabase = _mod.MemoryDatabase
