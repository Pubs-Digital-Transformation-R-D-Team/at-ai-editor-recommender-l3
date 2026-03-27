"""
Resilience — Circuit Breaker & Dead-Letter Queue
─────────────────────────────────────────────────
Shared infrastructure-level resilience for inter-service HTTP calls.

Circuit Breaker
    Prevents cascading failures by tracking consecutive errors for a
    downstream service.  After ``failure_threshold`` consecutive failures
    the breaker *opens* and immediately rejects calls for ``recovery_timeout``
    seconds.  After the timeout a *half-open* probe is allowed through — if
    it succeeds the breaker closes, otherwise it reopens.

Dead-Letter Queue (DLQ)
    Captures failed requests (with full payload, error info, and timestamps)
    in an append-only JSON-lines file so they can be inspected, replayed,
    or forwarded to an external system later.

Both components are dependency-free (stdlib only) and thread-safe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  Circuit Breaker
# ═══════════════════════════════════════════════════════════════════════════════

class CircuitState(Enum):
    CLOSED = "closed"        # normal — requests pass through
    OPEN = "open"            # failing — requests rejected immediately
    HALF_OPEN = "half_open"  # probing — one request allowed to test


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""

    def __init__(self, service: str, failures: int, retry_after: float):
        self.service = service
        self.failures = failures
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker OPEN for '{service}' — "
            f"{failures} consecutive failures, retry after {retry_after:.0f}s"
        )


@dataclass
class CircuitBreaker:
    """Per-service circuit breaker.

    Parameters
    ----------
    service_name:
        Human-readable label (e.g. ``"strands-coi"``, ``"langgraph"``).
    failure_threshold:
        Number of consecutive failures before the breaker opens.
    recovery_timeout:
        Seconds to wait before allowing a half-open probe.
    """

    service_name: str
    failure_threshold: int = 3
    recovery_timeout: float = 30.0

    # ── internal state ───────────────────────────────────────────────────────
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    # ── public properties ────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state is CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info(
                        "[CircuitBreaker:%s] Transition → HALF_OPEN (probing)",
                        self.service_name,
                    )
            return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    # ── gate check ───────────────────────────────────────────────────────────

    def allow_request(self) -> bool:
        """Return True if a request should be attempted.

        Raises ``CircuitOpenError`` if the circuit is open.
        """
        st = self.state  # triggers the OPEN → HALF_OPEN transition if timer elapsed
        if st is CircuitState.OPEN:
            retry_after = self.recovery_timeout - (time.time() - self._last_failure_time)
            raise CircuitOpenError(
                self.service_name,
                self._failure_count,
                max(retry_after, 0),
            )
        return True

    # ── outcome recording ────────────────────────────────────────────────────

    def record_success(self) -> None:
        """Record a successful call — resets the breaker to CLOSED."""
        with self._lock:
            prev = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            if prev is not CircuitState.CLOSED:
                logger.info(
                    "[CircuitBreaker:%s] ← Success — CLOSED (reset)",
                    self.service_name,
                )

    def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed call.  Opens the breaker if threshold exceeded."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "[CircuitBreaker:%s] ← Failure #%d (%s) — OPEN (blocking for %.0fs)",
                    self.service_name,
                    self._failure_count,
                    type(error).__name__ if error else "unknown",
                    self.recovery_timeout,
                )
            else:
                logger.info(
                    "[CircuitBreaker:%s] ← Failure #%d/%d (%s) — still CLOSED",
                    self.service_name,
                    self._failure_count,
                    self.failure_threshold,
                    type(error).__name__ if error else "unknown",
                )

    def reset(self) -> None:
        """Manually reset the breaker to CLOSED."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0
            logger.info("[CircuitBreaker:%s] Manual RESET → CLOSED", self.service_name)

    def to_dict(self) -> dict:
        """Snapshot for health/status endpoints."""
        return {
            "service": self.service_name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_s": self.recovery_timeout,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  Dead-Letter Queue (file-backed)
# ═══════════════════════════════════════════════════════════════════════════════

DLQ_DIR = Path(os.getenv("DLQ_DIR", ".dlq"))


@dataclass
class DeadLetterQueue:
    """Append-only JSON-lines queue for failed requests.

    Each entry contains:
      - ``timestamp``   — ISO-8601 wall-clock time
      - ``service``     — which downstream service failed
      - ``endpoint``    — target URL
      - ``payload``     — the original request body
      - ``error_type``  — exception class name
      - ``error_msg``   — exception message
      - ``attempt``     — which retry attempt this was
      - ``circuit_state`` — circuit breaker state at time of failure
    """

    service_name: str
    directory: Path = DLQ_DIR
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self):
        self.directory = Path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @property
    def _file_path(self) -> Path:
        safe_name = self.service_name.replace(" ", "_").replace("/", "_")
        return self.directory / f"dlq_{safe_name}.jsonl"

    def enqueue(
        self,
        endpoint: str,
        payload: Any,
        error: Exception,
        attempt: int = 1,
        circuit_state: str = "unknown",
        extra: dict | None = None,
    ) -> dict:
        """Persist a failed request to the DLQ file.

        Returns the DLQ entry dict for logging / response inclusion.
        """
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "service": self.service_name,
            "endpoint": endpoint,
            "payload": payload,
            "error_type": type(error).__name__,
            "error_msg": str(error),
            "attempt": attempt,
            "circuit_state": circuit_state,
        }
        if extra:
            entry["extra"] = extra

        with self._lock:
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

        logger.warning(
            "[DLQ:%s] Enqueued failed request → %s (%s: %s)",
            self.service_name,
            endpoint,
            type(error).__name__,
            error,
        )
        return entry

    def read_all(self) -> list[dict]:
        """Read all DLQ entries (for admin/replay)."""
        if not self._file_path.exists():
            return []
        with self._lock:
            with open(self._file_path, "r", encoding="utf-8") as f:
                entries = []
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                return entries

    def count(self) -> int:
        """Return the number of entries in the DLQ."""
        return len(self.read_all())

    def clear(self) -> int:
        """Remove all entries.  Returns the count of purged entries."""
        n = self.count()
        if self._file_path.exists():
            with self._lock:
                self._file_path.unlink()
        logger.info("[DLQ:%s] Cleared %d entries", self.service_name, n)
        return n

    def to_dict(self) -> dict:
        """Summary for status endpoints."""
        return {
            "service": self.service_name,
            "file": str(self._file_path),
            "count": self.count(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  Retry helper (integrates circuit breaker + DLQ)
# ═══════════════════════════════════════════════════════════════════════════════

def is_transient(error: Exception) -> bool:
    """Return True if the error is likely transient and worth retrying."""
    transient_types = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        ConnectionError,
        TimeoutError,
        OSError,
    )
    if isinstance(error, transient_types):
        return True
    # HTTP 5xx from raise_for_status()
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return False


async def resilient_post(
    *,
    url: str,
    json_payload: dict,
    breaker: CircuitBreaker,
    dlq: DeadLetterQueue,
    max_retries: int = 3,
    base_timeout: float = 30.0,
    backoff_factor: float = 2.0,
) -> "httpx.Response":
    """POST with retry, circuit breaker, and DLQ.

    1. Check circuit breaker → raise ``CircuitOpenError`` if open.
    2. Try up to ``max_retries`` times with exponential backoff.
    3. On transient errors → retry.  On permanent errors → fail fast.
    4. On exhaustion → enqueue to DLQ and raise the last error.
    5. On success → record success on the breaker.
    """
    breaker.allow_request()  # may raise CircuitOpenError

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        timeout = base_timeout * (backoff_factor ** (attempt - 1))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=json_payload)
                resp.raise_for_status()
                breaker.record_success()
                logger.info(
                    "[Resilience] ✓ %s succeeded (attempt %d/%d)",
                    url, attempt, max_retries,
                )
                return resp
        except Exception as e:
            last_error = e
            breaker.record_failure(e)
            if not is_transient(e) or attempt == max_retries:
                break
            wait = backoff_factor ** (attempt - 1)
            logger.warning(
                "[Resilience] ↻ %s failed (attempt %d/%d: %s), retrying in %.1fs",
                url, attempt, max_retries, e, wait,
            )
            await asyncio.sleep(wait)

    # All retries exhausted or permanent error — enqueue to DLQ
    assert last_error is not None
    dlq.enqueue(
        endpoint=url,
        payload=json_payload,
        error=last_error,
        attempt=max_retries,
        circuit_state=breaker.state.value,
    )
    raise last_error
