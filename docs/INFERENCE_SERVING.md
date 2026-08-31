# Mortal-ROGS inference serving

Mortal-ROGS owns every Mortal checkpoint and exposes inference to Akagi-NG over the pinned AkagiOT HTTP contract. Akagi-NG never receives or directly loads a Mortal-ROGS `.pth` file.

## Akagi compatibility

Pinned Akagi-NG uses:

- 3P: `POST /react_batch_3p`
- 4P: `POST /react_batch`
- gzip JSON request bodies
- `Authorization` API key
- `obs` + legal-action `masks`
- a 2 second connect timeout and 4 second read timeout
- a circuit breaker that opens after 3 failed requests and probes recovery after 30 seconds

Mortal-ROGS therefore uses a default **3500 ms server deadline**. Queue saturation or a deadline miss returns HTTP 503 before Akagi's 4 second read timeout. The untouched Akagi `EngineProvider` can then use its own fallback path instead of waiting on a wedged HTTP request.

## Persistent models and hot reload

3P and 4P have independent model slots. Each slot keeps the last fully validated model published for inference.

A candidate checkpoint is loaded in a background mode-specific watcher:

1. read candidate checkpoint;
2. validate Mortal v4 mode/action/observation ABI;
3. strict-load `Brain` and `current_dqn`;
4. move to the configured device;
5. apply BF16/`torch.compile` when enabled;
6. warm batch sizes 1 and 2;
7. atomically publish the candidate.

Requests continue using the previous model while those steps execute. A rejected candidate marks the slot degraded but does not drop the last valid model. 3P and 4P watchers are separate, so compiling one mode does not block candidate publication for the other.

## Dynamic batching

Within-request batching remains supported. In addition, concurrent HTTP requests for the same mode can be coalesced into one GPU execution.

Defaults:

```text
micro_batch_ms          = 1.0
micro_batch_max_rows    = 64
max_pending_requests    = 128
request_deadline_ms     = 3500
reload_poll_ms          = 500
```

The scheduler is mode-separated: 3P requests never share a tensor batch with 4P requests.

All request shapes are checked before coalescing so one malformed request cannot poison unrelated requests in the same GPU batch. A full queue fails immediately with HTTP 503.

CLI/environment overrides are available on `scripts/serve_akagi_api.py`:

```text
--micro-batch-ms                  MORTAL_INFERENCE_MICRO_BATCH_MS
--micro-batch-max-rows            MORTAL_INFERENCE_MICRO_BATCH_MAX_ROWS
--max-pending-requests            MORTAL_INFERENCE_MAX_PENDING_REQUESTS
--request-deadline-ms             MORTAL_INFERENCE_REQUEST_DEADLINE_MS
--reload-poll-ms                  MORTAL_INFERENCE_RELOAD_POLL_MS
```

`request_deadline_ms` must remain below the pinned AkagiOT 4000 ms read timeout.

## Telemetry

`GET /api/inference/metrics` reports per-mode counters and recent latency percentiles:

- requests and rows
- requests/s and rows/s
- GPU executions
- coalesced request count
- average/max rows per execution
- current/peak queue depth
- busy rejections
- server deadline timeouts
- request p50/p95/p99/max
- queue p50/p95/p99/max
- model p50/p95/p99/max

`GET /health` includes the same serving snapshot under `serving`, so the Control Center can render live 3P/4P performance without a separate model ownership path.

## CI contracts

CI verifies:

- bounded queue backpressure;
- server-side deadline behavior;
- cross-request micro-batching;
- inference continuing on the published model while a replacement loads;
- invalid replacement fallback and background recovery;
- actual pinned AkagiOT 2s/4s timeout constants;
- 3-failure/30-second circuit breaker behavior;
- pinned `EngineProvider` fallback behavior;
- successful half-open recovery against the Mortal-ROGS server;
- read-only pinned Akagi-NG checkout.
