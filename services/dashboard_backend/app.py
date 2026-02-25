from __future__ import annotations

import os

# Running as internal backend service: no frontend proxy here.
os.environ.setdefault("DASHBOARD_ENABLE_FRONTEND_PROXY", "0")
from dashboard_api import app

__all__ = ["app"]
