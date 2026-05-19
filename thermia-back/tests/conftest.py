import os

# Set a very high rate limit so the test suite never hits the 10/minute default.
os.environ.setdefault("ANALYZE_RATE_LIMIT", "10000/minute")
# Use local mode so auth checks are skipped in endpoint tests.
os.environ.setdefault("THERMIA_ENV", "local")
