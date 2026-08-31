from __future__ import annotations

import argparse


MESSAGE = """Direct Akagi-NG checkpoint compatibility probing is retired.

Mortal-ROGS no longer asks Akagi-NG to load Mortal checkpoints and never imports
Akagi-NG's local Mortal model loader for deployment validation.

Use these API-only checks instead:

  1. Server-side checkpoint ABI:
     scripts/check_mortal_api_checkpoint.py

  2. Mortal-ROGS HTTP service E2E:
     scripts/smoke_akagi_api.py

  3. Untouched pinned Akagi-NG AkagiOT client E2E:
     scripts/smoke_vanilla_akagi_client.py

The user-facing deployment path is: run Mortal-ROGS locally, start its inference
API, then configure a separately downloaded untouched Akagi-NG with the server
URL and matching API key.
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deprecated: Akagi-NG integration is API-only."
    )
    parser.add_argument("--akagi-root", nargs="?")
    parser.add_argument("--model", nargs="?")
    parser.add_argument("--require-v4", action="store_true")
    parser.parse_args()
    print(MESSAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
