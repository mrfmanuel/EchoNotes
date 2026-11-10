"""Docker HEALTHCHECK (#22): exit 0 only when GET /api/health on $PORT returns 200."""

import os
import sys
import urllib.request

URL = f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/api/health"

try:
    with urllib.request.urlopen(URL, timeout=4) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
