from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from evaluation.paired import evaluate_promotion_records, load_paired_records, load_rating_profiles


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Promote a Mortal checkpoint only after statistical and Akagi ABI gates pass"
    )
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--paired-results", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--mode", choices=("3p", "4p"), required=True)
    parser.add_argument("--akagi-root", type=Path, required=True)
    parser.add_argument(
        "--presets",
        type=Path,
        default=project / "config" / "rating_presets.toml",
    )
    parser.add_argument("--resamples", type=int, default=5000)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--min-rating-mean", type=float, default=0.0)
    parser.add_argument("--min-rating-lower", type=float, default=0.0)
    parser.add_argument("--min-rank-improvement", type=float, default=0.0)
    parser.add_argument("--max-last-place-regression", type=float, default=0.003)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    candidate = args.candidate.resolve()
    destination = args.destination.resolve()
    akagi_root = args.akagi_root.resolve()
    if not candidate.is_file() or candidate.suffix != ".pth":
        raise SystemExit(f"Candidate checkpoint does not exist or is not .pth: {candidate}")
    if candidate == destination:
        raise SystemExit("Candidate and destination must be different paths")

    rows = load_paired_records(args.paired_results)
    expected_players = 3 if args.mode == "3p" else 4
    if rows[0].players != expected_players:
        raise SystemExit(
            f"Evaluation result mode mismatch: file is {rows[0].players}P but --mode={args.mode}"
        )

    profiles = load_rating_profiles(args.presets)
    if args.profile not in profiles:
        raise SystemExit(f"Unknown rating profile: {args.profile}")
    decision = evaluate_promotion_records(
        rows,
        profile_name=args.profile,
        profile=profiles[args.profile],
        resamples=args.resamples,
        confidence=args.confidence,
        min_rating_mean=args.min_rating_mean,
        min_rating_lower=args.min_rating_lower,
        min_rank_improvement=args.min_rank_improvement,
        max_last_place_regression=args.max_last_place_regression,
    )

    report = {
        "candidate": str(candidate),
        "destination": str(destination),
        "mode": args.mode,
        "profile": args.profile,
        "games": len(rows),
        "statistics_passed": decision.passed,
        "statistics_reason": decision.reason,
        "abi_passed": False,
        "promoted": False,
        "metrics": [
            {
                "name": metric.name,
                "passed": metric.passed,
                "mean_delta": metric.estimate.mean_delta,
                "lower": metric.estimate.lower,
                "upper": metric.estimate.upper,
                "confidence": metric.estimate.confidence,
            }
            for metric in decision.metrics
        ],
    }

    if decision.passed:
        abi = project / "scripts" / "check_akagi_compat_dual.py"
        proc = subprocess.run(
            [
                sys.executable,
                str(abi),
                "--akagi-root",
                str(akagi_root),
                "--model",
                str(candidate),
                "--mode",
                args.mode,
            ],
            text=True,
            capture_output=True,
        )
        report["abi_stdout"] = proc.stdout
        report["abi_stderr"] = proc.stderr
        report["abi_passed"] = proc.returncode == 0
        if proc.returncode == 0:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".promoting")
            shutil.copy2(candidate, temporary)
            temporary.replace(destination)
            report["promoted"] = True

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.report.resolve().write_text(text + "\n", encoding="utf-8")

    if not report["statistics_passed"]:
        return 10
    if not report["abi_passed"]:
        return 11
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
