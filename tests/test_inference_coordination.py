from __future__ import annotations

import threading
import time

import pytest

from serving.coordination import DeviceExecutionCoordinator, InferenceDrainingError, RequestLifecycle


def test_device_execution_coordinator_serializes_modes_fairly() -> None:
    coordinator = DeviceExecutionCoordinator(max_parallel=1)
    barrier = threading.Barrier(3)
    active = 0
    peak_active = 0
    order: list[str] = []
    lock = threading.Lock()

    def worker(mode: str) -> None:
        nonlocal active, peak_active
        barrier.wait()
        with coordinator.execution(mode):
            with lock:
                active += 1
                peak_active = max(peak_active, active)
                order.append(mode)
            time.sleep(0.03)
            with lock:
                active -= 1

    threads = [threading.Thread(target=worker, args=(mode,)) for mode in ("3p", "4p")]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert peak_active == 1
    assert sorted(order) == ["3p", "4p"]
    metrics = coordinator.snapshot()
    assert metrics["max_parallel_executions"] == 1
    assert metrics["peak_active_executions"] == 1
    assert metrics["acquisitions_total"] == 2
    assert metrics["by_mode"]["3p"]["acquisitions"] == 1
    assert metrics["by_mode"]["4p"]["acquisitions"] == 1
    assert metrics["contended_acquisitions_total"] >= 1


def test_device_execution_coordinator_quiet_window() -> None:
    coordinator = DeviceExecutionCoordinator(max_parallel=1)
    entered = threading.Event()
    release = threading.Event()

    def worker() -> None:
        with coordinator.execution("3p"):
            entered.set()
            assert release.wait(timeout=2)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=1)
    assert coordinator.wait_for_quiet(idle_ms=5, timeout_ms=0) is False
    release.set()
    thread.join(timeout=2)
    assert coordinator.wait_for_quiet(idle_ms=5, timeout_ms=100) is True


def test_request_lifecycle_drains_existing_and_rejects_new_requests() -> None:
    lifecycle = RequestLifecycle()
    entered = threading.Event()
    release = threading.Event()
    completed: list[bool] = []

    def existing() -> None:
        with lifecycle.request():
            entered.set()
            assert release.wait(timeout=2)
            completed.append(True)

    request_thread = threading.Thread(target=existing)
    request_thread.start()
    assert entered.wait(timeout=1)

    drain_result: list[dict] = []

    def drain() -> None:
        drain_result.append(lifecycle.drain(1000))

    drain_thread = threading.Thread(target=drain)
    drain_thread.start()

    deadline = time.time() + 1
    while lifecycle.snapshot()["state"] != "draining" and time.time() < deadline:
        time.sleep(0.005)
    assert lifecycle.snapshot()["state"] == "draining"
    with pytest.raises(InferenceDrainingError):
        with lifecycle.request():
            pass

    release.set()
    request_thread.join(timeout=2)
    drain_thread.join(timeout=2)

    assert completed == [True]
    assert drain_result[0]["drained"] is True
    assert drain_result[0]["inflight_requests"] == 0
    assert lifecycle.snapshot()["rejected_during_drain_total"] == 1
