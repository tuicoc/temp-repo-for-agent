"""P3 offline replay of immutable P2 runs; no Agent/model/scorer invocation."""
from collections import Counter, defaultdict
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random

from .assets import Assets, parse_json, read_json
from .contracts import ROOT, checker, validate
from .extractor import FixtureExtractor, digest, extractor_input
from .runner import _output_path, _write


def context_key(context):
    return "/".join(str(context[key]) for key in ("run_id", "config", "scenario_id", "call", "turn"))


def expects_call_brief(context, result):
    return (context["config"] == "full" and context["call"] != "call_1"
            and result.get("customer_id") not in (None, "unidentified"))


def status(issues):
    failed = any(i["classification"] == "agent_violation" for i in issues)
    incomplete = any(i["classification"] != "agent_violation" for i in issues)
    return {"verdict": "FAIL" if failed else "UNDETERMINED" if incomplete else "PASS",
            "completeness": "INCOMPLETE" if incomplete else "COMPLETE",
            "reason_codes": sorted({i["code"] for i in issues})}


def locked_run(path):
    assets = Assets(path)
    lock = read_json(assets.path("artifacts.lock.json"))
    if set(lock) != {"files"} or not isinstance(lock["files"], dict):
        raise ValueError("Run requires P2 closed-file inventory/hash lock")
    actual = {str(p.relative_to(assets.root)) for p in assets.root.rglob("*") if p.is_file()}
    if actual != set(lock["files"]) | {"artifacts.lock.json"}:
        raise ValueError("Run inventory differs from closed-file lock")
    for name, sha in lock["files"].items():
        assets.resolve({"path": name, "sha256": sha, "pointer": ""}, json_content=False)
    return assets, lock


def milliseconds(start, end):
    if start is None or end is None:
        return None
    a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    if a.utcoffset() is None or b.utcoffset() is None or b < a:
        raise ValueError("Missing timezone or negative backend duration")
    return round((b - a).total_seconds() * 1000)


def export_trace(run_dir, out, config):
    """Export a complete wire cohort, independently of Agent quality verdict."""
    assets, _ = locked_run(run_dir)
    target = _output_path(out, assets)
    manifest = read_json(assets.path("manifest.json"))
    validate("Manifest", manifest)
    coverage = read_json(assets.path("coverage/btc_trace.json"))
    validate("Coverage", coverage)
    report = read_json(assets.path("collector-report.json"))
    if not report["trace_wire_complete"] or coverage["status"]["completeness"] != "COMPLETE":
        return {"exported": False, "reason": "Incomplete wire evidence/coverage", "quality_accepted": False}
    filename = {"full": "full.jsonl", "baseline_no_memory": "baseline.jsonl"}[config]
    payload = assets.path(filename).read_bytes()
    rows = [parse_json(line) for line in payload.decode("utf-8").splitlines()]
    expected = [context_key({"run_id": manifest["run_id"], **p, "turn": t})
                for p in manifest["planned_calls"] if p["config"] == config
                for t in range(1, p["expected_turns"] + 1)]
    if not expected or Counter(expected) != Counter(context_key(row) for row in rows):
        return {"exported": False, "reason": "Selected config has missing/duplicate/unknown turns", "quality_accepted": False}
    for row in rows:
        errors = checker.errors("sources/btc/schemas/trace_log.schema.json", row)
        if errors:
            raise ValueError(str(errors[0].message))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(payload)
    locked_run(run_dir)
    return {"exported": True, "rows": len(rows), "quality_accepted": False, "fixture": manifest["fixture"]}


def collect(run_dir, out, *, extractor_path=None, audit_seed=0):
    source, lock = locked_run(run_dir)  # Integrity check BEFORE creating output.
    out = _output_path(out, source)
    manifest = read_json(source.path("manifest.json"))
    validate("Manifest", manifest)
    plan = read_json(source.path("execution-plan.json"))
    configs = plan["configs"]
    if not configs or len(configs) != len(set(configs)) or set(configs) - {"full", "baseline_no_memory"}:
        raise ValueError("Unknown/duplicate planned configs")
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    raw = out / "raw"
    raw.mkdir()
    for name in list(lock["files"]) + ["artifacts.lock.json"]:
        payload = source.path(name).read_bytes()
        if name in lock["files"] and hashlib.sha256(payload).hexdigest() != lock["files"][name]:
            raise ValueError("Run changed while snapshotting for replay")
        target = raw / name
        if not target.resolve().is_relative_to(raw):
            raise ValueError("Unsafe replay path")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(payload)
    assets = Assets(out)
    _write(out / "manifest.json", manifest)
    manifest_ref = assets.ref("manifest.json")
    issues = []
    documents, doc_refs, turn_results = {}, {}, {}
    memories, briefs, timings, extractions = [], [], [], []
    starts, ends, answers, customers, events = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    tool_events, tool_phase, raw_results = [], {}, []

    def issue(code, message, classification="missing_evidence", ref=None):
        entry = {"code": code, "artifact": ref or manifest_ref, "json_pointer": "",
                 "message": message, "classification": classification}
        validate("Issue", entry)
        issues.append(entry)

    def write(name, data):
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, data)
        return assets.ref(name)

    def raw_lines(name):
        try:
            return source.path(name).read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            issue("RAW_FILE_MISSING", f"{name}: {exc}")
            return []

    def artifact(definition, context, suffix, **fields):
        obj = {"schema_version": "1.0.0", "artifact_id": context_key(context) + "/" + suffix,
               "run_id": manifest["run_id"], "context": copy.deepcopy(context), **fields}
        validate(definition, obj)
        return obj

    expected = [f"{manifest['run_id']}/{p['config']}/{p['scenario_id']}/{p['call']}/{t}"
                for p in manifest["planned_calls"] if p["config"] in configs
                for t in range(1, p["expected_turns"] + 1)]
    if expected != plan["expected_ids"]:
        # Ordering may legitimately differ by config; sets and counts must not.
        if Counter(expected) != Counter(plan["expected_ids"]):
            issue("PLAN_MISMATCH", "Manifest and execution-plan expected IDs disagree", "schema_error")
    pinned_inputs = Assets(raw / "inputs")
    scenarios = {}
    for ref in manifest["scenarios"]:
        try:
            scenario = pinned_inputs.resolve(ref)
            validate("Scenario", scenario)
            scenarios[scenario["scenario_id"]] = scenario
        except (OSError, ValueError, KeyError) as exc:
            issue("SCENARIO_INPUT_MISSING", str(exc))
    preflight = read_json(source.path("preflight.json"))
    for item in preflight["validation"]["issues"]:
        issue(item["code"], item["message"], item["classification"])
    execution = read_json(source.path("runner-report.json"))
    if not execution["execution_complete"]:
        issue("EXECUTION_INCOMPLETE", "P2 runner did not complete; replay preserves partial and expected coverage")

    # Materialize JSON arrays so every source is addressable by real JSON Pointer.
    for config in configs:
        rows = []
        for number, line in enumerate(raw_lines(f"{config}/raw-execution.jsonl"), 1):
            try:
                rows.append(parse_json(line))
            except (ValueError, TypeError) as exc:
                issue("RAW_JSON_INVALID", f"{config} line{number}: {exc}", "schema_error",
                      assets.ref(f"raw/{config}/raw-execution.jsonl"))
        rows_ref = write(f"{config}/raw-records.json", rows)
        current_hook, current_scope, barrier_complete = None, None, True
        for index, record in enumerate(rows):
            ref = {**rows_ref, "pointer": f"/{index}"}
            try:
                kind, data = record["kind"], record["data"]
                if kind == "hook_request":
                    current_hook = data["hook"]
                    if current_hook == "open_scenario":
                        current_scope = {k: data["args"][0][k] for k in ("run_id", "config", "scenario_id")}
                        barrier_complete = True
                    elif current_hook == "start_call":
                        if not barrier_complete:
                            issue("CALL_BEFORE_BARRIER", "Next call started before confirmed after-call completion", "schema_error", ref)
                        barrier_complete = False
                scope = record.get("scope") or current_scope
                phase = record.get("phase") or current_hook  # Compatible with immutable old P2 runs.
                context = record.get("context")
                if context is not None:
                    validate("Context", context)
                    if context["run_id"] != manifest["run_id"] or context["config"] != config or context["scenario_id"] not in scenarios:
                        raise ValueError("Raw context outside registered run/config/scenario")
                    if scope is not None and any(context[k] != scope[k] for k in scope):
                        raise ValueError("Scope and context disagree")
                if kind == "customer_input":
                    customers[context_key(context)].append((data, ref))
                elif kind == "adapter_message" and data["type"] == "result":
                    hook = data["hook"]
                    if phase != hook:
                        raise ValueError("Result phase/hook disagree")
                    if hook == "run_turn":
                        answers[context_key(context)].append((context, data["result"], ref))
                    elif hook in ("start_call", "end_call"):
                        anchor = {**context, "turn": 1}
                        target = starts if hook == "start_call" else ends
                        target[context_key(anchor)].append((anchor, data["result"], ref))
                        if hook == "end_call":
                            barrier_complete = isinstance(data["result"], dict) and data["result"].get("completed") is True and data["result"].get("barrier_complete") is True
                elif kind == "adapter_message" and data["type"] == "event" and context:
                    events[context_key(context)].append((data["event"], ref, phase))
                elif kind == "tool_audit" and "event" in data:
                    event = data["event"]
                    tool_phase[event["event_id"]] = phase
                    raw_results.append((event, ref))
            except (ValueError, TypeError, KeyError) as exc:
                issue("RAW_MAPPING", f"{config} record{index}: {exc}", "schema_error", ref)
        for line in raw_lines(f"{config}/tools.jsonl"):
            try:
                event = parse_json(line)
                validate("ToolEvent", event)
                ctx = event["context"]
                if ctx["config"] != config or ctx["run_id"] != manifest["run_id"]:
                    raise ValueError("Tool event belongs to another config/run")
                milliseconds(event["started_at"], event["finished_at"])
                matching = [(e, ref) for e, ref in raw_results if e["event_id"] == event["event_id"]]
                if len(matching) != 1 or matching[0][0] != event:
                    raise ValueError("Tool event/audit mismatch or duplicate")
                event = copy.deepcopy(event)
                event["evidence_refs"] = [matching[0][1]]
                tool_events.append(event)
            except (ValueError, KeyError, TypeError) as exc:
                issue("TOOL_EVIDENCE_INVALID", str(exc), "schema_error", assets.ref(f"raw/{config}/tools.jsonl"))
    for key, candidates in answers.items():
        if len(candidates) != 1 or len(customers[key]) != 1:
            issue("TURN_DUPLICATE_OR_INPUT_MISSING", key, "schema_error")
            continue
        context, result, result_ref = candidates[0]
        customer, customer_ref = customers[key][0]
        if not isinstance(result, dict) or not isinstance(result.get("agent_text"), str) or not isinstance(customer.get("text"), str):
            issue("TURN_OUTPUT_INVALID", key, "schema_error", result_ref)
            continue
        if key not in expected:
            issue("TURN_UNKNOWN", key, "schema_error", result_ref)
            continue
        spec = scenarios[context["scenario_id"]]["calls"][context["call"]]
        fed = spec.get("customer_turns_asr", spec["customer_turns"])
        if customer["text"] != fed[context["turn"] - 1]:
            issue("CUSTOMER_INPUT_MISMATCH", key, "schema_error", customer_ref)
        before_candidates = starts[context_key({**context, "turn": 1})]
        before = before_candidates[0][1] if len(before_candidates) == 1 and isinstance(before_candidates[0][1], dict) else {}
        before_memory = before.get("memory_snapshot")
        before_memory = before_memory if isinstance(before_memory, dict) else {}
        current_tools = [e for e in tool_events if context_key(e["context"]) == key]
        consultants = [event["text"] for event, _, _ in events[key]
                       if isinstance(event, dict) and event.get("role") == "consultant" and isinstance(event.get("text"), str)]
        document = {"context": context, "customer_text": customer["text"], "agent_text": result["agent_text"],
                    "customer_id": before.get("customer_id", before_memory.get("customer_id")), "consultant_texts": consultants,
                    "tools": current_tools, "tool_texts": [json.dumps(e["request"], ensure_ascii=False, sort_keys=True) for e in current_tools],
                    "evidence_refs": [customer_ref, result_ref]}
        ref = write(f"{context['config']}/transcripts/{digest(key)}.json", document)
        documents[key], doc_refs[key], turn_results[key] = document, ref, (result, result_ref)

    def source_ref(origin):
        if isinstance(origin, dict) and set(origin) == {"context", "field"}:
            key = context_key(origin["context"])
            if key not in doc_refs or origin["field"] not in ("customer_text", "agent_text"):
                raise ValueError("Memory origin must identify a collected customer/agent string")
            return {**doc_refs[key], "pointer": "/" + origin["field"]}
        validate("AssetRef", origin)
        ref = {**origin, "path": "raw/inputs/" + origin["path"]}
        if "/seed_history" not in ref["pointer"]:
            raise ValueError("Dataset labels/GT cannot supply runtime memory provenance")
        assets.resolve(ref)
        return ref

    memory_keys = set(starts) | set(ends) | set(answers)
    for call_key in sorted(memory_keys):
        phases = [("after_turn", answers[call_key])] if call_key in answers else []
        if call_key in starts or call_key in ends:
            phases += [("before_call", starts[call_key]), ("after_call", ends[call_key])]
        for phase, candidates in phases:
            if len(candidates) != 1:
                issue("MEMORY_PHASE_MISSING_OR_DUPLICATE", call_key + "/" + phase)
                continue
            context, result, raw_ref = candidates[0]
            try:
                snapshot = copy.deepcopy(result["memory_snapshot"])
                for item in snapshot["facts"] + snapshot["writes"]:
                    item["source"] = source_ref(item["source"])
                    if item["customer_id"] != snapshot["customer_id"]:
                        issue("MEMORY_WRONG_PROFILE", call_key, "agent_violation", raw_ref)
                    if item["source"]["path"].startswith(context["config"] + "/transcripts/"):
                        source_doc = read_json(assets.path(item["source"]["path"]))
                        if source_doc["customer_id"] != item["customer_id"]:
                            issue("MEMORY_SOURCE_PROFILE", call_key, "agent_violation", raw_ref)
                        origin_context = source_doc["context"]
                        if any(origin_context[k] != context[k] for k in ("run_id", "config", "scenario_id")):
                            issue("MEMORY_SOURCE_SCOPE", call_key, "agent_violation", raw_ref)
                        origin_order = (origin_context["call"], origin_context["turn"])
                        current_order = (context["call"], context["turn"])
                        if (origin_context["call"] > context["call"]
                                or phase == "before_call" and origin_context["call"] >= context["call"]
                                or phase == "after_turn" and origin_order > current_order):
                            issue("MEMORY_SOURCE_FUTURE", call_key, "agent_violation", raw_ref)
                obj = artifact("MemoryEvidence", context, phase, evidence_refs=[raw_ref], phase=phase,
                               **{k: snapshot[k] for k in ("customer_id", "namespace", "facts", "writes")})
                namespace = f"{manifest['state_namespaces'][context['config']]}/{manifest['run_id']}/{context['scenario_id']}"
                if obj["namespace"] != namespace:
                    issue("MEMORY_NAMESPACE", call_key, "agent_violation", raw_ref)
                for fact in obj["facts"]:
                    if fact["valid_until"] is not None:
                        milliseconds(fact["valid_from"], fact["valid_until"])
                memories.append(obj)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                issue("MEMORY_EVIDENCE_MISSING", f"{call_key}/{phase}: {exc}", ref=raw_ref)
            if phase == "before_call":
                result = result if isinstance(result, dict) else {}
                brief = result.get("call_brief")
                if brief is not None:
                    if result.get("customer_id") in (None, "unidentified"):
                        issue("BRIEF_UNVERIFIED_PROFILE", call_key, "agent_violation", raw_ref)
                    brief_ref = write(f"{context['config']}/briefs/{digest(call_key)}.json", brief)
                    errors = checker.errors("sources/btc/schemas/call_brief.schema.json", brief)
                    if errors:
                        issue("BRIEF_INVALID", str(errors[0].message), "agent_violation", brief_ref)
                    try:
                        milliseconds(result["identified_at"], result["brief_ready_at"])
                        briefs.append(artifact("BriefEvidence", context, "call_brief", evidence_refs=[raw_ref],
                            kind="call_brief", object_ref=brief_ref, identified_at=result["identified_at"],
                            ready_at=result["brief_ready_at"], producer="memory_agent",
                            validation={"verdict": "FAIL" if errors else "PASS", "completeness": "COMPLETE",
                                        "reason_codes": ["BRIEF_INVALID"] if errors else []}))
                    except (ValueError, KeyError, TypeError) as exc:
                        issue("BRIEF_TIMING_MISSING", str(exc), ref=brief_ref)
                elif expects_call_brief(context, result):
                    issue("BRIEF_MISSING", call_key, ref=raw_ref)

    # Handoff object is captured at invocation, never replaced with Call Brief.
    for event in tool_events:
        if event["request"]["name"] == "handoff.transfer":
            context, brief = event["context"], event["request"]["args"].get("brief")
            ref = write(f"{context['config']}/handoffs/{digest(event['event_id'])}.json", brief)
            invalid = checker.errors("sources/btc/schemas/handoff_brief.schema.json", brief)
            if invalid:
                issue("HANDOFF_INVALID", invalid[0].message, "agent_violation", ref)
            metadata = [e for e, _, _ in events[context_key(context)] if isinstance(e, dict)
                        and e.get("kind") == "handoff_brief" and e.get("object") == brief]
            try:
                if len(metadata) != 1:
                    raise ValueError("Handoff timing metadata missing/duplicate")
                meta = metadata[0]
                milliseconds(meta["identified_at"], meta["ready_at"])
                briefs.append(artifact("BriefEvidence", context, event["event_id"] + "/brief", evidence_refs=event["evidence_refs"],
                    kind="handoff_brief", object_ref=ref, identified_at=meta["identified_at"], ready_at=meta["ready_at"], producer="agent",
                    validation={"verdict": "FAIL" if invalid else "PASS", "completeness": "COMPLETE",
                                "reason_codes": ["HANDOFF_INVALID"] if invalid else []}))
            except (ValueError, KeyError, TypeError) as exc:
                issue("HANDOFF_TIMING_MISSING", str(exc), ref=ref)

    extractor = None
    if extractor_path:
        try:
            ref = pinned_inputs.ref(extractor_path)
            if pinned_inputs.resolve(ref).get("kind")=="command_model":
                from .model_extractor import ModelExtractor
                extractor = ModelExtractor(pinned_inputs,ref,manifest,
                    lambda i,data:write("extractor-raw/attempt-"+str(i)+".json",data))
            else:
                extractor = FixtureExtractor(pinned_inputs, ref, manifest)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            issue("EXTRACTOR_CONFIG", str(exc))
    else:
        issue("EXTRACTOR_NOT_CONFIGURED", "Pass a pinned fixture descriptor; no implicit extraction")
    traces = defaultdict(list)
    warmup_index = Counter()
    for key, document in documents.items():
        context = document["context"]
        result, raw_ref = turn_results[key]
        timing = latency = None
        try:
            usage = result.get("usage") or {}
            first_token = result.get("first_token_at")
            if first_token is None and result.get("mode") == "nonstream":
                first_token = result.get("completed_at")  # Explicit BTC nonstream protocol, not a fake sample.
            before_entries = starts[context_key({**context, "turn": 1})]
            before = before_entries[0][1] if len(before_entries) == 1 and context["turn"] == 1 and isinstance(before_entries[0][1], dict) else {}
            timing = artifact("TimingEvidence", context, "timing", schema_version="1.1.0",
                request_at=result["request_at"], first_token_at=first_token,
                completed_at=result.get("completed_at"), first_audio_at=result.get("first_audio_at"),
                brief_identified_at=before.get("identified_at"), brief_ready_at=before.get("brief_ready_at"),
                warmup=warmup_index[context["config"]] < manifest["warmup_count"],
                audio_seconds=result.get("audio_seconds"), asr_wall_ms=result.get("asr_wall_ms"),
                input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                cost=usage.get("cost"), currency=usage.get("currency"), concurrency_group=result.get("concurrency_group"),
                evidence_refs=[raw_ref])
            total = milliseconds(timing["request_at"], timing["completed_at"])
            first = milliseconds(timing["request_at"], timing["first_token_at"])
            if total is not None and first is not None and first <= total:
                audio = milliseconds(timing["request_at"], timing["first_audio_at"])
                if audio is not None and audio > total:
                    raise ValueError("First audio follows backend completion")
                latency = {"ttft_ms": first, "total_ms": total,
                           "ttfa_ms": audio}
            else:
                issue("TRACE_TIMING_MISSING", key, ref=raw_ref)
            timings.append(timing)
            warmup_index[context["config"]] += 1
            if any(timing[k] is None for k in ("input_tokens", "output_tokens", "cost", "currency")):
                issue("USAGE_MISSING", key, ref=raw_ref)
        except (ValueError, KeyError, TypeError) as exc:
            issue("TIMING_INVALID_OR_MISSING", f"{key}: {exc}", ref=raw_ref)
        extraction = None
        if extractor:
            try:
                replay = extractor.replay(document)
                cache_key = digest({"input": extractor_input(document), "context": context, "descriptor": extractor.descriptor})
                replay_ref = write(f"cache/{cache_key}.json", {"input_sha256": digest(extractor_input(document)), "items": replay})
                items = []
                for original in replay:
                    item = copy.deepcopy(original)
                    field = item.pop("source_field")
                    if not isinstance(field, str):
                        raise ValueError("Extraction source_field must be a string")
                    if field == "agent_text":
                        speaker = "agent"
                    elif field.startswith("consultant_texts/"):
                        speaker = "consultant"
                    elif field.startswith("tool_texts/"):
                        speaker = "tool"
                    else:
                        raise ValueError("Extraction source role unsupported; never read GT/memory")
                    if item["speaker"] != speaker:
                        raise ValueError("Extractor speaker disagrees with actual source")
                    item["source"] = {**doc_refs[key], "pointer": "/" + field}
                    source_string = assets.resolve(item["source"])
                    if (not isinstance(source_string, str) or item["start"] < 0 or item["end"] > len(source_string)
                            or item["end"] <= item["start"] or source_string[item["start"]:item["end"]] != item["quote"]):
                        raise ValueError("Quote differs from Unicode source slice")
                    if item["kind"] == "question" and (speaker != "agent" or item["question_type"] not in ("open", "confirm")):
                        raise ValueError("Only actual Agent questions can populate questions")
                    if item["kind"] != "question" and item["question_type"] is not None:
                        raise ValueError("Non-question must have question_type=null")
                    if item["kind"] == "fact_usage" and (speaker not in ("agent", "tool") or not item["purpose"]):
                        raise ValueError("Fact usage needs actual Agent/tool usage and purpose")
                    items.append(item)
                if len({digest(item) for item in items}) != len(items):
                    raise ValueError("Duplicate extraction items")
                extraction = artifact("Extraction", context, "extraction", evidence_refs=[doc_refs[key], replay_ref],
                                      extractor_version=extractor.version, items=items)
                extractions.append(extraction)
            except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
                issue("EXTRACTION_MISSING_OR_INVALID", f"{key}: {exc}", ref=doc_refs[key])
        if extraction is not None and latency is not None:
            spec = scenarios[context["scenario_id"]]["calls"][context["call"]]
            items = extraction["items"]
            row = {**context, "customer_text": document["customer_text"], "agent_text": document["agent_text"],
                   "questions": [{"slot": i["slot_or_field"], "type": i["question_type"], "text": i["quote"]}
                                 for i in items if i["kind"] == "question" and i["speaker"] == "agent"],
                   "claims": [{"field": i["slot_or_field"], "value": i["value"], "text": i["quote"]}
                              for i in items if i["kind"] == "claim" and i["speaker"] == "agent"],
                   "facts_used": [i["slot_or_field"] for i in items if i["kind"] == "fact_usage"],
                   "tool_calls": [{**e["request"], "result": e["result"]} for e in document["tools"]], "latency": latency}
            if "customer_turns_asr" in spec:
                mode = spec.get("input_mode")
                if mode not in ("asr_transcript", "chat_teencode"):
                    issue("INPUT_MODE_UNRESOLVED", key)
                    continue
                row["customer_input_mode"] = mode
            else:
                row["customer_input_mode"] = "clean"
            if context["turn"] == 1 and context["call"] != "call_1" and timing:
                try:
                    row["call_brief_latency_ms"] = milliseconds(timing["brief_identified_at"], timing["brief_ready_at"])
                except (ValueError, TypeError):
                    issue("BRIEF_TIMING_INVALID", key)
            if "memory_expectation" in spec:
                available = [m for m in memories if m["context"]["config"] == context["config"]
                             and m["context"]["scenario_id"] == context["scenario_id"]
                             and m["context"]["call"] == context["call"] and m["phase"] == "after_call"]
                if len(available) != 1:
                    issue("MEMORY_WRITES_MISSING", key)
                    continue
                row["memory_writes"] = [write for write in available[0]["writes"]
                                        if write["source"].get("path") == doc_refs[key]["path"]
                                        and write["source"].get("pointer") == "/customer_text"]
            schema_errors = checker.errors("sources/btc/schemas/trace_log.schema.json", row)
            if schema_errors:
                issue("TRACE_SCHEMA", str(schema_errors[0].message), "schema_error", doc_refs[key])
            else:
                traces[context["config"]].append(row)

    # Missing and duplicate source rows remain visible even if no valid trace emitted.
    def coverage(name, observed):
        counts = Counter(observed)
        missing, duplicate, unknown = sorted(set(expected) - set(observed)), sorted(k for k, n in counts.items() if n > 1), sorted(set(observed) - set(expected))
        obj = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/" + name,
               "run_id": manifest["run_id"], "scope": name, "expected_ids": expected, "observed_ids": observed,
               "missing_ids": missing, "duplicate_ids": duplicate, "unknown_ids": unknown,
               "status": {"verdict": "UNDETERMINED" if missing or duplicate or unknown else "PASS",
                          "completeness": "INCOMPLETE" if missing or duplicate or unknown else "COMPLETE",
                          "reason_codes": ["COVERAGE_GAP"] if missing or duplicate or unknown else []}}
        validate("Coverage", obj)
        if missing or duplicate or unknown:
            issue("COVERAGE_GAP", name + ": missing/duplicate/unknown IDs")
        return write("coverage/" + name + ".json", obj)
    coverage_refs = [coverage("raw_turns", [key for key, values in answers.items() for _ in values]),
                     coverage("extraction", [context_key(e["context"]) for e in extractions]),
                     coverage("btc_trace", [context_key(r) for values in traces.values() for r in values])]
    for config in configs:
        for filename, values in (("tools.jsonl", [e for e in tool_events if e["context"]["config"] == config]),
                                 ("memory.jsonl", [m for m in memories if m["context"]["config"] == config]),
                                 ("timing.jsonl", [t for t in timings if t["context"]["config"] == config]),
                                 ("brief-evidence.jsonl", [b for b in briefs if b["context"]["config"] == config]),
                                 ("extraction.jsonl", [e for e in extractions if e["context"]["config"] == config])):
            path = out / config / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                for value in values:
                    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
        with (out / ("full.jsonl" if config == "full" else "baseline.jsonl")).open("x", encoding="utf-8") as stream:
            for row in traces[config]:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    selected = random.Random(audit_seed).sample(sorted(documents), min(20, len(documents)))
    write("extractor-audit.json", {"seed": audit_seed, "sampling_frame": sorted(documents),
                                   "selected_ids": selected, "source_refs": [doc_refs[k] for k in selected],
                                   "reviews": [], "notice": "Human review pending; never model-generated human labels"})
    issue("EXTRACTOR_AUDIT_PENDING", f"Exported {len(selected)}/20 turns; independent human review still required")
    report = {"schema_version": "1.0.0", "artifact_id": manifest["run_id"] + "/collector",
              "run_id": manifest["run_id"], "status": status(issues), "issues": issues, "coverage_refs": coverage_refs}
    validate("ValidationReport", report)
    write("validation.json", report)
    wire_ready = (Counter(expected) == Counter(key for key, values in answers.items() for _ in values)
                  and set(expected) == {context_key(r) for rows in traces.values() for r in rows}
                  and len(expected) == sum(map(len, traces.values()))
                  and not any(i["classification"] == "schema_error" for i in issues))
    summary = {"notice": "P3 immutable collector; fixture replay or explicit pinned command_model extraction. Audit pending, not quality acceptance",
               "run_id": manifest["run_id"], "fixture": manifest["fixture"], "trace_wire_complete": wire_ready,
               "status": report["status"], "trace_rows": sum(map(len, traces.values())), "typed_memory_records": len(memories),
               "deferred": preflight["deferred"], "btc_full_readiness": "INCOMPLETE", "scoring": "PENDING_P4"}
    write("collector-report.json", summary)
    write("artifacts.lock.json", {"files": {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in sorted(out.rglob("*")) if p.is_file()}})
    locked_run(run_dir)  # Source integrity still holds; never mutate a closed run.
    return summary
