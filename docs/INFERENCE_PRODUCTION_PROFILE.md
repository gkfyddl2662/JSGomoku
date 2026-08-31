# Production serving profile transaction

A production serving profile is created only from the latest soak report that passed the full `mortal-rogs-serving-soak-v1` production gate. Short CI smoke reports cannot be activated as production profiles.

The active profile is stored under the unified runtime at `runtime/serving-profiles/production.json` using protocol `mortal-rogs-serving-profile-v1`. The file contains host/port/device, serving scheduler and reload/drain settings, and the source soak summary. The Akagi API key is deliberately never persisted.

## Apply sequence

Control Center `POST /api/inference/production/apply` performs one serialized transaction:

1. Validate that the latest soak report is a real production PASS and contains an eligible preset.
2. Atomically write the candidate profile with status `applying` using fsync + same-directory `os.replace`.
3. Ask the current Mortal inference server to graceful-drain already accepted requests.
4. Stop the old Control-Center-managed inference process.
5. Start a replacement process using every measured production setting, including shared-device serialization, reload quiet/wait, and drain timeout. The API key is passed only through `MORTAL_INFERENCE_API_KEY`, not process arguments.
6. Wait for both Mortal v4 models to be loaded/current, lifecycle RUNNING, no degraded health, and exact scheduler/reload/device/drain settings.
7. Atomically mark the profile `active`.

Only one production transaction may run at a time, and benchmark/soak jobs must be stopped before activation.

## Rollback

Any failure after the candidate profile is written triggers rollback. Control Center stops the candidate process if necessary, restores the exact previous profile bytes (or removes the new file if no previous profile existed), restarts the previous serving target, and verifies its health/settings before reporting rollback success.

A failed apply returns HTTP 409 with rollback details. A rollback is not considered successful merely because a process was spawned; the restored server must pass the same model/lifecycle/serving verification.

## Fixed RTX 5080 rule

Production profiles require `max_device_executions = 1`. The 3P and 4P models still micro-batch independently before the shared forward gate, but simultaneous model forward execution on the one RTX 5080 is not allowed in the production profile.

## Validation

Contract CI forces both successful and failed transactions and verifies exact profile-byte restoration. Native CI additionally uses real trained 3P/4P Mortal checkpoints to perform a successful apply, then intentionally starts an invalid-device candidate and verifies automatic rollback to the last healthy profile/server.
