from __future__ import annotations

import argparse


MESSAGE = """Direct 3P/4P checkpoint loading inside Akagi-NG is no longer a Mortal-ROGS deployment path.

Akagi-NG remains an untouched external client application. Mortal-ROGS owns the
3P and 4P models and serves inference through Akagi-NG's existing AkagiOT HTTP
protocol:

  3P: POST /react_batch_3p
  4P: POST /react_batch

Use scripts/check_mortal_api_checkpoint.py for mode-specific server-side v4 ABI
validation and scripts/smoke_vanilla_akagi_client.py for compatibility against
an untouched pinned Akagi-NG checkout.
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deprecated: Mortal-ROGS to Akagi-NG integration is API-only."
    )
    parser.add_argument("--akagi-root", nargs="?")
    parser.add_argument("--model", nargs="?")
    parser.add_argument("--mode", choices=("3p", "4p"))
    parser.add_argument("--abi", nargs="?")
    parser.add_argument("--allow-akagi-drift", action="store_true")
    parser.parse_args()
    print(MESSAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
