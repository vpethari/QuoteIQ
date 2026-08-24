"""QuoteIQ backend package.

When the API is started from the repository root as
``backend.app.main:app``, this module puts the ``backend/`` directory on
``sys.path`` so existing sibling imports (``app``, ``catalog``, ``matching``,
etc.) resolve without a manual PYTHONPATH.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
