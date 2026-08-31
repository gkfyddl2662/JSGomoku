# Production profile recovery

An activated production profile survives Control Center and machine restarts at `runtime/serving-profiles/production.json`.

The profile deliberately does **not** persist the Akagi API key. To restore the inference server after a reboot, the Control Center takes the current API Key input from the Web UI, injects it only into the new process environment as `MORTAL_INFERENCE_API_KEY`, and launches the saved host/port/device and all saved serving settings.

## Restore contract

`POST /api/inference/production/start` accepts an API key and health-verification timeout. It requires an `active` `mortal-rogs-serving-profile-v1` profile and restores:

- micro-batch wait and row cap;
- pending request capacity;
- server deadline below the pinned AkagiOT 4-second read timeout;
- reload polling, quiet admission and wait window;
- graceful drain timeout;
- the fixed RTX 5080 shared-device policy `max_device_executions=1`;
- the saved device target.

After the process starts, both 3P and 4P Mortal v4 models must be loaded/current with no model error, lifecycle must be RUNNING/accepting, and every serving setting plus the concrete model device must match the active profile.

## Conflict handling

Recovery is intentionally conservative. If a Control-Center-managed inference job already exists and is not already an exact verified profile match, recovery refuses to replace it; the operator can use production apply or stop it first. If no managed job exists but another process responds on the saved address, recovery treats it as an unmanaged conflict and does not kill or adopt it.

This prevents a restarted Control Center from accidentally terminating an independently managed service or replacing a live configuration without the transactional apply path.

## Drift reporting

`GET /api/inference/production/status` reports the persisted profile together with the observable live state. When authorization is available in the current Control Center process, it compares the live scheduler/reload/drain/device/model state with the profile and returns MATCH or a concrete drift list. After a fresh Control Center restart with an API-key-protected server, status may report authorization-unverified until the key is re-entered.

## Validation

Contract CI verifies runtime-only key injection, active-profile reconstruction, device drift detection, recovery endpoint ownership and unmanaged-process protection. Native CI stops the real trained-checkpoint server after apply/rollback, reconstructs the target from the persisted active profile, starts it again, and requires an exact live profile match. The native marker is `MORTAL_INFERENCE_PRODUCTION_RESTORE_E2E_OK`.
