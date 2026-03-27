"""
Tests for resilience module — Circuit Breaker & Dead-Letter Queue
─────────────────────────────────────────────────────────────────
Coverage:
  1. CircuitBreaker — state transitions, thresholds, recovery, reset
  2. DeadLetterQueue — enqueue, read, count, clear, file format
  3. is_transient — error classification
  4. resilient_post — retry with backoff, circuit integration, DLQ capture
  5. Integration with routes — /resilience/* admin endpoints
"""

import asyncio
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.testclient import TestClient

from resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    DeadLetterQueue,
    is_transient,
    resilient_post,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  CircuitBreaker tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """Tests for circuit breaker state machine."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(service_name="test", failure_threshold=3)
        assert cb.state is CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_allow_request_when_closed(self):
        cb = CircuitBreaker(service_name="test")
        assert cb.allow_request() is True

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(service_name="test", failure_threshold=3)
        cb.record_failure(ValueError("err1"))
        cb.record_failure(ValueError("err2"))
        assert cb.state is CircuitState.CLOSED
        assert cb.failure_count == 2

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(service_name="test", failure_threshold=3)
        for i in range(3):
            cb.record_failure(ValueError(f"err{i}"))
        assert cb.state is CircuitState.OPEN
        assert cb.failure_count == 3

    def test_open_rejects_requests(self):
        cb = CircuitBreaker(service_name="test", failure_threshold=2)
        cb.record_failure(ValueError("e1"))
        cb.record_failure(ValueError("e2"))
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.allow_request()
        assert exc_info.value.service == "test"
        assert exc_info.value.failures == 2

    def test_success_resets_to_closed(self):
        cb = CircuitBreaker(service_name="test", failure_threshold=3)
        cb.record_failure(ValueError("e1"))
        cb.record_failure(ValueError("e2"))
        cb.record_success()
        assert cb.state is CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(
            service_name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
        )
        cb.record_failure(ValueError("err"))
        assert cb.state is CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state is CircuitState.HALF_OPEN

    def test_half_open_allows_one_request(self):
        cb = CircuitBreaker(
            service_name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
        )
        cb.record_failure(ValueError("err"))
        time.sleep(0.15)
        assert cb.allow_request() is True  # half-open probe allowed

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(
            service_name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
        )
        cb.record_failure(ValueError("err"))
        time.sleep(0.15)
        cb.record_success()
        assert cb.state is CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(
            service_name="test",
            failure_threshold=1,
            recovery_timeout=0.1,
        )
        cb.record_failure(ValueError("err"))
        time.sleep(0.15)
        # trigger HALF_OPEN
        assert cb.state is CircuitState.HALF_OPEN
        cb.record_failure(ValueError("probe fail"))
        assert cb.state is CircuitState.OPEN

    def test_manual_reset(self):
        cb = CircuitBreaker(service_name="test", failure_threshold=1)
        cb.record_failure(ValueError("err"))
        assert cb.state is CircuitState.OPEN
        cb.reset()
        assert cb.state is CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_to_dict(self):
        cb = CircuitBreaker(
            service_name="my-service",
            failure_threshold=5,
            recovery_timeout=60.0,
        )
        d = cb.to_dict()
        assert d["service"] == "my-service"
        assert d["state"] == "closed"
        assert d["failure_count"] == 0
        assert d["failure_threshold"] == 5
        assert d["recovery_timeout_s"] == 60.0

    def test_circuit_open_error_fields(self):
        err = CircuitOpenError("svc", failures=5, retry_after=12.3)
        assert err.service == "svc"
        assert err.failures == 5
        assert err.retry_after == 12.3
        assert "svc" in str(err)

    def test_none_error_doesnt_crash(self):
        """record_failure(None) should still work."""
        cb = CircuitBreaker(service_name="test", failure_threshold=5)
        cb.record_failure(None)
        assert cb.failure_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
#  DeadLetterQueue tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeadLetterQueue:
    """Tests for file-backed dead-letter queue."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix="dlq_test_")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_enqueue_creates_file(self):
        dlq = DeadLetterQueue(service_name="test-svc", directory=Path(self.tmpdir))
        dlq.enqueue(
            endpoint="http://example.com/api",
            payload={"key": "value"},
            error=ConnectionError("refused"),
        )
        assert dlq.count() == 1

    def test_enqueue_returns_entry(self):
        dlq = DeadLetterQueue(service_name="test-svc", directory=Path(self.tmpdir))
        entry = dlq.enqueue(
            endpoint="http://example.com/api",
            payload={"k": "v"},
            error=TimeoutError("timeout"),
            attempt=2,
            circuit_state="half_open",
        )
        assert entry["service"] == "test-svc"
        assert entry["endpoint"] == "http://example.com/api"
        assert entry["error_type"] == "TimeoutError"
        assert entry["attempt"] == 2
        assert entry["circuit_state"] == "half_open"

    def test_read_all(self):
        dlq = DeadLetterQueue(service_name="test-svc", directory=Path(self.tmpdir))
        dlq.enqueue("http://a", {"a": 1}, ValueError("e1"))
        dlq.enqueue("http://b", {"b": 2}, OSError("e2"))
        entries = dlq.read_all()
        assert len(entries) == 2
        assert entries[0]["endpoint"] == "http://a"
        assert entries[1]["endpoint"] == "http://b"

    def test_read_all_empty(self):
        dlq = DeadLetterQueue(service_name="new-svc", directory=Path(self.tmpdir))
        assert dlq.read_all() == []

    def test_count(self):
        dlq = DeadLetterQueue(service_name="test-svc", directory=Path(self.tmpdir))
        assert dlq.count() == 0
        dlq.enqueue("http://a", {}, ValueError("e"))
        assert dlq.count() == 1
        dlq.enqueue("http://b", {}, ValueError("e"))
        assert dlq.count() == 2

    def test_clear(self):
        dlq = DeadLetterQueue(service_name="test-svc", directory=Path(self.tmpdir))
        dlq.enqueue("http://a", {}, ValueError("e"))
        dlq.enqueue("http://b", {}, ValueError("e"))
        purged = dlq.clear()
        assert purged == 2
        assert dlq.count() == 0

    def test_clear_empty(self):
        dlq = DeadLetterQueue(service_name="test-svc", directory=Path(self.tmpdir))
        purged = dlq.clear()
        assert purged == 0

    def test_file_is_jsonl(self):
        dlq = DeadLetterQueue(service_name="test-svc", directory=Path(self.tmpdir))
        dlq.enqueue("http://a", {"x": 1}, ValueError("e1"))
        dlq.enqueue("http://b", {"y": 2}, ValueError("e2"))
        with open(dlq._file_path, "r") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert "timestamp" in parsed

    def test_extra_field(self):
        dlq = DeadLetterQueue(service_name="test-svc", directory=Path(self.tmpdir))
        entry = dlq.enqueue(
            "http://a", {}, ValueError("e"), extra={"editor": "Dr. Jones"}
        )
        assert entry["extra"]["editor"] == "Dr. Jones"

    def test_to_dict(self):
        dlq = DeadLetterQueue(service_name="my-svc", directory=Path(self.tmpdir))
        d = dlq.to_dict()
        assert d["service"] == "my-svc"
        assert d["count"] == 0

    def test_safe_filename(self):
        dlq = DeadLetterQueue(service_name="my/service name", directory=Path(self.tmpdir))
        assert "my_service_name" in dlq._file_path.name


# ═══════════════════════════════════════════════════════════════════════════════
#  is_transient tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsTransient:
    """Tests for error classification."""

    def test_connect_error_is_transient(self):
        assert is_transient(httpx.ConnectError("refused")) is True

    def test_connect_timeout_is_transient(self):
        assert is_transient(httpx.ConnectTimeout("timeout")) is True

    def test_read_timeout_is_transient(self):
        assert is_transient(httpx.ReadTimeout("timeout")) is True

    def test_connection_error_is_transient(self):
        assert is_transient(ConnectionError("reset")) is True

    def test_timeout_error_is_transient(self):
        assert is_transient(TimeoutError("timed out")) is True

    def test_os_error_is_transient(self):
        assert is_transient(OSError("network")) is True

    def test_value_error_is_not_transient(self):
        assert is_transient(ValueError("bad input")) is False

    def test_key_error_is_not_transient(self):
        assert is_transient(KeyError("missing")) is False

    def test_http_500_is_transient(self):
        resp = httpx.Response(500, request=httpx.Request("POST", "http://x"))
        err = httpx.HTTPStatusError("500", request=resp.request, response=resp)
        assert is_transient(err) is True

    def test_http_503_is_transient(self):
        resp = httpx.Response(503, request=httpx.Request("POST", "http://x"))
        err = httpx.HTTPStatusError("503", request=resp.request, response=resp)
        assert is_transient(err) is True

    def test_http_400_is_not_transient(self):
        resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
        err = httpx.HTTPStatusError("400", request=resp.request, response=resp)
        assert is_transient(err) is False

    def test_http_404_is_not_transient(self):
        resp = httpx.Response(404, request=httpx.Request("POST", "http://x"))
        err = httpx.HTTPStatusError("404", request=resp.request, response=resp)
        assert is_transient(err) is False


# ═══════════════════════════════════════════════════════════════════════════════
#  resilient_post tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestResilientPost:
    """Tests for the async retry + circuit breaker + DLQ wrapper."""

    def _make_deps(self, tmpdir: str):
        breaker = CircuitBreaker(service_name="test-post", failure_threshold=3)
        dlq = DeadLetterQueue(service_name="test-post", directory=Path(tmpdir))
        return breaker, dlq

    @pytest.mark.asyncio
    async def test_success_on_first_try(self, tmp_path):
        breaker, dlq = self._make_deps(str(tmp_path))
        mock_resp = httpx.Response(
            200,
            json={"ok": True},
            request=httpx.Request("POST", "http://test/api"),
        )
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await resilient_post(
                url="http://test/api",
                json_payload={"data": 1},
                breaker=breaker,
                dlq=dlq,
                max_retries=3,
            )
            assert resp.status_code == 200
            assert breaker.failure_count == 0
            assert dlq.count() == 0

    @pytest.mark.asyncio
    async def test_rejects_when_circuit_open(self, tmp_path):
        breaker, dlq = self._make_deps(str(tmp_path))
        # Force open
        for _ in range(3):
            breaker.record_failure(ValueError("err"))
        with pytest.raises(CircuitOpenError):
            await resilient_post(
                url="http://test/api",
                json_payload={},
                breaker=breaker,
                dlq=dlq,
            )

    @pytest.mark.asyncio
    async def test_permanent_error_no_retry(self, tmp_path):
        """Non-transient errors (e.g. ValueError) should not be retried."""
        breaker, dlq = self._make_deps(str(tmp_path))
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = ValueError("bad payload")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError):
                await resilient_post(
                    url="http://test/api",
                    json_payload={},
                    breaker=breaker,
                    dlq=dlq,
                    max_retries=3,
                )
            # Should have been called only once (no retry for permanent error)
            assert mock_client.post.call_count == 1
            assert dlq.count() == 1

    @pytest.mark.asyncio
    async def test_dlq_on_exhaustion(self, tmp_path):
        """After max retries, the request should land in the DLQ."""
        breaker, dlq = self._make_deps(str(tmp_path))
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("refused")
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.ConnectError):
                await resilient_post(
                    url="http://test/api",
                    json_payload={"ms": "MS-999"},
                    breaker=breaker,
                    dlq=dlq,
                    max_retries=2,
                    backoff_factor=0.01,  # fast for tests
                )
            assert dlq.count() == 1
            entry = dlq.read_all()[0]
            assert entry["endpoint"] == "http://test/api"
            assert entry["error_type"] == "ConnectError"


# ═══════════════════════════════════════════════════════════════════════════════
#  Resilience admin endpoint tests (LangGraph)
# ═══════════════════════════════════════════════════════════════════════════════


class TestResilienceEndpoints:
    """Tests for the /resilience/* REST endpoints on LangGraph :8000."""

    @pytest.fixture(autouse=True)
    def _setup_app(self):
        """Reset breaker and DLQ before each test."""
        from langgraph_service.routes import strands_breaker, strands_dlq
        strands_breaker.reset()
        strands_dlq.clear()

        from langgraph_service.callback_server import app
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_status_endpoint(self):
        resp = self.client.get("/resilience/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["circuit_breaker"]["state"] == "closed"
        assert data["dlq"]["count"] == 0

    def test_dlq_endpoint_empty(self):
        resp = self.client.get("/resilience/dlq")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        assert resp.json()["entries"] == []

    def test_dlq_clear_endpoint(self):
        resp = self.client.post("/resilience/dlq/clear")
        assert resp.status_code == 200
        assert resp.json()["purged"] == 0

    def test_reset_endpoint(self):
        from langgraph_service.routes import strands_breaker
        strands_breaker.record_failure(ValueError("err"))
        resp = self.client.post("/resilience/reset")
        assert resp.status_code == 200
        assert resp.json()["circuit_breaker"]["state"] == "closed"

    def test_status_reflects_failure(self):
        from langgraph_service.routes import strands_breaker
        strands_breaker.record_failure(ValueError("e1"))
        strands_breaker.record_failure(ValueError("e2"))
        resp = self.client.get("/resilience/status")
        data = resp.json()
        assert data["circuit_breaker"]["failure_count"] == 2
        assert data["circuit_breaker"]["state"] == "closed"
