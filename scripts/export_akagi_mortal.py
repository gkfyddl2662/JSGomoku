from __future__ import annotations

import argparse
from pathlib import Path


DEPRECATION_MESSAGE = """Direct Mortal checkpoint export into Akagi-NG is disabled.

Mortal-ROGS owns and loads all 3P/4P checkpoints inside Mortal_Unified.
Run the Mortal-ROGS inference API instead and configure an untouched Akagi-NG
installation to use the API URL:

  server:  http://127.0.0.1:8190
  3P:      POST /react_batch_3p
  4P:      POST /react_batch

From the Mortal-ROGS Web UI, use SERVING -> Akagi-NG · Mortal API.
No Mortal-ROGS .pth file should be copied into or loaded by Akagi-NG.
"""


def parse_args() -> argparse.Namespace:
    # Keep the historical CLI shape so old automation fails with an actionable
    # message instead of silently copying a checkpoint into Akagi-NG.
    p = argparse.ArgumentParser(
        description="Deprecated: Mortal-ROGS serves models to Akagi-NG through HTTP only."
    )
    p.add_argument("source", type=Path, nargs="?")
    p.add_argument("destination", type=Path, nargs="?")
    return p.parse_args()


def main() -> int:
    parse_args()
    print(DEPRECATION_MESSAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
