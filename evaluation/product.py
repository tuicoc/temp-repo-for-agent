"""The team's agent in this harness: :func:`evaluate` runs every stage, :func:`prepare` the first.

``run_eval.py evaluate --out runs/<name>`` calls :func:`evaluate`, which writes
one folder per stage under ``--out`` and never overwrites one:

| Folder | Stage | What to read |
|---|---|---|
| ``inputs/`` | :func:`prepare`: pinned scenarios, grading, manifest, adapter | ``preparation-report.json`` |
| ``raw/`` | P2 ``run_fixed``: the agent's hooks, every tool event | ``runner-report.json``, ``full/adapter-*.log`` |
| ``evidence/`` | P3 ``collect``: transcripts, extraction, memory, briefs, the BTC trace | ``full.jsonl``, ``baseline.jsonl``, ``validation.json`` |
| ``scored/`` | P4 ``score``: the organisers' grader and this harness's own checks | ``scorer.stdout.txt``, ``official-report.json``, ``supplemental-report.json`` |

``execution-report.json`` at the top sums up every stage. P6 (``report``) is
not run: it implements level M1, and these scenarios are M2.

:func:`prepare` calls no model. It writes into a new directory what ``run_fixed`` needs, each input pinned by
hash in the manifest: the five scenarios of ``datasets/output1-btc-diagnostic-v2``
(their provenance from ``output (1)`` checked against ``normalize_output1``),
one grading contract per scenario from ``fixtures/grading.json``, the scope,
the adapter (``product_adapter.py``) and the bundle naming the agent it
starts, the metrics policy, and the real extractor (``extractor-prompt.txt``
and the product's extraction command). The agent's model and parameters are
read from the backend's own ``config/models.yaml``, as the agent reads them.
"""
import hashlib
import json
from pathlib import Path
import subprocess

from eval_harness.assets import Assets, read_json
from eval_harness.case_trace import write as write_case_trace
from eval_harness.collector import collect
from eval_harness.contracts import ROOT, checker, validate
from eval_harness.datasets import close_output
from eval_harness.preflight import call_plan, preflight
from eval_harness.runner import _output_path, _write, run_fixed
from eval_harness.scoring import score
from normalize_output1 import convert
from product_adapter import tree_sha256
from tool_expectations import labels_for
from eval_harness.data_registry import inspect as inspect_data_registry

PRODUCT = ROOT.parent.parent / "backend"
PYTHON = PRODUCT / ".venv/bin/python"
DATASET = ROOT.parent / "datasets/output1-btc-diagnostic-v2/scenarios"
DATASETS = ROOT.parent / "datasets"
COMMAND = "src/pipeline/eval/extract_command.py"
CAPABILITIES = ["business_tools", "memory_isolation", "memory_read_gate", "after_call_barrier",
                "snapshots", "briefs", "timestamps", "usage"]
#: What the backend's interpreter reports about the agent it would run.
QUERY = ("import json; from src.config.config_manager import get_models_config; "
         "from src.pipeline.eval.bridge import parameters; m = get_models_config(); a = m.agent('advisor'); "
         "print(json.dumps({'provider': a.provider, 'model': a.model, 'parameters': parameters(a.provider, a.model), "
         "'extractor': m.agent_llm_config('extractor')}))")


def product_settings():
    result = subprocess.run([str(PYTHON), "-B", "-c", QUERY], cwd=PRODUCT, capture_output=True, text=True,
                            check=True, timeout=120)
    return json.loads(result.stdout.strip().splitlines()[-1])


def git_state():
    def git(*args):
        return subprocess.run(["git", *args], cwd=PRODUCT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def scenarios_with_provenance(source, only):
    """The five derived scenarios, each proved to be normalize_output1's output for its pinned original."""
    paths = sorted(source.glob("*.json"))
    report = read_json(source.parent / "conversion-report.json")
    if len(paths) != 5 or report.get("official_gt_approved") is not False or len(report.get("files", [])) != 5:
        raise ValueError("Require the five diagnostic revision files and their conversion report")
    for path, record in zip(paths, report["files"]):
        original = ROOT.parent / record["source"]
        if (record["derived"] != "scenarios/" + path.name or not original.is_file()
                or hashlib.sha256(original.read_bytes()).hexdigest() != record["source_sha256"]
                or read_json(path) != convert(read_json(original))[0]):
            raise ValueError(f"Scenario provenance changed: {path.name}")
    chosen = [p for p in paths if not only or read_json(p)["scenario_id"] in only]
    if not chosen:
        raise ValueError("No scenario matches --only")
    return report, chosen


def prepare(out, *, only=None, extractor_calls=64, dataset_id=None):
    checker.verify_sources()
    out = _output_path(out, Assets(PRODUCT))
    out.mkdir(parents=True, mode=0o700)
    assets = Assets(out)
    agent = product_settings()

    # The adapter, and the agent it starts.
    (out / "product_adapter.py").write_bytes((ROOT.parent / "product_adapter.py").read_bytes())
    _write(out / "product-bundle.json", {
        "schema_version": "product-bundle-v2", "python": str(PYTHON), "backend": str(PRODUCT),
        "tree_sha256": tree_sha256(PRODUCT), "git": git_state(),
        "llm": {"provider": agent["provider"], "model": agent["model"]},
        "notice": "The team's agent, run from backend/ with its .env; the evaluation database is backend's *_eval",
    })
    descriptor = {"kind": "runtime", "entrypoint": "product_adapter:factory",
                  "code": assets.ref("product_adapter.py"), "capabilities": CAPABILITIES}
    _write(out / "adapter.json", descriptor)

    # Scenarios and their grading contracts, as the diagnostic revision defines them.
    imported_labels = None
    if dataset_id is None:
        conversion, paths = scenarios_with_provenance(DATASET, only)
    else:
        inventory = inspect_data_registry(DATASETS, only=dataset_id)
        if inventory["issues"]:
            raise ValueError("Dataset registry has unresolved validation issues")
        groups = [g for g in read_json(DATASETS / "registry.json")["sets"] if g["id"] == dataset_id]
        if len(groups) != 1 or groups[0]["status"] != "approved":
            raise ValueError("Choose one independently approved registered dataset")
        group = groups[0]
        paths = sorted((DATASETS / group["path"]).glob("*.json"))
        if only:
            paths = [p for p in paths if read_json(p)["scenario_id"] in only]
        if not paths:
            raise ValueError("No registered scenario matches")
        imported_labels = read_json(DATASETS / group["tool_labels"])
        conversion = {"report_kind": "registered-dataset-v1", "dataset_id": dataset_id,
                      "split": group["split"], "reviewed_by": group["reviewed_by"],
                      "files": [{"scenario_id": read_json(p)["scenario_id"], "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    _write(out / "conversion-report.json", conversion)
    if imported_labels is not None:
        (out / "registered-tool-labels.json").write_bytes((DATASETS / group["tool_labels"]).read_bytes())
    (out / "scenarios").mkdir()
    (out / "grading").mkdir()
    (out / "expected-tools").mkdir()
    scenario_refs, grading_refs, tool_refs, scenarios = [], [], [], []
    for path in paths:
        item = read_json(path)
        validate("Scenario", item)
        (out / "scenarios" / path.name).write_bytes(path.read_bytes())
        ref = assets.ref("scenarios/" + path.name)
        scenario_refs.append(ref)
        scenarios.append(item)
        grader = read_json(ROOT / "fixtures/grading.json")
        grader.update(scenario=ref, scenario_id=item["scenario_id"], level=item["level"], calls=[])
        for call in item["calls"]:
            template = read_json(ROOT / "fixtures/grading.json")["calls"][0]
            template.update(call=call, official_success_if={**ref, "pointer": "/calls/" + call + "/success_if"},
                            ground_truth=[ref])
            template["suites"][0]["reason"] = "Generated diagnostic GT pending QA"
            expected = (labels_for(item["scenario_id"], call, item["calls"][call]["success_if"])
                        if imported_labels is None else imported_labels[item["scenario_id"]][call])
            for config in ("full", "baseline_no_memory"):
                label_path = f"expected-tools/{config}/{item['scenario_id']}/{call}.json"
                (out / label_path).parent.mkdir(parents=True, exist_ok=True)
                context = {"run_id": "PRODUCT-" + hashlib.sha256(str(out).encode()).hexdigest()[:16],
                           "config": config, "scenario_id": item["scenario_id"], "call": call, "turn": 1}
                _write(out / label_path, {"schema_version": "1.0.0",
                       "artifact_id": "/".join((context["run_id"], config, item["scenario_id"], call, "tool-labels")),
                       "run_id": context["run_id"], "evidence_refs": [ref], "context": context,
                       "calls": expected, "allow_extra_read_only": True,
                       "labelled_by": ("output1-diagnostic-tool-labels-pending-independent-QA" if imported_labels is None else group["reviewed_by"])})
                label_ref = assets.ref(label_path)
                tool_refs.append(label_ref)
                template["checks"].append({"check_id": "tool_accuracy_" + config,
                    "kind": "tool_accuracy", "params": {"expected_calls": label_ref},
                    "required_evidence": []})
            grader["calls"].append(template)
        _write(out / "grading" / path.name, grader)
        grading_refs.append(assets.ref("grading/" + path.name))

    manifest = read_json(ROOT / "fixtures/p6-manifest.json")
    suffix = hashlib.sha256(str(out).encode()).hexdigest()[:16]
    levels = {item["level"] for item in scenarios}
    if len(levels) != 1:
        raise ValueError("One run requires scenarios at one level")
    manifest.update(artifact_id="PRODUCT-Manifest", run_id="PRODUCT-" + suffix, level=levels.pop(), fixture=False,
                    scenarios=scenario_refs, grading_contracts=grading_refs)
    if imported_labels is not None:
        manifest["split"] = group["split"]
    manifest["configuration"].update(model=agent["model"], parameters=agent["parameters"],
                                     hardware="local backend, evaluation database")
    # A turn may wait on the provider's rate limit; the bridge starts five MCP servers.
    manifest["timeouts_ms"].update(agent=300000, after_call=300000)
    manifest["state_namespaces"] = {key: "product/" + suffix + "/" + key for key in manifest["state_namespaces"]}
    manifest["planned_calls"] = [
        {"config": config, "scenario_id": item["scenario_id"], "call": plan["call"],
         "expected_turns": plan["expected_turns"],
         "memory_required": config == "full" and bool(item["calls"][plan["call"]].get("must_carry_over"))}
        for config in ("full", "baseline_no_memory") for item in scenarios
        for plan in call_plan(item, manifest["reference_date"])]

    scope = read_json(ROOT / "fixtures/p1-scope.json")
    scope["notice"] = "Generated diagnostic scenarios; labels pending independent QA; report-only synthetic test"
    scope["source_decisions"] = [
        {**scope["source_decisions"][0], "origin": ref, "run_id": manifest["run_id"],
         "artifact_id": manifest["run_id"] + "/source-decision/" + str(index),
         "source_split": manifest["split"],
         "reason": ("User-provided generated data; report-only diagnostic; GT not approved" if imported_labels is None
                    else "Registered dataset reviewed by " + group["reviewed_by"] + "; report-only")}
        for index, ref in enumerate(scenario_refs)]
    if imported_labels is not None:
        scope["pii_review"] = {"status": "approved", "reviewed_by": group["reviewed_by"],
                               "scope": "authorized_redacted"}
    (out / "fixtures").mkdir()
    _write(out / "fixtures/p1-scope.json", scope)

    resources = []
    for key in ("prompt", "tools", "kb"):
        ref = manifest["configuration"][key]
        target = out / ref["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / ref["path"]).read_bytes())
        resources.append(ref)
    (out / "metrics-policy.json").write_bytes((ROOT / "fixtures/p6-metrics-policy.json").read_bytes())

    # The real extractor: the harness's prompt, the product's command, pinned.
    (out / "extractor-prompt.txt").write_bytes((ROOT.parent / "extractor-prompt.txt").read_bytes())
    (out / "extract_command.py").write_bytes((PRODUCT / COMMAND).read_bytes())
    extractor = {"kind": "command_model", "version": "product-extractor-v2", "python": str(PYTHON),
                 "backend": str(PRODUCT), "code": assets.ref("extract_command.py"), "files": [],
                 "config": agent["extractor"], "prompt": assets.ref("extractor-prompt.txt"),
                 "max_calls": extractor_calls}
    _write(out / "extractor.json", extractor)
    manifest["configuration"]["extractor_version"] = extractor["version"]

    manifest["sources"] = [assets.ref("fixtures/p1-scope.json"), *resources, *tool_refs, assets.ref("adapter.json"),
                           descriptor["code"], assets.ref("product-bundle.json"), assets.ref("metrics-policy.json"),
                           assets.ref("conversion-report.json"), assets.ref("extractor-prompt.txt"),
                           assets.ref("extract_command.py"), assets.ref("extractor.json")]
    if imported_labels is not None:
        manifest["sources"].append(assets.ref("registered-tool-labels.json"))
    _write(out / "manifest.json", manifest)
    _write(out / "settings.json", {"asset_root": ".", "manifest": "manifest.json",
                                   "scope": "fixtures/p1-scope.json", "adapter": assets.ref("adapter.json")})
    report = preflight(out / "settings.json")
    _write(out / "preparation-report.json", report)
    return {"settings": str(out / "settings.json"), "run_id": manifest["run_id"],
            "execution_gate": report["execution_gate"], "planned_turns": len(report["coverage_plan"]["expected_trace_ids"])}


def evaluate(out, *, only=None, extractor_calls=64, dataset_id=None):
    """Prepare, run, collect and score; ``execution-report.json`` sums it up."""
    out = _output_path(out, Assets(PRODUCT))
    out.mkdir(parents=True, mode=0o700)
    stages, failure = [], None
    try:
        prepared = prepare(out / "inputs", only=only, extractor_calls=extractor_calls, dataset_id=dataset_id)
        stages.append({"stage": "prepare", **prepared})
        if not prepared["execution_gate"]["allowed"]:
            raise ValueError("Prepared inputs did not pass the execution gate")
        raw = run_fixed(out / "inputs/settings.json", out / "raw")
        stages.append({"stage": "run", "execution_complete": raw["execution_complete"],
                       "completed_calls": raw["completed_calls"], "failed_calls": raw["failed_calls"],
                       "errors": raw["errors"]})
        evidence = collect(out / "raw", out / "evidence", extractor_path="extractor.json")
        stages.append({"stage": "collect", "status": evidence["status"], "trace_rows": evidence["trace_rows"],
                       "trace_wire_complete": evidence["trace_wire_complete"]})
        scored = score(out / "evidence", out / "scored")
        stages.append({"stage": "score", "status": scored["status"],
                       "official_report_available": scored["official_report_available"]})
    except (OSError, ValueError, KeyError, TypeError, AssertionError, RuntimeError) as exc:
        failure = f"{type(exc).__name__}: {exc}"
    report = {"report_kind": "product-evaluate-v1", "stages": stages, "pipeline_error": failure,
              "quality_accepted": False, "table": "scored/scorer.stdout.txt",
              "notice": "The team's agent on generated diagnostic scenarios whose labels await QA; "
                        "not BTC acceptance. P6 is M1-only and these scenarios are M2."}
    try:
        write_case_trace(out, report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report["pipeline_error"] = (report["pipeline_error"] + "; " if report["pipeline_error"] else "") + f"Case trace: {type(exc).__name__}: {exc}"
    _write(out / "execution-report.json", report)
    close_output(out)
    return report
