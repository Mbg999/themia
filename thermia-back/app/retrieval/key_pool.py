"""
Provider-agnostic API key pool with sticky-then-rotate fallback strategy.

Key design decisions:
- threading.Lock (not asyncio.Lock): ingest.py is synchronous; FastAPI's
  Groq calls run in worker threads; threading.Lock covers both.
- Module-level singleton per provider via from_env(); explicit-keys
  constructor for unit-test isolation (no os.environ monkey-patching needed).
- Cool-down state is in-process only — a process restart resets all cool-downs.
"""
from __future__ import annotations

import enum
import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

_RATE_LIMIT_RE = re.compile(r"429|rate limit", re.IGNORECASE)
_GROQ_DAILY_RE = re.compile(r"daily.*(token|quota)", re.IGNORECASE)
_5XX_RE = re.compile(r"(?<!\d)5\d{2}(?!\d)")


class FailureReason(enum.Enum):
    """Rotation-triggering failure signals (FR-3)."""
    RATE_LIMIT_429 = "429"
    GROQ_DAILY_QUOTA = "groq_daily"
    PERSISTENT_5XX = "5xx"


class AllKeysExhaustedError(Exception):
    """Raised when all keys in the pool are in cool-down (FR-6 runtime)."""


# ---------------------------------------------------------------------------
# Failure-signal classifier
# ---------------------------------------------------------------------------

def classify_failure(exc_or_text: Any) -> FailureReason | None:
    """Map an exception or error text to a ``FailureReason``.

    Returns ``None`` for non-rotating signals (e.g. 400, 401, 403).

    Parameters
    ----------
    exc_or_text:
        An exception object or a string containing the error detail.
    """
    text = str(exc_or_text)

    # Groq daily quota
    if _GROQ_DAILY_RE.search(text):
        return FailureReason.GROQ_DAILY_QUOTA

    # Generic 429 / rate-limit (after provider-specific checks)
    if _RATE_LIMIT_RE.search(text):
        return FailureReason.RATE_LIMIT_429

    # Persistent 5xx — the regex uses look-around to avoid matching 5xx
    # substrings inside larger numbers (e.g. "15000" must not match).
    if _5XX_RE.search(text):
        return FailureReason.PERSISTENT_5XX

    return None


# ---------------------------------------------------------------------------
# Environment parsing helper
# ---------------------------------------------------------------------------

# Key format: alphanumeric characters, hyphens, and underscores; minimum 8 chars.
# This is intentionally broad — real Groq keys use this character set.
_KEY_FORMAT_RE = re.compile(r"^[\w\-]{8,}$")


def _validate_key_format(keys: list[str], source_var: str) -> None:
    """Raise ValueError if any key in *keys* fails the format check.

    Checks:
    - Non-empty string
    - Minimum 8 characters
    - Only alphanumeric characters, hyphens, and underscores

    Logs the count of loaded keys but never any key material.
    """
    for i, key in enumerate(keys):
        if not isinstance(key, str) or not _KEY_FORMAT_RE.match(key):
            raise ValueError(
                f"{source_var}[{i}]: invalid key format "
                f"(must be alphanumeric/hyphens/underscores, min 8 chars)"
            )


def _parse_keys_env(provider: str, environ: dict[str, str]) -> list[str]:
    """Return the list of API keys for *provider* from *environ*.

    Lookup order:
    1. ``<PROVIDER>_API_KEYS`` — JSON array (preferred).
    2. ``<PROVIDER>_API_KEY``  — legacy scalar (emit WARN, treat as 1-element pool).

    Raises ``ValueError`` on missing or malformed configuration.
    """
    upper = provider.upper()
    array_var = f"{upper}_API_KEYS"
    scalar_var = f"{upper}_API_KEY"

    raw = environ.get(array_var, "").strip()
    if raw:
        # Strip surrounding single-quotes that .env parsers sometimes add
        if raw.startswith("'") and raw.endswith("'"):
            raw = raw[1:-1].strip()
        try:
            keys = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{array_var} contains invalid JSON: {exc}. "
                f"Expected a JSON array, e.g.: {array_var}='[\"key1\",\"key2\"]'"
            ) from exc
        if not isinstance(keys, list) or not keys:
            raise ValueError(
                f"{array_var} must be a non-empty JSON array. "
                f"See .env.example for the correct format."
            )
        str_keys = [str(k) for k in keys]
        if not all(str_keys):
            raise ValueError(f"{array_var} contains empty key entries.")
        _validate_key_format(str_keys, array_var)
        log.info("key_pool.loaded provider=%s count=%d", provider, len(str_keys))
        return str_keys

    # Legacy fallback
    legacy = environ.get(scalar_var, "").strip()
    if legacy:
        log.warning(
            "key_pool.legacy_var: %s is set but %s is not. "
            "Treating %s as a one-element pool. "
            "Migrate to %s='[\"%s...\"]' for multi-key fallback.",
            scalar_var, array_var, scalar_var, array_var, legacy[:4],
        )
        _validate_key_format([legacy], scalar_var)
        log.info("key_pool.loaded provider=%s count=1", provider)
        return [legacy]

    raise ValueError(
        f"No API keys configured for provider '{provider}'. "
        f"Set {array_var}='[\"key1\",\"key2\"]' in your .env file. "
        f"See .env.example for examples. At least one key is required."
    )


# Default cool-down windows per provider (seconds)
_DEFAULT_COOLDOWNS: dict[str, int] = {
    "groq": 86400,      # 1 day  (daily token reset)
}


def _get_cooldown_seconds(provider: str) -> int:
    """Read per-provider cool-down from env or use default."""
    env_var = f"{provider.upper()}_KEY_COOLDOWN_SECONDS"
    raw = os.environ.get(env_var, "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            log.warning("key_pool.bad_cooldown: %s='%s' is not an integer; using default.", env_var, raw)
    return _DEFAULT_COOLDOWNS.get(provider.lower(), 86400)


# ---------------------------------------------------------------------------
# KeyPool
# ---------------------------------------------------------------------------

class KeyPool:
    """Sticky-then-rotate pool of API keys for a single provider.

    Thread-safe: all mutations are protected by a ``threading.Lock``.

    Parameters
    ----------
    keys:
        Ordered list of API keys. Position 0 is highest priority.
    provider:
        Provider name (e.g. ``"groq"``).
        Used for log fields and cool-down env-var lookup.
    cooldown_seconds:
        Optional override for the cool-down window. When *None*, the
        value is read from ``<PROVIDER>_KEY_COOLDOWN_SECONDS`` env var or
        the provider default (1 d — daily token reset).
    """

    def __init__(
        self,
        keys: list[str],
        provider: str,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not keys:
            raise ValueError(
                f"KeyPool for provider '{provider}' requires at least one key."
            )
        self._keys = list(keys)
        self._provider = provider.lower()
        self._cooldown = (
            cooldown_seconds
            if cooldown_seconds is not None
            else _get_cooldown_seconds(self._provider)
        )
        self._cursor = 0
        # Maps key-index → unix timestamp when the cool-down expires
        self._cooldowns: dict[int, float] = {}
        self._lock = threading.Lock()
        # Track state transitions to emit each WARN/ERROR only once per transition
        self._was_degraded = False
        self._was_exhausted = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        provider: str,
        environ: dict[str, str] | None = None,
        cooldown_seconds: int | None = None,
    ) -> "KeyPool":
        """Construct a ``KeyPool`` by reading keys from environment variables.

        Parameters
        ----------
        provider:
            ``"groq"`` (or any future provider).
        environ:
            Optional dict of environment variables (defaults to ``os.environ``).
            Provide an explicit dict in tests to avoid monkey-patching.
        cooldown_seconds:
            Optional cool-down override (seconds). Falls back to env var or default.
        """
        env = environ if environ is not None else dict(os.environ)
        keys = _parse_keys_env(provider, env)
        return cls(keys=keys, provider=provider, cooldown_seconds=cooldown_seconds)

    def current(self) -> str:
        """Return the currently active API key.

        Raises ``AllKeysExhaustedError`` if no healthy key is available.
        """
        with self._lock:
            return self._current_unlocked()

    def mark_failed(self, reason: FailureReason) -> None:
        """Record the current key as failed and advance to the next healthy key.

        Emits structured log lines per FR-7:
        - ``key_pool.rotated`` INFO on successful rotation
        - ``key_pool.degraded`` WARN when exactly one key remains (once per transition)
        - ``key_pool.exhausted`` ERROR when zero healthy keys remain (once per transition)

        Raises ``AllKeysExhaustedError`` if no healthy key is available after rotation.
        """
        with self._lock:
            failed_index = self._cursor
            # Put failed key into cool-down
            self._cooldowns[failed_index] = time.time() + self._cooldown

            next_index = self._next_healthy_index(skip=failed_index)
            healthy = self._count_healthy_unlocked()

            if next_index is None:
                # Zero healthy keys
                if not self._was_exhausted:
                    self._was_exhausted = True
                    self._was_degraded = False
                    log.error(
                        "key_pool.exhausted provider=%s keys_remaining=0",
                        self._provider,
                    )
                raise AllKeysExhaustedError(
                    f"All keys for provider '{self._provider}' are in cool-down."
                )

            # Successful rotation
            log.info(
                "key_pool.rotated provider=%s key_index_from=%d key_index_to=%d "
                "reason=%s keys_remaining=%d key_id_hash_from=%s key_id_hash_to=%s",
                self._provider,
                failed_index,
                next_index,
                reason.value,
                healthy,
                self._hash_key(self._keys[failed_index]),
                self._hash_key(self._keys[next_index]),
            )
            self._cursor = next_index
            self._was_exhausted = False

            # Degraded-state transition: exactly 1 key left
            if healthy == 1 and not self._was_degraded:
                self._was_degraded = True
                log.warning(
                    "key_pool.degraded provider=%s keys_remaining=1",
                    self._provider,
                )
            elif healthy > 1:
                self._was_degraded = False

    def healthy_count(self) -> int:
        """Return the number of keys not currently in cool-down."""
        with self._lock:
            return self._count_healthy_unlocked()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _current_unlocked(self) -> str:
        """Return the active key; raises AllKeysExhaustedError if none.

        Also resets _was_degraded / _was_exhausted when cooldown expiry
        re-admits keys, so that future degradation/exhaustion events will
        emit their log transitions again.
        """
        # Check that the current cursor index is still healthy
        if not self._is_healthy(self._cursor):
            # Try to find any healthy key
            idx = self._next_healthy_index(skip=None)
            if idx is None:
                raise AllKeysExhaustedError(
                    f"All keys for provider '{self._provider}' are in cool-down."
                )
            self._cursor = idx

        # Re-compute healthy count after any cooldown expiries (side-effect of
        # _is_healthy / _next_healthy_index calls above) and reset flags so
        # future degradation / exhaustion transitions fire again.
        healthy_count = self._count_healthy_unlocked()
        if healthy_count > 1 and self._was_degraded:
            self._was_degraded = False
        if healthy_count > 0 and self._was_exhausted:
            self._was_exhausted = False

        return self._keys[self._cursor]

    def _is_healthy(self, index: int) -> bool:
        """Return True if the key at *index* is not in cool-down."""
        expiry = self._cooldowns.get(index)
        if expiry is None:
            return True
        if time.time() >= expiry:
            # Cool-down expired — re-enter pool
            del self._cooldowns[index]
            return True
        return False

    def _next_healthy_index(self, skip: int | None) -> int | None:
        """Return the index of the next healthy key after skipping *skip*.

        Searches the key list in declaration order, wrapping around.
        Returns ``None`` if no healthy key exists.
        """
        n = len(self._keys)
        for offset in range(1, n + 1):
            idx = (self._cursor + offset) % n
            if idx == skip:
                continue
            if self._is_healthy(idx):
                return idx
        return None

    def _count_healthy_unlocked(self) -> int:
        return sum(1 for i in range(len(self._keys)) if self._is_healthy(i))

    @staticmethod
    def _hash_key(key: str) -> str:
        """Return the first 8 hex chars of sha256(key) — safe to log (FR-7)."""
        return hashlib.sha256(key.encode()).hexdigest()[:8]

    def __repr__(self) -> str:
        return (
            f"KeyPool(provider={self._provider!r}, "
            f"size={len(self._keys)}, "
            f"cursor={self._cursor}, "
            f"healthy={self._count_healthy_unlocked()})"
        )
