"""Test bootstrap for the CBC backend.

The container copies `src/backend/` to `/app/src/`, so every module imports as
`src.*` (e.g. `from src.services import ...`). Locally the directory is still
named `backend`, so we alias a top-level `src` package onto it before any test
imports run. We also point `CBC_DATA_DIR` at a throwaway dir so tests never
touch real on-disk state (DATA_DIR is read at import time in _paths.py).
"""
import os
import pathlib
import sys
import tempfile
import types

# Isolate on-disk state BEFORE src.services._paths computes DATA_DIR at import.
os.environ.setdefault("CBC_DATA_DIR", tempfile.mkdtemp(prefix="cbc-test-data-"))

# Alias `src` -> .../src/backend so `import src.services...` resolves locally.
_BACKEND = pathlib.Path(__file__).resolve().parent.parent / "src" / "backend"
if "src" not in sys.modules:
    _pkg = types.ModuleType("src")
    _pkg.__path__ = [str(_BACKEND)]
    sys.modules["src"] = _pkg
