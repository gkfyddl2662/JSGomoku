from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .inference import LoadedModel, contract_for, resolve_checkpoint_path


class InferenceBusyError(RuntimeError):
    """The serving queue is full, so Akagi should fail over immediately."""


class InferenceDeadlineExceeded(RuntimeError):
    """The server deadline expired before an inference response was ready."""


def _signature_text(signature: tuple[int, int] | None) -> str | None:
    if signature is None:
        return None
    return f"{signature[0]}:{signature[1]}"


def _percentile(values: deque[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction, 3)


class ModeTelemetry:
    def __init__(self, mode: str, *, recent_samples: int = 1024) -> None:
        self.mode = contract_for(mode).mode
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._requests = 0
        self._rows = 0
        self._errors = 0
        self._timeouts = 0
        self._busy_rejections = 0
        self._executions = 0
        self._execution_rows = 0
        self._coalesced_requests = 0
        self._max_rows_per_execution = 0
        self._queue_depth = 0
        self._peak_queue_depth = 0
        self._last_batch_rows = 0
        self._last_batch_requests = 0
        self._request_ms: deque[float] = deque(maxlen=recent_samples)
        self._queue_ms: deque[float] = deque(maxlen=recent_samples)
        self._model_ms: deque[float] = deque(maxlen=recent_samples)

    def set_queue_depth(self, depth: int) -> None:
        with self._lock:
            self._queue_depth = max(0, int(depth))
            self._peak_queue_depth = max(self._peak_queue_depth, self._queue_depth)

    def record_busy(self) -> None:
        with self._lock:
            self._requests += 1
            self._errors += 1
            self._busy_rejections += 1

    def record_timeout(self, rows: int, total_ms: float) -> None:
        with self._lock:
            self._requests += 1
            self._rows += rows
            self._errors += 1
            self._timeouts += 1
            self._request_ms.append(total_ms)

    def record_execution(self, request_count: int, row_count: int, model_ms: float) -> None:
        with self._lock:
            self._executions += 1
            self._execution_rows += row_count
            self._coalesced_requests += max(0, request_count - 1)
            self._max_rows_per_execution = max(self._max_rows_per_execution, row_count)
            self._last_batch_rows = row_count
            self._last_batch_requests = request_count
            self._model_ms.append(model_ms)

    def record_request(self, rows: int, queue_ms: float, total_ms: float, *, success: bool) -> None:
        with self._lock:
            self._requests += 1
            self._rows += rows
            if not success:
                self._errors += 1
            self._queue_ms.append(queue_ms)
            self._request_ms.append(total_ms)

    @staticmethod
    def _latency_snapshot(values: deque[float]) -> dict[str, float | None]:
        if not values:
            return {"last": None, "p50": None, "p95": None, "p99": None, "max": None}
        return {
            "last": round(values[-1], 3),
            "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
            "max": round(max(values), 3),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            uptime = max(time.monotonic() - self._started, 1.0e-9)
            executions = self._executions
            return {
                "mode": self.mode,
                "uptime_s": round(uptime, 3),
                "requests_total": self._requests,
                "rows_total": self._rows,
                "errors_total": self._errors,
                "timeouts_total": self._timeouts,
                "busy_rejections_total": self._busy_rejections,
                "executions_total": executions,
                "coalesced_requests_total": self._coalesced_requests,
                "request_rate_per_s": round(self._requests / uptime, 3),
                "row_rate_per_s": round(self._rows / uptime, 3),
                "avg_rows_per_execution": round(self._execution_rows / executions, 3) if executions else 0.0,
                "max_rows_per_execution": self._max_rows_per_execution,
                "last_batch_rows": self._last_batch_rows,
                "last_batch_requests": self._last_batch_requests,
                "queue_depth": self._queue_depth,
                "peak_queue_depth": self._peak_queue_depth,
                "latency_ms": {
                    "request": self._latency_snapshot(self._request_ms),
                    "queue": self._latency_snapshot(self._queue_ms),
                    "model": self._latency_snapshot(self._model_ms),
                },
            }


class ServingModelSlot:
    """Atomic publish slot that never compiles a replacement on a request thread."""

    def __init__(self, mode: str, path: Path, mortal_dir: Path, device: str) -> None:
        self.contract = contract_for(mode)
        self.path = path.resolve()
        self.mortal_dir = mortal_dir.resolve()
        self.device = device
        self._lock = threading.RLock()
        self._reload_lock = threading.Lock()
        self._loaded: LoadedModel | None = None
        self._loaded_signature: tuple[int, int] | None = None
        self._failed_signature: tuple[int, int] | None = None
        self._last_error: str | None = None
        self._reloading = False

    def _signature(self) -> tuple[int, int]:
        st = self.path.stat()
        return st.st_mtime_ns, st.st_size

    def get(self) -> LoadedModel:
        with self._lock:
            loaded = self._loaded
        if loaded is not None:
            return loaded
        return self.reload(raise_on_failure=True, force=True)

    def reload(self, *, raise_on_failure: bool = False, force: bool = False) -> LoadedModel:
        with self._reload_lock:
            if not self.path.is_file():
                error = f"FileNotFoundError: {self.contract.mode} API model not found: {self.path}"
                with self._lock:
                    self._last_error = error
                    loaded = self._loaded
                if loaded is not None and not raise_on_failure:
                    return loaded
                raise FileNotFoundError(f"{self.contract.mode} API model not found: {self.path}")

            signature = self._signature()
            with self._lock:
                if self._loaded is not None and signature == self._loaded_signature:
                    return self._loaded
                if self._loaded is not None and signature == self._failed_signature and not force:
                    return self._loaded
                self._reloading = True

            try:
                candidate = LoadedModel(self.contract.mode, self.path, self.mortal_dir, self.device)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self._failed_signature = signature
                    self._last_error = error
                    self._reloading = False
                    loaded = self._loaded
                if loaded is not None and not raise_on_failure:
                    return loaded
                raise

            with self._lock:
                self._loaded = candidate
                self._loaded_signature = signature
                self._failed_signature = None
                self._last_error = None
                self._reloading = False
                return candidate

    def refresh(self) -> None:
        with self._lock:
            loaded = self._loaded
        if loaded is None:
            try:
                self.reload(raise_on_failure=False)
            except Exception:
                pass
            return
        if not self.path.is_file():
            with self._lock:
                self._last_error = f"FileNotFoundError: {self.contract.mode} API model not found: {self.path}"
            return
        signature = self._signature()
        with self._lock:
            if signature == self._loaded_signature or signature == self._failed_signature or self._reloading:
                return
        try:
            self.reload(raise_on_failure=False)
        except Exception:
            pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            exists = self.path.is_file()
            current_signature = self._signature() if exists else None
            loaded = self._loaded
            return {
                "mode": self.contract.mode,
                "path": str(self.path),
                "exists": exists,
                "loaded": loaded is not None,
                "current": current_signature == self._loaded_signature if current_signature is not None else False,
                "reloading": self._reloading,
                "last_error": self._last_error,
                "action_space": self.contract.action_space,
                "obs_shape": [self.contract.obs_channels, 34],
                "device": str(loaded.device) if loaded is not None else self.device,
                "compiled": loaded.compiled if loaded is not None else None,
                "amp_dtype": loaded.amp_dtype_name if loaded is not None and loaded.use_amp else None,
                "loaded_signature": _signature_text(self._loaded_signature),
                "candidate_signature": _signature_text(current_signature),
                "failed_signature": _signature_text(self._failed_signature),
            }


@dataclass(slots=True)
class _PendingRequest:
    obs: Any
    masks: Any
    rows: int
    enqueued_at: float
    event: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None
    error: Exception | None = None
    timed_out: bool = False


class DynamicBatcher:
    RESPONSE_KEYS = ("actions", "q_out", "masks", "is_greedy")

    def __init__(
        self,
        mode: str,
        infer_fn: Callable[[Any, Any], dict[str, Any]],
        telemetry: ModeTelemetry,
        *,
        wait_ms: float = 1.0,
        max_rows: int = 64,
        max_pending_requests: int = 128,
        request_deadline_ms: float = 3500.0,
    ) -> None:
        self.mode = contract_for(mode).mode
        self.infer_fn = infer_fn
        self.telemetry = telemetry
        self.wait_s = max(0.0, float(wait_ms)) / 1000.0
        self.max_rows = max(1, int(max_rows))
        self.max_pending_requests = max(1, int(max_pending_requests))
        self.request_deadline_s = max(0.001, float(request_deadline_ms) / 1000.0)
        self._queue: deque[_PendingRequest] = deque()
        self._condition = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name=f"mortal-rogs-batcher-{self.mode}", daemon=True)
        self._thread.start()

    def submit(self, obs: Any, masks: Any) -> dict[str, Any]:
        try:
            rows = len(obs)
            mask_rows = len(masks)
        except TypeError as exc:
            raise ValueError("Inference obs and masks must be batched sequences") from exc
        if rows <= 0:
            raise ValueError("Inference batch must be non-empty")
        if mask_rows != rows:
            raise ValueError(f"Inference obs/mask batch mismatch: {rows} vs {mask_rows}")

        contract = contract_for(self.mode)
        for row_index in range(rows):
            obs_row = obs[row_index]
            mask_row = masks[row_index]
            try:
                channels = len(obs_row)
                action_count = len(mask_row)
            except TypeError as exc:
                raise ValueError(f"{self.mode} inference rows must be sequences") from exc
            if channels != contract.obs_channels:
                raise ValueError(
                    f"{self.mode} obs must be [batch,{contract.obs_channels},34], "
                    f"row {row_index} has {channels} channels"
                )
            for channel_index, channel in enumerate(obs_row):
                try:
                    tile_count = len(channel)
                except TypeError as exc:
                    raise ValueError(f"{self.mode} obs channel {channel_index} must be a sequence") from exc
                if tile_count != 34:
                    raise ValueError(
                        f"{self.mode} obs must be [batch,{contract.obs_channels},34], "
                        f"row {row_index} channel {channel_index} has {tile_count} tiles"
                    )
            if action_count != contract.action_space:
                raise ValueError(
                    f"{self.mode} masks must be [batch,{contract.action_space}], "
                    f"row {row_index} has {action_count} actions"
                )
            if not any(bool(value) for value in mask_row):
                raise ValueError("Every inference row must contain at least one legal action")

        pending = _PendingRequest(obs=obs, masks=masks, rows=rows, enqueued_at=time.perf_counter())
        with self._condition:
            if self._closed:
                raise RuntimeError("Inference batcher is closed")
            if len(self._queue) >= self.max_pending_requests:
                self.telemetry.record_busy()
                raise InferenceBusyError(
                    f"{self.mode} inference queue is full ({self.max_pending_requests} pending requests)"
                )
            self._queue.append(pending)
            self.telemetry.set_queue_depth(len(self._queue))
            self._condition.notify()

        if not pending.event.wait(self.request_deadline_s):
            pending.timed_out = True
            total_ms = (time.perf_counter() - pending.enqueued_at) * 1000.0
            self.telemetry.record_timeout(rows, total_ms)
            raise InferenceDeadlineExceeded(
                f"{self.mode} inference exceeded server deadline {self.request_deadline_s * 1000.0:.0f} ms"
            )
        if pending.error is not None:
            raise pending.error
        if pending.response is None:
            raise RuntimeError("Inference batcher completed without a response")
        return pending.response

    def close(self) -> None:
        with self._condition:
            self._closed = True
            queued = list(self._queue)
            self._queue.clear()
            self.telemetry.set_queue_depth(0)
            self._condition.notify_all()
        for pending in queued:
            pending.error = RuntimeError("Inference service is shutting down")
            pending.event.set()
        self._thread.join(timeout=2.0)

    def _take_batch(self) -> list[_PendingRequest]:
        with self._condition:
            while not self._queue and not self._closed:
                self._condition.wait()
            if self._closed and not self._queue:
                return []

            first = self._queue.popleft()
            batch = [first]
            row_count = first.rows
            deadline = time.perf_counter() + self.wait_s
            while row_count < self.max_rows and not self._closed:
                if self._queue:
                    candidate = self._queue[0]
                    if row_count + candidate.rows > self.max_rows:
                        break
                    batch.append(self._queue.popleft())
                    row_count += candidate.rows
                    continue
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)

            self.telemetry.set_queue_depth(len(self._queue))
            return batch

    def _run(self) -> None:
        while True:
            batch = self._take_batch()
            if not batch:
                if self._closed:
                    return
                continue

            merged_obs: list[Any] = []
            merged_masks: list[Any] = []
            for pending in batch:
                for index in range(pending.rows):
                    merged_obs.append(pending.obs[index])
                    merged_masks.append(pending.masks[index])

            model_started = time.perf_counter()
            try:
                combined = self.infer_fn(merged_obs, merged_masks)
                model_ms = (time.perf_counter() - model_started) * 1000.0
                self.telemetry.record_execution(len(batch), len(merged_obs), model_ms)

                offset = 0
                completed_at = time.perf_counter()
                for pending in batch:
                    end = offset + pending.rows
                    pending.response = {key: combined[key][offset:end] for key in self.RESPONSE_KEYS}
                    queue_ms = max(0.0, (model_started - pending.enqueued_at) * 1000.0)
                    total_ms = max(0.0, (completed_at - pending.enqueued_at) * 1000.0)
                    if not pending.timed_out:
                        self.telemetry.record_request(pending.rows, queue_ms, total_ms, success=True)
                    pending.event.set()
                    offset = end
            except Exception as exc:
                model_ms = (time.perf_counter() - model_started) * 1000.0
                self.telemetry.record_execution(len(batch), len(merged_obs), model_ms)
                completed_at = time.perf_counter()
                for pending in batch:
                    pending.error = exc
                    queue_ms = max(0.0, (model_started - pending.enqueued_at) * 1000.0)
                    total_ms = max(0.0, (completed_at - pending.enqueued_at) * 1000.0)
                    if not pending.timed_out:
                        self.telemetry.record_request(pending.rows, queue_ms, total_ms, success=False)
                    pending.event.set()


class ResilientInferenceService:
    def __init__(
        self,
        runtime_root: Path,
        *,
        device: str = "auto",
        model_3p: Path | None = None,
        model_4p: Path | None = None,
        micro_batch_ms: float = 1.0,
        micro_batch_max_rows: int = 64,
        max_pending_requests: int = 128,
        request_deadline_ms: float = 3500.0,
        reload_poll_ms: float = 500.0,
    ) -> None:
        self.runtime_root = runtime_root.expanduser().resolve()
        mortal_dir = self.runtime_root / "mortal"
        if not mortal_dir.is_dir():
            raise FileNotFoundError(f"Unified Mortal directory not found: {mortal_dir}")
        self.slots = {
            "3p": ServingModelSlot("3p", resolve_checkpoint_path(self.runtime_root, "3p", model_3p), mortal_dir, device),
            "4p": ServingModelSlot("4p", resolve_checkpoint_path(self.runtime_root, "4p", model_4p), mortal_dir, device),
        }
        self.telemetry = {mode: ModeTelemetry(mode) for mode in self.slots}
        self.micro_batch_ms = max(0.0, float(micro_batch_ms))
        self.micro_batch_max_rows = max(1, int(micro_batch_max_rows))
        self.max_pending_requests = max(1, int(max_pending_requests))
        self.request_deadline_ms = max(1.0, float(request_deadline_ms))
        self.reload_poll_ms = max(50.0, float(reload_poll_ms))
        self._stop_event = threading.Event()
        self._watchers: dict[str, threading.Thread] = {}
        self.batchers = {
            mode: DynamicBatcher(
                mode,
                lambda obs, masks, mode=mode: self.slots[mode].get().infer(obs, masks),
                self.telemetry[mode],
                wait_ms=self.micro_batch_ms,
                max_rows=self.micro_batch_max_rows,
                max_pending_requests=self.max_pending_requests,
                request_deadline_ms=self.request_deadline_ms,
            )
            for mode in self.slots
        }

    def warmup(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        loaded_count = 0
        for mode, slot in self.slots.items():
            try:
                model = slot.reload(raise_on_failure=True, force=True)
            except Exception as exc:
                results[mode] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                continue
            loaded_count += 1
            results[mode] = {
                "ok": True,
                "device": str(model.device),
                "compiled": model.compiled,
                "amp_dtype": model.amp_dtype_name if model.use_amp else None,
            }
        if loaded_count == 0:
            details = "; ".join(f"{mode}: {info['error']}" for mode, info in results.items())
            raise RuntimeError(f"No Mortal API model could be prewarmed: {details}")
        return {"ok": True, "loaded": loaded_count, "modes": results}

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
                name=f"mortal-rogs-model-watcher-{mode}",
                daemon=True,
            )
            self._watchers[mode] = thread
            thread.start()

    def _watch_checkpoint(self, mode: str) -> None:
        interval = self.reload_poll_ms / 1000.0
        slot = self.slots[mode]
        while not self._stop_event.wait(interval):
            slot.refresh()

    def reload(self, mode: str, *, force: bool = True) -> dict[str, Any]:
        contract = contract_for(mode)
        slot = self.slots[contract.mode]
        try:
            slot.reload(raise_on_failure=True, force=force)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "status": slot.status()}
        info = slot.status()
        ok = bool(info["loaded"] and info["current"] and info["last_error"] is None)
        return {"ok": ok, "status": info}

    def infer(self, mode: str, obs: Any, masks: Any) -> dict[str, Any]:
        contract = contract_for(mode)
        return self.batchers[contract.mode].submit(obs, masks)

    def metrics(self) -> dict[str, Any]:
        return {
            "protocol": "mortal-rogs-inference-v1",
            "micro_batch": {
                "wait_ms": self.micro_batch_ms,
                "max_rows": self.micro_batch_max_rows,
                "max_pending_requests": self.max_pending_requests,
                "request_deadline_ms": self.request_deadline_ms,
            },
            "reload": {
                "poll_ms": self.reload_poll_ms,
                "background": bool(self._watchers) and all(thread.is_alive() for thread in self._watchers.values()),
                "workers": {mode: thread.is_alive() for mode, thread in self._watchers.items()},
            },
            "modes": {mode: telemetry.snapshot() for mode, telemetry in self.telemetry.items()},
        }

    def health(self) -> dict[str, Any]:
        models = {mode: slot.status() for mode, slot in self.slots.items()}
        degraded = any((not info["exists"]) or info["last_error"] is not None for info in models.values())
        return {
            "ok": True,
            "degraded": degraded,
            "protocol": "akagiot-v1",
            "runtime_root": str(self.runtime_root),
            "endpoints": {"3p": "/react_batch_3p", "4p": "/react_batch"},
            "models": models,
            "serving": self.metrics(),
        }

    def close(self) -> None:
        self._stop_event.set()
        for watcher in self._watchers.values():
            watcher.join(timeout=2.0)
        for batcher in self.batchers.values():
            batcher.close()
