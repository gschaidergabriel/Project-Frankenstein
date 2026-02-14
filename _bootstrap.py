"""
Minimal sys.path bootstrapper for entry-point scripts.

Usage (at the TOP of any entry-point script launched by systemd or CLI):

    import _bootstrap  # noqa: F401

This adds the aicore source root to sys.path so that
`from config.paths import ...` and other imports work regardless
of how the script was invoked.
"""

import sys
from pathlib import Path

_AICORE_ROOT = str(Path(__file__).resolve().parent)
if _AICORE_ROOT not in sys.path:
    sys.path.insert(0, _AICORE_ROOT)
