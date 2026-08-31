from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Any, Iterator

from .inference import contract_for
from .resilient import ResilientInferenceService


class InferenceDrainingError(RuntimeError):
    """New inference is rejected because the service is draining."""


def _percentile(values: deque[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction, 3)


class RequestLifecycle:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._state = "running"
        self._inflight = 0
        self._peak_inflight = 0
        self._accepted = 0
        self._rejected = 0
        self._drain_started_at: float | None = None

    @contextmanager
    def request(self) -> Iterator[None]:
        with self._condition:
            if self._state != "running":
                self._rejected += 1
                raise InferenceDrainingError(f"Inference service is {self._state}")
            self._accepted += 1
            self._inflight += 1
            self._peak_inflight = max(self._peak_inflight, self._inflight)
        try:
            yield
        finally:
            with self._condition:
                self._inflight = max(0, self._inflight - 1)
                self._condition.notify_all()

    def drain(self, timeout_ms: float) -> dict[str, Any]:
        timeout_s = max(0.0, float(timeout_ms)) / 1000.0
        deadline = time.monotonic() + timeout_s
        with self._condition:
            if self._state == "closed":
                return {**self.snapshot(), "drained": True, "timed_out": False}
            if self._state == "running":
                self._state = "draining"
                self._drain_started_at = time.monotonic()
            while self._inflight > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {**self.snapshot(), "drained": False, "timed_out": True}
                self._condition.wait(timeout=remaining)
            return {**self.snapshot(), "drained": True, "timed_out": False}

    def close(self) -> None:
        with self._condition:
            self._state = "closed"
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            draining_for_ms = None
            if self._drain_started_at is not None:
                draining_for_ms = round((time.monotonic() - self._drain_started_at) * 1000.0, 3)
            return {
                "state": self._state,
                "accepting": self._state == "running",
                "inflight_requests": self._inflight,
                "peak_inflight_requests": self._peak_inflight,
                "accepted_requests_total": self._accepted,
                "rejected_during_drain_total": self._rejected,
                "draining_for_ms": draining_for_ms,
            }


class DeviceExecutionCoordinator:
    def __init__(self, *, max_parallel: int = 1, recent_samples: int = 1024) -> None:
        self.max_parallel = max(1, int(max_parallel))
        self._condition = threading.Condition()
        self._next_ticket = 0
        self._serving_ticket = 0
        self._active = 0
        self._waiting = 0
        self._peak_active = 0
        self._peak_waiting = 0
        self._acquisitions = 0
        self._contended = 0
        self._wait_ms: deque[float] = deque(maxlen=recent_samples)
        self._by_mode: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"acquisitions": 0, "contended": 0, "wait_ms_total": 0.0}
        )
        self._last_release = time.monotonic()

        self._maintenance_lock = threading.Lock()
        self._maintenance_active = 0
        self._maintenance_waiting = 0
        self._peak_maintenance_waiting = 0
        self._maintenance_cycles = 0
        self._maintenance_wait_ms: deque[float] = deque(maxlen=recent_samples)
        self._inference_during_maintenance = 0

    @contextmanager
    def execution(self, mode: str) -> Iterator[None]:
        normalized = contract_for(mode).mode
        started = time.perf_counter()
        with self._condition:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._waiting += 1
            self._peak_waiting = max(self._peak_waiting, self._waiting)
            had_to_wait = not (ticket == self._serving_ticket and self._active < self.max_parallel)
            while ticket != self._serving_ticket or self._active >= self.max_parallel:
                self._condition.wait()
            self._serving_ticket += 1
            self._waiting -= 1
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)
            if self._maintenance_active:
                self._inference_during_maintenance += 1
            self._condition.notify_all()

        waited_ms = (time.perf_counter() - started) * 1000.0
        with self._condition:
            self._acquisitions += 1
            self._wait_ms.append(waited_ms)
            mode_row = self._by_mode[normalized]
            mode_row["acquisitions"] = int(mode_row["acquisitions"]) + 1
            mode_row["wait_ms_total"] = float(mode_row["wait_ms_total"]) + waited_ms
            if had_to_wait:
                self._contended += 1
                mode_row["contended"] = int(mode_row["contended"]) + 1

        try:
            yield
        finally:
            with self._condition:
                self._active = max(0, self._active - 1)
                self._last_release = time.monotonic()
                self._condition.notify_all()

    def wait_for_quiet(self, *, idle_ms: float, timeout_ms: float) -> bool:
        idle_s = max(0.0, float(idle_ms)) / 1000.0
        timeout_s = max(0.0, float(timeout_ms)) / 1000.0
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while True:
                now = time.monotonic()
                idle_for = now - self._last_release
                if self._active == 0 and self._waiting == 0 and idle_for >= idle_s:
                    return True
                if timeout_s <= 0.0:
                    return False
                remaining = deadline - now
                if remaining <= 0:
                    return False
                idle_remaining = max(0.0, idle_s - idle_for)
                wait_for = remaining if idle_remaining <= 0 else min(remaining, idle_remaining)
                self._condition.wait(timeout=max(0.001, wait_for))

    @contextmanager
    def maintenance(self) -> Iterator[None]:
        started = time.perf_counter()
        with self._condition:
            self._maintenance_waiting += 1
            self._peak_maintenance_waiting = max(self._peak_maintenance_waiting, self._maintenance_waiting)
        with self._maintenance_lock:
            waited_ms = (time.perf_counter() - started) * 1000.0
            with self._condition:
                self._maintenance_waiting = max(0, self._maintenance_waiting - 1)
                self._maintenance_active = 1
                self._maintenance_cycles += 1
                self._maintenance_wait_ms.append(waited_ms)
            try:
                yield
            finally:
                with self._condition:
                    self._maintenance_active = 0
                    self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            by_mode: dict[str, Any] = {}
            for mode in ("3p", "4p"):
                row = self._by_mode.get(mode, {"acquisitions": 0, "contended": 0, "wait_ms_total": 0.0})
                acquisitions = int(row["acquisitions"])
                total_wait = float(row["wait_ms_total"])
                by_mode[mode] = {
                    "acquisitions": acquisitions,
                    "contended": int(row["contended"]),
                    "avg_wait_ms": round(total_wait / acquisitions, 3) if acquisitions else 0.0,
                }
            return {
                "policy": "fair-fifo",
                "max_parallel_executions": self.max_parallel,
                "active_executions": self._active,
                "waiting_executions": self._waiting,
                "peak_active_executions": self._peak_active,
                "peak_waiting_executions": self._peak_waiting,
                "acquisitions_total": self._acquisitions,
                "contended_acquisitions_total": self._contended,
                "wait_ms": {
                    "p50": _percentile(self._wait_ms, 0.50),
                    "p95": _percentile(self._wait_ms, 0.95),
                    "p99": _percentile(self._wait_ms, 0.99),
                    "max": round(max(self._wait_ms), 3) if self._wait_ms else None,
                },
                "maintenance_active": self._maintenance_active > 0,
                "maintenance_waiting": self._maintenance_waiting,
                "peak_maintenance_waiting": self._peak_maintenance_waiting,
                "maintenance_cycles_total": self._maintenance_cycles,
                "maintenance_wait_ms": {
                    "p50": _percentile(self._maintenance_wait_ms, 0.50),
                    "p95": _percentile(self._maintenance_wait_ms, 0.95),
                    "p99": _percentile(self._maintenance_wait_ms, 0.99),
                    "max": round(max(self._maintenance_wait_ms), 3) if self._maintenance_wait_ms else None,
                },
                "inference_during_maintenance_total": self._inference_during_maintenance,
                "by_mode": by_mode,
            }


class CoordinatedInferenceService:
    """Operational wrapper around ResilientInferenceService.

    Same-mode micro-batching remains inside each DynamicBatcher. Only the actual
    model execution callback is gated, so concurrent requests can still coalesce
    before 3P/4P compete for one GPU.
    """

    def __init__(
        self,
        service: ResilientInferenceService,
        *,
        max_device_executions: int = 1,
        reload_quiet_ms: float = 150.0,
        reload_wait_ms: float = 1000.0,
        drain_timeout_ms: float = 3500.0,
    ) -> None:
        self._service = service
        self.runtime_root = service.runtime_root
        self.slots = service.slots
        self.batchers = service.batchers
        self.telemetry = service.telemetry
        self.device = DeviceExecutionCoordinator(max_parallel=max_device_executions)
        self.lifecycle = RequestLifecycle()
        self.reload_quiet_ms = max(0.0, float(reload_quiet_ms))
        self.reload_wait_ms = max(0.0, float(reload_wait_ms))
        self.drain_timeout_ms = max(1.0, float(drain_timeout_ms))
        self._stop_event = threading.Event()
        self._watchers: dict[str, threading.Thread] = {}
        self._tuning_lock = threading.Lock()
        self._install_device_gate()

    @property
    def micro_batch_ms(self) -> float:
        return self._service.micro_batch_ms

    @property
    def reload_poll_ms(self) -> float:
        return self._service.reload_poll_ms

    def _install_device_gate(self) -> None:
        for mode, batcher in self.batchers.items():
            original = batcher.infer_fn

            def guarded(obs: Any, masks: Any, *, mode: str = mode, original=original) -> dict[str, Any]:
                with self.device.execution(mode):
                    return original(obs, masks)

            batcher.infer_fn = guarded

    def warmup(self) -> dict[str, Any]:
        return self._service.warmup()

    def set_micro_batch_wait(self, wait_ms: float) -> dict[str, Any]:
        from contextlib import ExitStack

        wait_ms = float(wait_ms)
        if not 0.0 <= wait_ms <= 100.0:
            raise ValueError("micro_batch_ms must be between 0 and 100")
        batchers = [self.batchers[mode] for mode in sorted(self.batchers)]
        with self._tuning_lock, ExitStack() as stack:
            for batcher in batchers:
                stack.enter_context(batcher._condition)
            for batcher in batchers:
                batcher.wait_s = wait_ms / 1000.0
            self._service.micro_batch_ms = wait_ms
        return dict(self.metrics()["micro_batch"])

    def start_background(self) -> None:
        if self._watchers and all(thread.is_alive() for thread in self._watchers.values()):
            return
        self._stop_event.clear()
        for mode in self.slots:
            current = self._watchers.get(mode)
            if current is not None and current.is_alive():
                continue
            thread = threading.Thread(
                target=self._watch_checkpoint,
                args=(mode,),
                name=f"mortal-rogs-coordinated-watcher-{mode}",
                daemon=True,
            )
            self._watchers[mode] = thread
            thread.start()

    def _watch_checkpoint(self, mode: str) -> None:
        interval = self.reload_poll_ms / 1000.0
        while not self._stop_event.wait(interval):
            if self.lifecycle.snapshot()["state"] != "running":
                continue
            info = self.slots[mode].status()
            needs_reload = bool(info["exists"] and (not info["loaded"] or not info["current"]) and not info["reloading"])
            if not needs_reload:
                continue
            self._reload_now(mode, force=False, quiet_wait_ms=0.0)

    def _reload_now(self, mode: str, *, force: bool, quiet_wait_ms: float) -> dict[str, Any]:
        with self.device.maintenance():
            # Quiet admission is deliberately checked after acquiring the shared
            # maintenance lock. Otherwise a 4P reload waiting behind a long 3P
            # compile could act on a stale pre-lock idle observation.
            if not self.device.wait_for_quiet(idle_ms=self.reload_quiet_ms, timeout_ms=quiet_wait_ms):
                return {
                    "ok": False,
                    "deferred": True,
                    "error": (
                        f"InferenceBusyError: {mode} reload deferred because the shared device "
                        f"did not stay quiet for {self.reload_quiet_ms:.0f} ms"
                    ),
                    "status": self.slots[mode].status(),
                }
            return self._service.reload(mode, force=force)

    def reload(self, mode: str, *, force: bool = True) -> dict[str, Any]:
        contract = contract_for(mode)
        if self.lifecycle.snapshot()["state"] != "running":
            return {
                "ok": False,
                "error": "InferenceDrainingError: reload rejected while service is draining",
                "status": self.slots[contract.mode].status(),
            }
        return self._reload_now(contract.mode, force=force, quiet_wait_ms=self.reload_wait_ms)

    def infer(self, mode: str, obs: Any, masks: Any) -> dict[str, Any]:
        contract = contract_for(mode)
        with self.lifecycle.request():
            return self._service.infer(contract.mode, obs, masks)

    def drain(self, timeout_ms: float | None = None) -> dict[str, Any]:
        self._stop_event.set()
        result = self.lifecycle.drain(self.drain_timeout_ms if timeout_ms is None else timeout_ms)
        for watcher in self._watchers.values():
            watcher.join(timeout=1.0)
        result["device_scheduler"] = self.device.snapshot()
        return result

    def metrics(self) -> dict[str, Any]:
        result = dict(self._service.metrics())
        result["device_scheduler"] = self.device.snapshot()
        result["lifecycle"] = self.lifecycle.snapshot()
        result["reload"] = {
            **dict(result.get("reload", {})),
            "background": bool(self._watchers) and all(thread.is_alive() for thread in self._watchers.values()),
            "workers": {mode: thread.is_alive() for mode, thread in self._watchers.items()},
            "quiet_ms": self.reload_quiet_ms,
            "wait_ms": self.reload_wait_ms,
        }
        result["drain_timeout_ms"] = self.drain_timeout_ms
        return result

    def health(self) -> dict[str, Any]:
        result = dict(self._service.health())
        result["serving"] = self.metrics()
        result["lifecycle"] = self.lifecycle.snapshot()
        return result

    def close(self) -> None:
        if self.lifecycle.snapshot()["state"] == "running":
            self.drain(self.drain_timeout_ms)
        self._stop_event.set()
        for watcher in self._watchers.values():
            watcher.join(timeout=1.0)
        self._service.close()
        self.lifecycle.close()
