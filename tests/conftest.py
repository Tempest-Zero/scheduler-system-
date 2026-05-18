"""Shared pytest setup: make the scheduler package importable."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "or-tools-scheduler" / "or-tools-scheduler"))
