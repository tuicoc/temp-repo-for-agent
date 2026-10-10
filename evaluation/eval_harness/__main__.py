"""Offline contracts, preflight, execution and evidence replay."""
import argparse
import json
from pathlib import Path


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage()
        self.exit(3, f"{self.prog}: error: {message}\n")


def main(argv=None):
    parser = Parser(description="P0 offline checks / P1 preflight / P2 execution / P3 replay / P4 scoring / P5 ASR / P6 metrics")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    product = commands.add_parser("evaluate", help="The team's agent through prepare, run, collect and score; output in --out")
    product.add_argument("--out", type=Path, help="A new run directory (default: evaluation/runs/<date-time>)")
    product.add_argument("--only", action="append", default=[], metavar="SCENARIO_ID", help="Run one scenario; repeat for more")
    product.add_argument("--extractor-calls", type=int, default=64, help="Budget of extraction calls, 1-64")
    suite=commands.add_parser("suite-bundle",help="P8–P10 closed producer evidence adapters; no live inference/production activation")
    suite.add_argument("--inputs",required=True,type=Path)
    suite.add_argument("--out",required=True,type=Path)
    release=commands.add_parser("release-gate",help="P7 verified candidate release recommendation; no deployment mutation")
    release.add_argument("--inputs",required=True,type=Path)
    release.add_argument("--out",required=True,type=Path)
    package=commands.add_parser("package",help="P10 immutable handoff/readiness; does not certify missing A01–A18")
    package.add_argument("--inputs",required=True,type=Path)
    package.add_argument("--out",required=True,type=Path)
    rounds = commands.add_parser("compare-rounds", help="P7 diagnostic R0/R1 comparison/readiness; never activates production")
    rounds.add_argument("--r0", required=True, type=Path)
    rounds.add_argument("--r1", type=Path)
    rounds.add_argument("--out", required=True, type=Path)
    metrics = commands.add_parser("report", help="P6 immutable M1 metric/comparison/table replay; no Agent/model")
    metrics.add_argument("--run", required=True, type=Path, help="Closed P4 score run")
    metrics.add_argument("--asr-run", type=Path, help="Closed P5 team eval ASR run")
    metrics.add_argument("--usage-run", type=Path, help="Closed reconciled billing ledger; never fills missing usage with zero")
    metrics.add_argument("--casebook-run", type=Path, help="Closed casebook review with independent retest evidence")
    metrics.add_argument("--out", required=True, type=Path)
    bench = commands.add_parser("benchmark", help="P6 one-command M1 using explicit paired execution and ASR settings")
    bench.add_argument("--settings", required=True, type=Path)
    bench.add_argument("--out", required=True, type=Path)
    pair = commands.add_parser("benchmark-rounds", help="Run pinned R0 and R1 through P2–P7; diagnostic hold")
    pair.add_argument("--r0-settings", required=True, type=Path)
    pair.add_argument("--r1-settings", required=True, type=Path)
    pair.add_argument("--out", required=True, type=Path)
    pair.add_argument("--max-model-attempts", type=int, help="Required hard cap for runtime rounds; preflight counts both Agent configurations and extractor")
    readiness = commands.add_parser("dataset-readiness", help="P5 pinned inventory; no inference or dataset generation")
    readiness.add_argument("--settings", required=True, type=Path)
    readiness.add_argument("--out", required=True, type=Path)
    asr = commands.add_parser("asr-suite", help="P5 existing ASR adapter; replay by default, not a new speed benchmark")
    asr.add_argument("--settings", required=True, type=Path)
    asr.add_argument("--out", required=True, type=Path)
    asr.add_argument("--split", choices=("dev", "eval"), default="eval")
    asr.add_argument("--mode", choices=("replay", "infer"), default="replay")
    pre = commands.add_parser("preflight", help="Validate pinned planned inputs without running an Agent")
    pre.add_argument("--settings", required=True, type=Path)
    pre.add_argument("--scenarios", type=Path, help="Optional directory; must exactly match manifest")
    pre.add_argument("--out", type=Path, help="New JSON report file; never overwrites an existing file")
    pre.add_argument("--for-execution", action="store_true",
                     help="Exit by P2 input gate; still does not bind/run an adapter")
    run = commands.add_parser("run", help="P2 fixed-turn execution only; no quality scoring/trace export")
    run.add_argument("--settings", required=True, type=Path)
    run.add_argument("--scenarios", type=Path)
    run.add_argument("--config", choices=("full", "baseline_no_memory"), help="Default runs both configs")
    run.add_argument("--round", help="Must match pinned manifest.round, e.g. R0")
    run.add_argument("--out", required=True, type=Path, help="New raw run directory, NOT a BTC JSONL file")
    collect = commands.add_parser("collect", help="P3 immutable evidence validation; command_model extractor calls model only when explicitly pinned")
    collect.add_argument("--run", required=True, type=Path)
    collect.add_argument("--extractor", help="Descriptor path relative to the run's pinned inputs")
    collect.add_argument("--audit-seed", type=int, default=0)
    collect.add_argument("--out", required=True, type=Path)
    export = commands.add_parser("export-trace", help="Export complete BTC wire cohort, not quality acceptance")
    export.add_argument("--run", required=True, type=Path)
    export.add_argument("--config", required=True, choices=("full", "baseline_no_memory"))
    export.add_argument("--out", required=True, type=Path)
    scoring = commands.add_parser("score", help="P4 BTC CLI + supplemental checks; no Agent/model/DB")
    scoring.add_argument("--run", required=True, type=Path)
    scoring.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        from datetime import datetime
        from product import evaluate  # beside run_eval.py; it drives the backend's agent
        out = args.out or Path(__file__).resolve().parents[1] / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
        report = evaluate(out, only=set(args.only), extractor_calls=args.extractor_calls)
        print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
        print("Run written to", out.resolve())
        table = out / "scored" / "scorer.stdout.txt"
        if table.is_file():
            print(table.read_text(encoding="utf-8"))
        if report["pipeline_error"]:
            return 3
        status = report["stages"][-1].get("status") or {}
        return 1 if status.get("verdict") == "FAIL" else 2 if status.get("completeness") == "INCOMPLETE" else 0
    if args.command in ("suite-bundle","release-gate","package"):
        from .suite_bundle import evaluate_bundle
        from .release import release_gate
        from .package import handoff_package
        try:
            report=({"suite-bundle":evaluate_bundle,"release-gate":release_gate,"package":handoff_package}[args.command])(args.inputs,args.out)
            print(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2))
            if args.command=="release-gate":return 0 if report["decision"]=="active" else 2
            return 1 if report["status"]["verdict"]=="FAIL" else 2 if report["status"]["completeness"]=="INCOMPLETE" else 0
        except (OSError,ValueError,KeyError,TypeError,AssertionError) as exc:
            print("Suite/release config or integrity error:",exc)
            return 3
    if args.command == "compare-rounds":
        from .rounds import compare_rounds
        try:
            report = compare_rounds(args.r0,args.out,r1_run=args.r1)
            print(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2))
            return 1 if report["status"]["verdict"]=="FAIL" else 2 if report["status"]["completeness"]=="INCOMPLETE" else 0
        except (OSError,ValueError,KeyError,TypeError,AssertionError) as exception:
            print(f"P7 config/integrity error: {exception}")
            return 3
    if args.command == "benchmark-rounds":
        from .benchmark import benchmark_rounds
        try:
            report = benchmark_rounds(args.r0_settings, args.r1_settings, args.out,
                                      max_model_attempts=args.max_model_attempts)
            print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
            return 2  # Diagnostic hold is never a release/acceptance success exit.
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exception:
            print(f"R0/R1 benchmark config/integrity error: {exception}")
            return 3
    if args.command in ("report", "benchmark"):
        from .reporting import report_metrics
        from .benchmark import benchmark
        try:
            report = (benchmark(args.settings, args.out) if args.command == "benchmark"
                      else report_metrics(args.run, args.out, asr_run=args.asr_run, usage_run=args.usage_run, casebook_run=args.casebook_run))
            print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
            if args.command == "benchmark" and report["table_ref"]:
                print((args.out / report["table_ref"]["path"]).read_text())
            return 1 if report["status"]["verdict"] == "FAIL" else 2 if report["status"]["completeness"] == "INCOMPLETE" else 0
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exception:
            print(f"P6 config/integrity error: {exception}")
            return 3
    if args.command in ("dataset-readiness", "asr-suite"):
        from .datasets import dataset_readiness
        from .asr_suite import asr_suite
        try:
            report = (dataset_readiness(args.settings, args.out) if args.command == "dataset-readiness"
                      else asr_suite(args.settings, args.out, split=args.split, mode=args.mode))
            print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
            return 2 if report["status"]["completeness"] == "INCOMPLETE" else 0
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exception:
            print(f"P5 config/integrity error: {exception}")
            return 3
    if args.command == "score":
        from .scoring import score
        try:
            report = score(args.run, args.out)
            print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
            return 1 if report["status"]["verdict"] == "FAIL" else 2 if report["status"]["completeness"] == "INCOMPLETE" else 0
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exception:
            print(f"Score config/integrity error: {exception}")
            return 3
    if args.command == "export-trace":
        from .collector import export_trace
        try:
            report = export_trace(args.run, args.out, args.config)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["exported"] else 2
        except (OSError, ValueError, KeyError, TypeError) as exception:
            print(f"Export config/integrity error: {exception}")
            return 3
    if args.command == "collect":
        from .collector import collect
        try:
            report = collect(args.run, args.out, extractor_path=args.extractor, audit_seed=args.audit_seed)
            print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
            return 1 if report["status"]["verdict"] == "FAIL" else 2 if report["status"]["completeness"] == "INCOMPLETE" else 0
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exception:
            print(f"Collector config/integrity error: {exception}")
            return 3
    if args.command == "run":
        from .runner import run_fixed
        try:
            report = run_fixed(args.settings, args.out, config=args.config,
                               scenarios_dir=args.scenarios, round_name=args.round)
            print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
            return 2  # P3+ scoring/suites missing even if P2 execution_complete=true.
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exception:
            print(f"Runner config/infra error: {exception}")
            return 3
    if args.command == "preflight":
        from .preflight import preflight
        from .contracts import ROOT
        try:
            if args.out is not None and args.out.exists():
                raise ValueError("Output already exists; choose a new file")
            protected = (ROOT / "sources/btc", ROOT.parent / "BTC-Data-Vong1-TEAMS", ROOT.parent.parent / "BTC-Data-Vong1-TEAMS")
            if args.out is not None and any(args.out.resolve().is_relative_to(path.resolve()) for path in protected):
                raise ValueError("Never write reports inside protected BTC sources")
            report = preflight(args.settings, args.scenarios)
            rendered = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
            if args.out is not None:
                with args.out.open("x", encoding="utf-8") as output:
                    output.write(rendered + "\n")
            print(rendered)
            if args.for_execution:
                return 0 if report["execution_gate"]["allowed"] else 2
            return 2 if report["validation"]["issues"] else 0
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exception:
            print(f"Preflight config/infra error: {exception}")
            return 3
    raise AssertionError("Unhandled evaluation command")


if __name__ == "__main__":
    raise SystemExit(main())
