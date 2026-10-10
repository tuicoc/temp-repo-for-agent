"""Prepare a synthetic R0/R1 FAQ diagnostic pair; never calls a model or grants release."""
import argparse
import json
import os
from pathlib import Path

from prepare_product import prepare
from product_smoke import PRODUCT
from eval_harness.assets import Assets, read_json
from eval_harness.preflight import preflight
from eval_harness.runner import _output_path, _write

EVALUATION = Path(__file__).resolve().parent


def prepare_pair(out, r1_kb, provider, model, per_process, extractor_max):
    source=Path(r1_kb).resolve(strict=True)
    content=source.read_bytes()
    if not content.strip():
        raise ValueError("R1 FAQ resource cannot be empty")
    out=_output_path(out,Assets(PRODUCT))
    if not out.is_relative_to(EVALUATION/"integration"):
        raise ValueError("Diagnostic pair output must be under evaluation/integration")
    out.mkdir(parents=True,mode=0o700,exist_ok=False)
    policy={"schema_version":"p7-round-policy-v1","allowed_changed_configuration":["kb"]}
    for round_number in (0,1):
        folder=out/("r"+str(round_number))
        prepared=prepare(folder,True,provider,model,per_process,extractor_max,storage="postgresql")
        if not prepared["execution_gate"]["allowed"]:
            raise ValueError("Prepared product input gate blocked")
        assets=Assets(folder)
        manifest=read_json(folder/"manifest.json")
        manifest["round"]=round_number
        _write(folder/"round-policy.json",policy)
        manifest["sources"].append(assets.ref("round-policy.json"))
        if round_number==1:
            target=folder/"candidate-faq.md"
            target.write_bytes(content)
            old=manifest["configuration"]["kb"]
            current=assets.ref("candidate-faq.md")
            manifest["configuration"]["kb"]=current
            manifest["sources"]=[current if ref==old else ref for ref in manifest["sources"]]
            manifest["candidate_hash"]=current["sha256"]
        (folder/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        report=preflight(folder/"settings.json")
        if not report["execution_gate"]["allowed"]:
            raise ValueError("R"+str(round_number)+" gate blocked after FAQ pin")
    common=Assets(EVALUATION)
    for number in (0,1):
        config={"asset_root":os.path.relpath(EVALUATION,out),
                "execution_settings":common.ref(str((out/("r"+str(number))/"settings.json").relative_to(EVALUATION))),
                "extractor":"extractor.json",
                "asr":{"settings":common.ref("p5-settings.example.json"),"split":"eval","mode":"replay"}}
        _write(out/("r"+str(number)+"-benchmark-settings.json"),config)
    report={"kind":"synthetic-r0-r1-preparation-v1","r0_settings":str(out/"r0-benchmark-settings.json"),
            "r1_settings":str(out/"r1-benchmark-settings.json"),"candidate_hash":Assets(out/"r1").ref("candidate-faq.md")["sha256"],
            "model_attempt_envelope":2*(2*per_process+extractor_max),
            "notice":"Fixture/development diagnostic only. FAQ approval and source authority are not inferred."}
    _write(out/"pair-preparation.json",report)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--r1-kb",required=True,type=Path,help="QA-provided whole FAQ resource bytes; diagnostic only")
    parser.add_argument("--provider",required=True,choices=("groq","google_genai"))
    parser.add_argument("--model",required=True)
    parser.add_argument("--per-process",required=True,type=int)
    parser.add_argument("--extractor-max",required=True,type=int)
    args=parser.parse_args()
    print(json.dumps(prepare_pair(args.out,args.r1_kb,args.provider,args.model,args.per_process,args.extractor_max),ensure_ascii=False,indent=2))
