import os

# Set a very high rate limit so the test suite never hits the 10/minute default.
os.environ.setdefault("ANALYZE_RATE_LIMIT", "10000/minute")
# Set a valid API_KEY so app.main can be imported without raising RuntimeError.
# Individual tests that check auth behaviour use hmac.compare_digest against
# this value (or reload the module with a different env var).
os.environ.setdefault("API_KEY", "test-dev-token-1234")
