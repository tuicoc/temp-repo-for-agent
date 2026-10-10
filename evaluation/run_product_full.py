"""Bounded real-model run of the current development cohort, not BTC acceptance."""
import argparse
import json
from pathlib import Path

from prepare_product import prepare
from product_smoke import PRODUCT
from eval_harness.runner import run_fixed, _write, _output_path
from eval_harness.assets import Assets, read_json
from eval_harness.collector import collect
from eval_harness.scoring import score
from eval_harness.asr_suite import asr_suite
from eval_harness.reporting import report_metrics
from eval_harness.datasets import close_output


def run(out, *, provider="groq", model="openai/gpt-oss-20b", per_process=30, extractor_max=4, hard_cap=64):
    if type(per_process) is not int or type(extractor_max) is not int or type(hard_cap) is not int or min(per_process, extractor_max, hard_cap) < 1:
        raise ValueError("Positive integer API budgets required")
    if 2 * per_process + extractor_max > hard_cap:
        raise ValueError("Planned two configurations plus extractor exceed hard cap")
    out=_output_path(out,Assets(PRODUCT));out.mkdir(parents=True,mode=0o700)
    _write(out/"execution-budget.json",{"provider":provider,"model":model,"agent_memory_per_process":per_process,
        "configurations":2,"scenarios":1,"extractor_max":extractor_max,"maximum_model_attempts":hard_cap,
        "asr_mode":"replay","notice":"Explicit bounded current-scope run; no retry/cohort expansion or production calls"})
    stages=[];failure=None
    try:
        prepared=prepare(out/"inputs",True,provider,model,per_process,extractor_max,storage="postgresql")
        if not prepared["execution_gate"]["allowed"]:raise ValueError("Prepared input gate blocked")
        raw=run_fixed(out/"inputs/settings.json",out/"raw")
        stages.append({"stage":"run","execution_complete":raw["execution_complete"],"completed_calls":raw["completed_calls"],"errors":raw["errors"]})
        evidence=collect(out/"raw",out/"evidence",extractor_path="extractor.json")
        stages.append({"stage":"collect","status":evidence["status"],"trace_rows":evidence["trace_rows"]})
        scored=score(out/"evidence",out/"scored")
        stages.append({"stage":"score","status":scored["status"]})
        asr=asr_suite(Path(__file__).parent/"p5-settings.example.json",out/"asr",split="eval",mode="replay")
        stages.append({"stage":"asr","status":asr["status"]})
        metrics=report_metrics(out/"scored",out/"metrics",asr_run=out/"asr")
        stages.append({"stage":"metrics","status":metrics["status"]})
    except (OSError,ValueError,KeyError,TypeError,AssertionError) as exc:
        failure=type(exc).__name__+": "+str(exc)
    report={"report_kind":"product-full-current-scope-v1","stages":stages,"pipeline_error":failure,"quality_accepted":False,
            "notice":"Real "+provider+" execution on synthetic current cohort; ASR historical replay; not entire M1/M2/BTC acceptance"}
    _write(out/"execution-report.json",report);close_output(out)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--provider",required=True,choices=("groq","google_genai"))
    parser.add_argument("--model",required=True)
    parser.add_argument("--per-process",required=True,type=int)
    parser.add_argument("--extractor-max",required=True,type=int)
    parser.add_argument("--hard-cap",required=True,type=int)
    args=parser.parse_args()
    print(json.dumps(run(args.out,provider=args.provider,model=args.model,per_process=args.per_process,
                         extractor_max=args.extractor_max,hard_cap=args.hard_cap),ensure_ascii=False,indent=2))
