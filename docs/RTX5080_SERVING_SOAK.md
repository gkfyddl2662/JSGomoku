# RTX 5080 serving soak validation

The Control Center can run a long mixed 3P/4P soak against the already-running Mortal-ROGS inference server. The default production gate is intentionally stricter than the short benchmark/A-B sweep.

## Default production run

- Duration: 30 minutes minimum.
- Modes: 3P + 4P mixed continuously.
- Concurrency: 8 clients.
- Rows per request: 1.
- Server telemetry sample interval: 1 second.
- p95 budget: 100 ms.
- p99 budget: 250 ms.
- Peak VRAM ceiling: 92%.
- Peak GPU temperature ceiling: 88 C.
- NVIDIA telemetry: required from `nvidia-smi` when launched from the Control Center.
- Reload stress: off by default. It can be enabled explicitly to probe maintenance admission under sustained traffic.

A run shorter than 30 minutes is still stored as a smoke report, but cannot become production eligible through the Control Center.

## Collected data

Each report records per-mode request counts, status counts, error rate, rows/s, latency p50/p95/p99/max, server timeout and busy-rejection deltas, shared-device contention and wait metrics, lifecycle state, degraded health samples, model-signature stability, optional reload attempts, and sampled NVIDIA GPU VRAM/utilization/temperature/power.

Reports are written under the unified runtime at `runtime/serving-benchmarks/soak-*.json` using protocol `mortal-rogs-serving-soak-v1`.

## Production gate

The gate requires all of the following:

- minimum soak duration reached;
- no failed/client requests;
- no server busy rejection or deadline timeout;
- p95 and p99 stay inside their configured budgets;
- shared-device peak execution does not exceed the configured serialization limit;
- no degraded-health sample;
- loaded checkpoint signatures remain stable during the measurement window;
- optional reload stress has no failed/deferred attempt when enabled;
- when GPU telemetry is required, peak VRAM and temperature stay below their ceilings.

A passing report emits `MORTAL_INFERENCE_PRODUCTION_PRESET_OK`. The resulting preset keeps `max_device_executions=1`, preserves the measured micro-batch wait, sizes pending capacity from observed queue/concurrency, and derives conservative deadline/reload admission values from measured p99 latency.

The Web UI can copy the serving fields that are currently restart-configurable in the Control Center back into the tuning form. Device serialization remains fixed at one execution for the RTX 5080 production path.

## CI boundary

GitHub CPU CI does not claim RTX 5080 performance. It runs the same soak code for a very short real-checkpoint smoke with relaxed latency limits and no required NVIDIA telemetry. This verifies workload generation, report schema, production-gate logic, preset generation, and shared-device serialization without fabricating RTX 5080 numbers.
