"""Shared pytest setup: path only.

Adds `src/` to `sys.path` so every test file can `import digest` and its sub-modules
without each one repeating the same three lines, and points the contract loader at the
repository's own `contracts/` directory regardless of the working directory pytest was
invoked from.

Nothing else belongs here. A test that needs a fixture puts it in its own test file, per
`build/COMMON_RULES.md`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("DIGEST_CONTRACTS_DIR", str(REPO_ROOT / "contracts"))
