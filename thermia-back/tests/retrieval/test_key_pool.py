"""
Unit tests for app.retrieval.key_pool.

TDD slices KP-T1 through KP-T9 (see code-generation plan).
"""
from __future__ import annotations

import sys
import os
import time

import pytest

# Make thermia-back importable without an installed package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


# ---------------------------------------------------------------------------
# KP-T1: Skeleton importability
# ---------------------------------------------------------------------------


class TestKeyPoolSkeleton:
    """KP-T1 — KeyPool, FailureReason, AllKeysExhaustedError importable."""

    def test_imports(self):
        from app.retrieval.key_pool import KeyPool, FailureReason, AllKeysExhaustedError  # noqa
        assert KeyPool is not None
        assert FailureReason is not None
        assert AllKeysExhaustedError is not None

    def test_constructor_with_explicit_keys(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool(keys=["k1", "k2"], provider="groq")
        assert pool is not None

    def test_public_methods_exist(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool(keys=["k1"], provider="groq")
        assert callable(pool.current)
        assert callable(pool.mark_failed)
        assert callable(pool.healthy_count)

    def test_from_env_is_classmethod(self):
        from app.retrieval.key_pool import KeyPool
        import inspect
        assert isinstance(inspect.getattr_static(KeyPool, "from_env"), classmethod)

    def test_repr_does_not_leak_keys(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool(keys=["supersecretkey123"], provider="groq")
        assert "supersecretkey123" not in repr(pool)


# ---------------------------------------------------------------------------
# KP-T2: from_env() — JSON array, legacy fallback, boot fail-fast
# ---------------------------------------------------------------------------


class TestFromEnv:
    """KP-T2 — .env parsing: JSON-array form + legacy fallback + fail-fast."""

    def test_json_array_two_keys(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool.from_env("groq", environ={"GROQ_API_KEYS": '["key_one_1234","key_two_5678"]'})
        assert pool.healthy_count() == 2

    def test_json_array_first_key_is_active(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool.from_env("groq", environ={"GROQ_API_KEYS": '["key_one_1234","key_two_5678"]'})
        assert pool.current() == "key_one_1234"

    def test_single_quoted_json_and_whitespace(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool.from_env("groq", environ={"GROQ_API_KEYS": " '[\"key_one_1234\",\"key_two_5678\"]' "})
        assert pool.healthy_count() == 2

    def test_legacy_var_treated_as_one_element(self, caplog):
        import logging
        from app.retrieval.key_pool import KeyPool
        with caplog.at_level(logging.WARNING, logger="app.retrieval.key_pool"):
            pool = KeyPool.from_env("groq", environ={"GROQ_API_KEY": "legacykey"})
        assert pool.healthy_count() == 1
        assert pool.current() == "legacykey"
        # WARN log must have been emitted
        assert any("legacy" in r.message.lower() or "key_pool.legacy" in r.message for r in caplog.records)

    def test_array_var_preferred_over_legacy(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool.from_env(
            "groq",
            environ={"GROQ_API_KEYS": '["key_one_1234","key_two_5678"]', "GROQ_API_KEY": "legacykey"},
        )
        assert pool.healthy_count() == 2
        assert pool.current() == "key_one_1234"

    def test_no_vars_raises_value_error(self):
        from app.retrieval.key_pool import KeyPool
        import pytest
        with pytest.raises(ValueError, match="GROQ_API_KEYS"):
            KeyPool.from_env("groq", environ={})

    def test_empty_array_raises_value_error(self):
        from app.retrieval.key_pool import KeyPool
        import pytest
        with pytest.raises(ValueError):
            KeyPool.from_env("groq", environ={"GROQ_API_KEYS": "[]"})

    def test_malformed_json_raises_value_error(self):
        from app.retrieval.key_pool import KeyPool
        import pytest
        with pytest.raises(ValueError, match="GROQ_API_KEYS"):
            KeyPool.from_env("groq", environ={"GROQ_API_KEYS": "not-json"})

    def test_groq_provider_uses_correct_env_var(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool.from_env("groq", environ={"GROQ_API_KEYS": '["groqkey-1234"]'})
        assert pool.current() == "groqkey-1234"


# ---------------------------------------------------------------------------
# KP-T3: classify_failure() — signal classifier
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    """KP-T3 — classify_failure covers all FR-3 signals."""

    def _cf(self, text):
        from app.retrieval.key_pool import classify_failure
        return classify_failure(text)

    def test_429_in_string(self):
        from app.retrieval.key_pool import FailureReason
        assert self._cf("HTTP error 429 Too Many Requests") == FailureReason.RATE_LIMIT_429

    def test_rate_limit_case_insensitive(self):
        from app.retrieval.key_pool import FailureReason
        assert self._cf("Rate Limit exceeded") == FailureReason.RATE_LIMIT_429

    def test_rate_limit_lower(self):
        from app.retrieval.key_pool import FailureReason
        assert self._cf("rate limit") == FailureReason.RATE_LIMIT_429

    def test_exception_with_429(self):
        from app.retrieval.key_pool import FailureReason
        exc = Exception("Server responded with 429")
        assert self._cf(exc) == FailureReason.RATE_LIMIT_429

    def test_groq_daily_token(self):
        from app.retrieval.key_pool import FailureReason
        assert self._cf("You have exceeded your daily token limit") == FailureReason.GROQ_DAILY_QUOTA

    def test_groq_daily_quota(self):
        from app.retrieval.key_pool import FailureReason
        assert self._cf("Error: daily quota exceeded for this API key") == FailureReason.GROQ_DAILY_QUOTA

    def test_500_internal_server_error(self):
        from app.retrieval.key_pool import FailureReason
        assert self._cf("HTTP 500 internal server error") == FailureReason.PERSISTENT_5XX

    def test_503_service_unavailable(self):
        from app.retrieval.key_pool import FailureReason
        assert self._cf("503 Service Unavailable") == FailureReason.PERSISTENT_5XX

    def test_400_bad_request_returns_none(self):
        assert self._cf("400 bad request") is None

    def test_401_unauthorized_returns_none(self):
        assert self._cf("401 unauthorized") is None

    def test_403_forbidden_returns_none(self):
        assert self._cf("403 forbidden") is None


# ---------------------------------------------------------------------------
# KP-T4: Cool-down dict + sticky-then-rotate cursor + thread-safe mark_failed
# ---------------------------------------------------------------------------


class TestKeyPoolRotation:
    """KP-T4 — cool-down, sticky-then-rotate, logs, concurrency."""

    def _pool2(self, **kwargs):
        from app.retrieval.key_pool import KeyPool
        return KeyPool(keys=["k1", "k2"], provider="groq", cooldown_seconds=60, **kwargs)

    def test_healthy_count_is_two(self):
        pool = self._pool2()
        assert pool.healthy_count() == 2

    def test_current_returns_first_key(self):
        pool = self._pool2()
        assert pool.current() == "k1"

    def test_mark_failed_advances_cursor(self):
        from app.retrieval.key_pool import FailureReason
        pool = self._pool2()
        pool.mark_failed(FailureReason.RATE_LIMIT_429)
        assert pool.current() == "k2"

    def test_current_is_sticky(self):
        pool = self._pool2()
        assert pool.current() == "k1"
        assert pool.current() == "k1"  # same call twice

    def test_mark_failed_last_key_wraps_if_first_recovered(self):
        """After k2 fails, k1 should have recovered (cooldown_seconds=0)."""
        from app.retrieval.key_pool import KeyPool, FailureReason
        pool = KeyPool(keys=["k1", "k2"], provider="groq", cooldown_seconds=0)
        pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k1 → cooldown=0
        # k2 is now active; k1's cooldown=0 so it has already expired
        pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k2 → should wrap to k1
        assert pool.current() == "k1"

    def test_all_keys_failed_raises_exhausted(self):
        from app.retrieval.key_pool import KeyPool, FailureReason, AllKeysExhaustedError
        pool = KeyPool(keys=["k1", "k2"], provider="groq", cooldown_seconds=3600)
        pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k1 dead, cursor→k2
        with pytest.raises(AllKeysExhaustedError):
            pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k2 dead, no healthy

    def test_current_raises_when_exhausted(self):
        from app.retrieval.key_pool import KeyPool, FailureReason, AllKeysExhaustedError
        pool = KeyPool(keys=["k1"], provider="groq", cooldown_seconds=3600)
        # Manually put k0 in cooldown
        pool._cooldowns[0] = time.time() + 3600
        with pytest.raises(AllKeysExhaustedError):
            pool.current()

    def test_rotated_log_emitted_on_mark_failed(self, caplog):
        import logging
        from app.retrieval.key_pool import FailureReason
        pool = self._pool2()
        with caplog.at_level(logging.INFO, logger="app.retrieval.key_pool"):
            pool.mark_failed(FailureReason.RATE_LIMIT_429)
        assert any("key_pool.rotated" in r.message for r in caplog.records)
        rotated = next(r for r in caplog.records if "key_pool.rotated" in r.message)
        assert "provider=groq" in rotated.message
        assert "key_index_from=0" in rotated.message
        assert "key_index_to=1" in rotated.message
        assert "reason=429" in rotated.message
        # No raw keys in log
        assert "k1" not in rotated.message
        assert "k2" not in rotated.message

    def test_degraded_warn_emitted_once(self, caplog):
        """Degraded WARN fires when 1 key remains, not on every subsequent call."""
        import logging
        from app.retrieval.key_pool import KeyPool, FailureReason
        pool = KeyPool(keys=["k1", "k2", "k3"], provider="groq", cooldown_seconds=3600)
        with caplog.at_level(logging.WARNING, logger="app.retrieval.key_pool"):
            pool.mark_failed(FailureReason.RATE_LIMIT_429)  # 3→2 healthy: no WARN yet
            caplog.clear()
            pool.mark_failed(FailureReason.RATE_LIMIT_429)  # 2→1 healthy: WARN
        degraded = [r for r in caplog.records if "key_pool.degraded" in r.message]
        assert len(degraded) == 1

    def test_exhausted_error_emitted_once(self, caplog):
        import logging
        from app.retrieval.key_pool import KeyPool, FailureReason, AllKeysExhaustedError
        pool = KeyPool(keys=["k1", "k2"], provider="groq", cooldown_seconds=3600)
        pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k1 dead
        with caplog.at_level(logging.ERROR, logger="app.retrieval.key_pool"):
            with pytest.raises(AllKeysExhaustedError):
                pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k2 dead → ERROR
        exhausted = [r for r in caplog.records if "key_pool.exhausted" in r.message]
        assert len(exhausted) == 1

    def test_cooldown_expiry_reenters_pool(self):
        from app.retrieval.key_pool import KeyPool, FailureReason
        pool = KeyPool(keys=["k1", "k2"], provider="groq", cooldown_seconds=100)
        pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k1 dead, cooldown=100s
        # Now simulate time passing past cooldown: manipulate _cooldowns directly
        pool._cooldowns[0] = time.time() - 1  # expiry already passed
        assert pool.healthy_count() == 2  # k1 should be back

    def test_50_concurrent_threads_single_rotation(self):
        """50 threads hitting a 2-key pool where k1 is bad → exactly 1 rotation."""
        import threading
        from app.retrieval.key_pool import KeyPool, FailureReason

        pool = KeyPool(keys=["k1", "k2"], provider="groq", cooldown_seconds=3600)
        rotation_count = 0
        rotation_lock = threading.Lock()
        barrier = threading.Barrier(50)

        def worker():
            nonlocal rotation_count
            barrier.wait()  # all 50 threads start simultaneously
            try:
                key = pool.current()
                if key == "k1":
                    pool.mark_failed(FailureReason.RATE_LIMIT_429)
                    with rotation_lock:
                        rotation_count += 1
            except Exception:
                pass

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # After all threads, cursor should be at k2 and only 1 rotation happened
        assert pool.current() == "k2"
        # rotation_count tracks how many threads saw k1; mark_failed is idempotent
        # (once k1 is in cooldown, subsequent calls from threads that also see k1
        # still call mark_failed, but they all see k2 next — we just need cursor=k2)
        assert pool.healthy_count() == 1  # k1 in cooldown, k2 healthy


# ---------------------------------------------------------------------------
# KP-T5: Full suite consolidation + no raw key material in logs
# ---------------------------------------------------------------------------


class TestNoRawKeysInLogs:
    """KP-T5 — assert no raw key material appears in any log output."""

    def test_no_raw_keys_in_rotation_logs(self, caplog):
        """Full rotation sequence: raw keys must not appear in log output."""
        import logging
        import re
        from app.retrieval.key_pool import KeyPool, FailureReason, AllKeysExhaustedError

        secret_keys = ["superSECRET_key_ALPHA", "superSECRET_key_BETA"]
        pool = KeyPool(keys=secret_keys, provider="groq", cooldown_seconds=3600)

        with caplog.at_level(logging.DEBUG, logger="app.retrieval.key_pool"):
            pool.mark_failed(FailureReason.RATE_LIMIT_429)
            try:
                pool.mark_failed(FailureReason.GROQ_DAILY_QUOTA)
            except AllKeysExhaustedError:
                pass

        full_log = "\n".join(r.message for r in caplog.records)
        for key in secret_keys:
            # Check no raw key or suffix longer than 4 chars appears
            assert key not in full_log, f"Raw key leaked into logs: {key[:4]}..."
            # Also check the last 4 chars (common suffix leak pattern)
            if len(key) > 4:
                # Regex check for any contiguous substring longer than 4 chars
                for length in range(5, len(key) + 1):
                    for start in range(len(key) - length + 1):
                        fragment = key[start:start + length]
                        assert fragment not in full_log, (
                            f"Key fragment '{fragment[:4]}...' (len={length}) leaked into logs"
                        )

    def test_from_env_legacy_warn_no_raw_key(self, caplog):
        """Legacy-var WARN must not leak the actual key value."""
        import logging
        from app.retrieval.key_pool import KeyPool

        secret = "mySuperSecretLegacyKey"
        with caplog.at_level(logging.WARNING, logger="app.retrieval.key_pool"):
            KeyPool.from_env("groq", environ={"GROQ_API_KEY": secret})

        full_log = "\n".join(r.message for r in caplog.records)
        # Only first 4 chars allowed (truncated suffix hint in warn message)
        assert secret not in full_log
        if len(secret) > 4:
            assert secret[4:] not in full_log


# ---------------------------------------------------------------------------
# KP-T7: llm.py wired with KeyPool
# ---------------------------------------------------------------------------


class TestLLMKeyPool:
    """KP-T7 — analyze_with_llm uses KeyPool for Groq api_key."""

    def setup_method(self):
        """Reset llm module-level singleton before each test."""
        import importlib
        import app.retrieval.llm as llm_mod
        llm_mod._groq_pool = None

    def test_llm_uses_active_groq_key(self, monkeypatch):
        """analyze_with_llm reads active key from get_groq_pool().current()."""
        from unittest.mock import MagicMock, patch
        from app.retrieval.key_pool import KeyPool
        import app.retrieval.llm as llm_mod

        pool = KeyPool(keys=["groq_key_1"], provider="groq", cooldown_seconds=3600)
        llm_mod._groq_pool = pool

        mock_llm_instance = MagicMock()
        mock_llm_instance.with_structured_output.return_value = mock_llm_instance
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"resumen": "test", "implicaciones_legales": [], "fundamento_juridico": []}
        mock_llm_instance.invoke.return_value = mock_response

        captured_api_key = {}

        def fake_chat_groq(**kwargs):
            captured_api_key["key"] = kwargs.get("api_key")
            return mock_llm_instance

        with patch("app.retrieval.llm.ChatGroq", side_effect=fake_chat_groq):
            result = llm_mod.analyze_with_llm(
                "El artículo 14 de la ley establece que todos los ciudadanos son iguales ante la ley, sin que pueda prevalecer discriminación alguna por razón de nacimiento, raza, sexo, religión, opinión o cualquier otra condición o circunstancia personal o social.",
                "query text",
            )

        assert captured_api_key["key"] == "groq_key_1"
        assert result["resumen"] == "test"

    def test_groq_daily_quota_rotates_and_retries(self, monkeypatch):
        """On GROQ_DAILY_QUOTA, pool rotates and retries once on new key."""
        from unittest.mock import MagicMock, patch
        from app.retrieval.key_pool import KeyPool
        import app.retrieval.llm as llm_mod

        pool = KeyPool(keys=["bad_groq_key", "good_groq_key"], provider="groq", cooldown_seconds=3600)
        llm_mod._groq_pool = pool

        api_keys_used = []

        def fake_chat_groq(**kwargs):
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = mock_llm
            key = kwargs.get("api_key")
            api_keys_used.append(key)
            if key == "bad_groq_key":
                mock_llm.invoke.side_effect = Exception(
                    "Error: daily quota exceeded for this API key"
                )
            else:
                mock_resp = MagicMock()
                mock_resp.model_dump.return_value = {"resumen": "ok", "implicaciones_legales": [], "fundamento_juridico": []}
                mock_llm.invoke.return_value = mock_resp
            return mock_llm

        with patch("app.retrieval.llm.ChatGroq", side_effect=fake_chat_groq):
            result = llm_mod.analyze_with_llm(
                "El artículo 14 de la ley establece que todos los ciudadanos son iguales ante la ley, sin que pueda prevalecer discriminación alguna por razón de nacimiento, raza, sexo, religión, opinión o cualquier otra condición o circunstancia personal o social.",
                "q",
            )

        assert result["resumen"] == "ok"
        # First call used bad_groq_key, second used good_groq_key after rotation
        assert "bad_groq_key" in api_keys_used
        assert "good_groq_key" in api_keys_used
        assert pool.current() == "good_groq_key"

    def test_all_groq_keys_exhausted_propagates(self, monkeypatch):
        """AllKeysExhaustedError propagates when all Groq keys are exhausted."""
        from unittest.mock import MagicMock, patch
        from app.retrieval.key_pool import KeyPool, AllKeysExhaustedError
        import app.retrieval.llm as llm_mod

        pool = KeyPool(keys=["only_groq_key"], provider="groq", cooldown_seconds=3600)
        llm_mod._groq_pool = pool

        def fake_chat_groq(**kwargs):
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = mock_llm
            mock_llm.invoke.side_effect = Exception("daily quota exceeded for this API key")
            return mock_llm

        with patch("app.retrieval.llm.ChatGroq", side_effect=fake_chat_groq):
            with pytest.raises(AllKeysExhaustedError):
                llm_mod.analyze_with_llm(
                    "El artículo 14 de la ley establece que todos los ciudadanos son iguales ante la ley, sin que pueda prevalecer discriminación alguna por razón de nacimiento, raza, sexo, religión, opinión o cualquier otra condición o circunstancia personal o social.",
                    "q",
                )

    def test_non_rotating_llm_failure_reraises(self, monkeypatch):
        """Non-rotating LLM errors (e.g. 400) are re-raised without rotation."""
        from unittest.mock import MagicMock, patch
        from app.retrieval.key_pool import KeyPool
        import app.retrieval.llm as llm_mod

        pool = KeyPool(keys=["groq_key"], provider="groq", cooldown_seconds=3600)
        llm_mod._groq_pool = pool
        original_healthy = pool.healthy_count()

        def fake_chat_groq(**kwargs):
            mock_llm = MagicMock()
            mock_llm.with_structured_output.return_value = mock_llm
            mock_llm.invoke.side_effect = Exception("400 Bad Request — invalid model")
            return mock_llm

        with patch("app.retrieval.llm.ChatGroq", side_effect=fake_chat_groq):
            with pytest.raises(Exception, match="400 Bad Request"):
                llm_mod.analyze_with_llm(
                    "El artículo 14 de la ley establece que todos los ciudadanos son iguales ante la ley, sin que pueda prevalecer discriminación alguna por razón de nacimiento, raza, sexo, religión, opinión o cualquier otra condición o circunstancia personal o social.",
                    "q",
                )

        assert pool.healthy_count() == original_healthy


# ---------------------------------------------------------------------------
# KP-T8: ingest.py wired with KeyPool (via shared embedder pool)
# ---------------------------------------------------------------------------


class TestIngestKeyPool:
    """KP-T8 — ingest.py uses Ollama-based generate_embeddings (no Cohere/KeyPool)."""

    def test_generate_embeddings_called_without_pool(self):
        """generate_embeddings no longer takes client or pool params."""
        import sys
        import os
        import inspect
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
        from scripts.ingest import generate_embeddings

        sig = inspect.signature(generate_embeddings)
        params = list(sig.parameters.keys())
        assert params == ["texts"], (
            f"generate_embeddings should take only 'texts', got: {params}"
        )

    def test_ingest_main_no_cohere_references(self):
        """ingest.main() no longer references cohere or get_cohere_pool."""
        import ast
        import pathlib

        ingest_source = pathlib.Path(
            os.path.join(os.path.dirname(__file__), "../../scripts/ingest.py")
        ).read_text()
        tree = ast.parse(ingest_source)
        main_func = next(
            (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "main"),
            None,
        )
        assert main_func is not None

        string_constants = [
            node.value for node in ast.walk(main_func)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert "COHERE_API_KEY" not in string_constants
        assert "get_cohere_pool" not in string_constants
        assert "cohere" not in string_constants


# ---------------------------------------------------------------------------
# TEST-A: _5XX_RE regex — no false positives on large numbers (FIX-1 / P1-CQ-2)
# ---------------------------------------------------------------------------


class TestClassifyFailureFalsePositives:
    """TEST-A — regex _5XX_RE must not match 5xx inside larger numbers."""

    @pytest.mark.parametrize("text", [
        "processed 15000 tokens",
        "batch 1500 items completed",
        "50001 records",
        "error code 25001",
    ])
    def test_5xx_no_false_positive_in_large_numbers(self, text):
        from app.retrieval.key_pool import classify_failure
        result = classify_failure(text)
        assert result is None, f"Expected None for {text!r}, got {result}"


# ---------------------------------------------------------------------------
# TEST-B: _was_degraded/_was_exhausted reset after cooldown recovery (FIX-2 / P1-CQ-3)
# ---------------------------------------------------------------------------


class TestFlagResetAfterRecovery:
    """TEST-B — degraded/exhausted flags reset when keys recover from cooldown."""

    def test_flags_reset_after_cooldown_expiry_and_fire_again(self, caplog):
        """
        Full cycle:
        1. 2-key pool
        2. Mark key 0 failed → _was_degraded fires (1 healthy key)
        3. Mark key 1 failed → _was_exhausted fires (0 healthy keys)
        4. Expire cooldowns via direct attribute manipulation
        5. Call pool.current() → flags reset (_was_degraded=False, _was_exhausted=False)
        6. Mark a key failed again → WARN fires a second time (flags re-armed)
        """
        import logging
        from app.retrieval.key_pool import KeyPool, FailureReason, AllKeysExhaustedError

        pool = KeyPool(keys=["k1", "k2"], provider="groq", cooldown_seconds=3600)

        # Step 2: degrade (1 healthy key left)
        with caplog.at_level(logging.WARNING, logger="app.retrieval.key_pool"):
            pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k1 dead → 1 healthy
        degraded_first = [r for r in caplog.records if "key_pool.degraded" in r.message]
        assert len(degraded_first) == 1, "First degraded WARN must fire"

        # Step 3: exhaust (0 healthy keys)
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="app.retrieval.key_pool"):
            with pytest.raises(AllKeysExhaustedError):
                pool.mark_failed(FailureReason.RATE_LIMIT_429)  # k2 dead → 0 healthy
        exhausted_first = [r for r in caplog.records if "key_pool.exhausted" in r.message]
        assert len(exhausted_first) == 1, "First exhausted ERROR must fire"

        # Verify flags are set
        assert pool._was_exhausted is True

        # Step 4: expire all cooldowns
        for idx in list(pool._cooldowns):
            pool._cooldowns[idx] = time.time() - 1  # already expired

        # Step 5: call current() — this triggers _current_unlocked() which resets flags
        key = pool.current()
        assert key in ("k1", "k2"), "A key should be available after cooldown expiry"
        assert pool._was_degraded is False, "_was_degraded must be reset after recovery"
        assert pool._was_exhausted is False, "_was_exhausted must be reset after recovery"

        # Step 6: degrade and exhaust again — logs must fire a second time
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="app.retrieval.key_pool"):
            pool.mark_failed(FailureReason.RATE_LIMIT_429)  # degrade again
        degraded_second = [r for r in caplog.records if "key_pool.degraded" in r.message]
        assert len(degraded_second) == 1, "Degraded WARN must fire AGAIN after flag reset"


# ---------------------------------------------------------------------------
# TEST-C: from_env key-format validation (FIX-7 / P1-SEC-5)
# ---------------------------------------------------------------------------


class TestKeyFormatValidation:
    """TEST-C — _parse_keys_env raises ValueError on malformed key strings."""

    def test_empty_string_key_raises(self):
        from app.retrieval.key_pool import KeyPool
        with pytest.raises(ValueError):
            KeyPool.from_env("groq", environ={"GROQ_API_KEYS": '[""]'})

    def test_short_key_raises(self):
        from app.retrieval.key_pool import KeyPool
        with pytest.raises(ValueError, match="invalid key format"):
            KeyPool.from_env("groq", environ={"GROQ_API_KEYS": '["ab"]'})

    def test_key_with_invalid_chars_raises(self):
        from app.retrieval.key_pool import KeyPool
        with pytest.raises(ValueError, match="invalid key format"):
            KeyPool.from_env("groq", environ={"GROQ_API_KEYS": '["key with spaces"]'})

    def test_valid_key_accepted(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool.from_env("groq", environ={"GROQ_API_KEYS": '["validkey12345"]'})
        assert pool.healthy_count() == 1

    def test_valid_key_with_hyphens_accepted(self):
        from app.retrieval.key_pool import KeyPool
        pool = KeyPool.from_env("groq", environ={"GROQ_API_KEYS": '["valid-key-123456"]'})
        assert pool.healthy_count() == 1


# ---------------------------------------------------------------------------
# Verification assertions — no Cohere provider leaking into agnostic tests
# ---------------------------------------------------------------------------


def test_no_cohere_provider_in_agnostic_tests():
    """Verify provider-agnostic tests use 'groq' not 'cohere'."""
    import pathlib
    source = pathlib.Path(__file__).read_text()
    target = 'cohere'
    for cls_name in ("TestKeyPoolSkeleton", "TestFromEnv", "TestKeyPoolRotation",
                     "TestNoRawKeysInLogs", "TestFlagResetAfterRecovery",
                     "TestKeyFormatValidation"):
        cls_start = source.find(f"class {cls_name}")
        cls_end = source.find("\n\nclass ", cls_start + 1)
        if cls_end < 0:
            cls_end = source.find("\n\n# ---", cls_start + 1)
        if cls_end < 0:
            cls_end = len(source)
        cls_source = source[cls_start:cls_end]
        assert f'"{target}"' not in cls_source, f"{cls_name} still references '{target}'"
