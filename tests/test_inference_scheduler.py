from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from serving.resilient import (
    DynamicBatcher,
    InferenceBusyError,
    InferenceDeadlineExceeded,
    ModeTelemetry,
)


def _request_for(mode: str, value: int):
    channels, actions = (1010, 44) if mode == "3p" else (1012, 46)
    obs_row = [[0.0] * 34 for _ in range(channels)]
    obs_row[0][0] = float(value)
    mask_row = [False] * actions
    mask_row[0] = True
    return [obs_row], [mask_row]


def _response_for(obs, masks):
    # Use the first scalar as a stable per-row identity so split/merge ordering is
    # observable without importing torch or a Mortal runtime.
    actions = [int(row[0][0]) for row in obs]
    return {
        "actions": actions,
        "q_out": [[float(action)] for action in actions],
        "masks": [list(row) for row in masks],
        "is_greedy": [True] * len(actions),
    }


def test_dynamic_batcher_coalesces_concurrent_requests() -> None:
    telemetry = ModeTelemetry("3p")
    entered = []
    lock = threading.Lock()

    def infer(obs, masks):
        with lock:
            entered.append(len(obs))
        time.sleep(0.01)
        return _response_for(obs, masks)

    batcher = DynamicBatcher(
        "3p",
        infer,
        telemetry,
        wait_ms=30,
        max_rows=16,
        max_pending_requests=16,
        request_deadline_ms=1000,
    )
    barrier = threading.Barrier(5)
    outputs: dict[int, dict] = {}
    errors: list[BaseException] = []

    def worker(value: int) -> None:
        try:
            barrier.wait()
            obs, masks = _request_for("3p", value)
            outputs[value] = batcher.submit(obs, masks)
        except BaseException as exc:  # test harness must report thread errors
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(value,)) for value in range(4)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)
    batcher.close()

    assert not errors
    assert len(outputs) == 4
    for value, body in outputs.items():
        assert body["actions"] == [value]
        assert body["q_out"] == [[float(value)]]
    assert entered == [4]

    metrics = telemetry.snapshot()
    assert metrics["requests_total"] == 4
    assert metrics["rows_total"] == 4
    assert metrics["executions_total"] == 1
    assert metrics["coalesced_requests_total"] == 3
    assert metrics["avg_rows_per_execution"] == 4.0
    assert metrics["last_batch_requests"] == 4
    assert metrics["last_batch_rows"] == 4
    assert metrics["latency_ms"]["request"]["p95"] is not None


def test_dynamic_batcher_rejects_when_pending_queue_is_full() -> None:
    telemetry = ModeTelemetry("4p")
    infer_entered = threading.Event()
    release_infer = threading.Event()

    def blocked_infer(obs, masks):
        infer_entered.set()
        assert release_infer.wait(timeout=2)
        return _response_for(obs, masks)

    batcher = DynamicBatcher(
        "4p",
        blocked_infer,
        telemetry,
        wait_ms=0,
        max_rows=8,
        max_pending_requests=1,
        request_deadline_ms=1500,
    )
    first_result: list[dict] = []
    second_result: list[dict] = []

    first = threading.Thread(target=lambda: first_result.append(batcher.submit(*_request_for("4p", 1))))
    first.start()
    assert infer_entered.wait(timeout=1)

    second_started = threading.Event()

    def second_worker() -> None:
        second_started.set()
        second_result.append(batcher.submit(*_request_for("4p", 2)))

    second = threading.Thread(target=second_worker)
    second.start()
    assert second_started.wait(timeout=1)

    deadline = time.time() + 1
    while telemetry.snapshot()["queue_depth"] < 1 and time.time() < deadline:
        time.sleep(0.005)
    assert telemetry.snapshot()["queue_depth"] == 1

    with pytest.raises(InferenceBusyError):
        batcher.submit(*_request_for("4p", 3))

    release_infer.set()
    first.join(timeout=2)
    second.join(timeout=2)
    batcher.close()

    assert first_result[0]["actions"] == [1]
    assert second_result[0]["actions"] == [2]
    metrics = telemetry.snapshot()
    assert metrics["busy_rejections_total"] == 1
    assert metrics["errors_total"] >= 1


def test_dynamic_batcher_enforces_server_deadline() -> None:
    telemetry = ModeTelemetry("3p")

    def slow_infer(obs, masks):
        time.sleep(0.10)
        return _response_for(obs, masks)

    batcher = DynamicBatcher(
        "3p",
        slow_infer,
        telemetry,
        wait_ms=0,
        max_rows=8,
        max_pending_requests=8,
        request_deadline_ms=20,
    )
    started = time.perf_counter()
    with pytest.raises(InferenceDeadlineExceeded):
        batcher.submit(*_request_for("3p", 7))
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < 90

    # Let the worker finish before closing; a timed-out HTTP request must not kill
    # the serving worker or poison later batches.
    time.sleep(0.12)
    batcher.close()
    metrics = telemetry.snapshot()
    assert metrics["timeouts_total"] == 1
    assert metrics["errors_total"] >= 1


def test_model_slot_keeps_published_model_available_during_reload(tmp_path, monkeypatch) -> None:
    import serving.resilient as inference

    model_path = tmp_path / "best_mortal.pth"
    model_path.write_text("old", encoding="utf-8")
    mortal_dir = tmp_path / "mortal"
    mortal_dir.mkdir()

    reload_started = threading.Event()
    allow_reload = threading.Event()
    created = []

    class FakeLoadedModel:
        def __init__(self, mode, path, runtime_mortal_dir, device):
            self.mode = mode
            self.path = path
            self.device = device
            self.compiled = False
            self.use_amp = False
            self.amp_dtype_name = "bfloat16"
            self.payload = path.read_text(encoding="utf-8")
            created.append(self)
            if self.payload == "new-checkpoint":
                reload_started.set()
                assert allow_reload.wait(timeout=2)

    monkeypatch.setattr(inference, "LoadedModel", FakeLoadedModel)
    slot = inference.ServingModelSlot("3p", model_path, mortal_dir, "cpu")
    old_model = slot.reload(force=True, raise_on_failure=True)
    assert old_model.payload == "old"

    model_path.write_text("new-checkpoint", encoding="utf-8")
    reload_error = []

    def reload_worker() -> None:
        try:
            slot.reload(force=True, raise_on_failure=True)
        except BaseException as exc:
            reload_error.append(exc)

    thread = threading.Thread(target=reload_worker)
    thread.start()
    assert reload_started.wait(timeout=1)

    started = time.perf_counter()
    still_serving = slot.get()
    get_ms = (time.perf_counter() - started) * 1000.0
    assert still_serving is old_model
    assert get_ms < 50
    assert slot.status()["reloading"] is True

    allow_reload.set()
    thread.join(timeout=2)
    assert not reload_error
    assert slot.get() is not old_model
    assert slot.get().payload == "new-checkpoint"
    assert len(created) == 2


def test_cuda_memory_snapshot_and_oom_cleanup_are_lazy(monkeypatch) -> None:
    import serving.resilient as inference

    gib = 1024**3
    cleared: list[bool] = []

    class FakeOOM(RuntimeError):
        pass

    class FakeCuda:
        OutOfMemoryError = FakeOOM

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def device_count():
            return 1

        @staticmethod
        def mem_get_info(index):
            assert index == 0
            return 4 * gib, 16 * gib

        @staticmethod
        def get_device_name(index):
            assert index == 0
            return "NVIDIA GeForce RTX 5080"

        @staticmethod
        def memory_allocated(index):
            return 8 * gib

        @staticmethod
        def memory_reserved(index):
            return 10 * gib

        @staticmethod
        def max_memory_allocated(index):
            return 9 * gib

        @staticmethod
        def max_memory_reserved(index):
            return 11 * gib

        @staticmethod
        def empty_cache():
            cleared.append(True)

    class FakeTorch:
        OutOfMemoryError = FakeOOM
        cuda = FakeCuda()

    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    memory = inference.cuda_memory_snapshot()
    assert memory["available"] is True
    assert len(memory["devices"]) == 1
    device = memory["devices"][0]
    assert device["name"] == "NVIDIA GeForce RTX 5080"
    assert device["allocated_mib"] == 8192.0
    assert device["reserved_mib"] == 10240.0
    assert device["peak_reserved_mib"] == 11264.0
    assert device["free_mib"] == 4096.0
    assert device["total_mib"] == 16384.0
    assert device["reserved_pct_total"] == 62.5

    assert inference._clear_cuda_cache_after_oom(FakeOOM("CUDA out of memory")) is True
    assert cleared == [True]
    assert inference._clear_cuda_cache_after_oom(RuntimeError("ordinary reload failure")) is False
    assert cleared == [True]


def test_cuda_memory_metrics_are_wired_without_new_serving_subsystem() -> None:
    root = Path(__file__).resolve().parents[1]
    service = (root / "serving" / "resilient.py").read_text(encoding="utf-8")
    ui = (root / "static" / "inference.js").read_text(encoding="utf-8")

    assert '"cuda_memory": cuda_memory_snapshot()' in service
    assert "cache_cleared = _clear_cuda_cache_after_oom(exc)" in service
    assert 'result["cuda_cache_cleared"] = True' in service
    assert "function inferenceCudaMemoryMetric" in ui
    assert "<label>CUDA Memory</label>" in ui
