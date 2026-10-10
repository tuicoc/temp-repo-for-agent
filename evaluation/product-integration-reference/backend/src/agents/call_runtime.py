"""Local isolated lifecycle shared by Advisor and MemoryAgent, not production DB."""
import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from math import isfinite
import re
from .runtime_store import RuntimeStore
from .pii import mask_pii
from .orchestrator import OrchestratorAgent

from langchain_core.messages import AIMessage, HumanMessage


def stamp():
    return datetime.now(timezone.utc).isoformat()


class CallRuntime:
    """One store/namespace per scenario/config; commit is the after-call barrier."""
    def __init__(self, context, advisor, memory, call_tool, options=None, emit=None, store=None, policy=None, qa=None):
        if context.get("seed_history"):
            raise ValueError("Seed history import not implemented; do not invent provenance")
        self.context, self.advisor, self.memory = context, advisor, memory
        self.candidate=context.get("candidate")
        self.call_tool, self.options = call_tool, options or {}
        self.emit=emit
        self.orchestrator=OrchestratorAgent()
        self.policy, self.qa = policy, qa
        self.store = store or RuntimeStore(context["namespace"])
        self.db = self.store.db
        if self.store.namespace != context["namespace"]:
            raise ValueError("Store namespace differs from runtime")
        self.call=None
        self.closed=False
        self.failed=False
        self.lane="IDENTITY_RESOLUTION"
        history = self.store.history()
        self.last_call=max((int(call.split("_")[1]) for call,status,_ in history if status=="COMPLETED"), default=0)
        self.last_date=max((context["on"] for _,status,context in history if status=="COMPLETED"), default=None)
        self.last_end = None
        self.timeline=[]
        self.tool_event_index=0
        self.memory_reader=None

    @classmethod
    def resume_persist_job(cls, store, customer, call, memory, options=None):
        saved=store.call_record(customer,call)
        if not saved or saved["status"] not in ("OPEN","FINALIZING"):
            raise RuntimeError("Only an unfinished call can resume persistence")
        if store.job_status(customer,call,"persist") not in ("PENDING","RUNNING"):
            raise RuntimeError("No recoverable persistence job")
        context=saved["context"]
        if any(event.get("outcome") in ("attempted","unknown") for event in store.business_events(customer,call)):
            raise RuntimeError("Unknown tool outcome requires reconciliation")
        runtime=cls({"run_id":context["run_id"],"config":context["config"],"scenario_id":context["scenario_id"],
                     "namespace":store.namespace,"seed_history":[],"resources":{}},None,memory,None,options,store=store)
        runtime.call=context
        runtime.customer_id=customer
        runtime.turn=max((turn for turn,_ in store.turn_history(customer,call)),default=0)
        runtime.at=context["on"]+"T00:00:00+07:00"
        runtime.writes=[]
        runtime.recover_persist=True
        return runtime

    def start_call(self, context):
        if self.closed or self.failed or self.call is not None:
            raise RuntimeError("Cannot start before a committed barrier or after failure")
        if any(context[k]!=self.context[k] for k in ("run_id","config","scenario_id")):
            raise ValueError("Call outside runtime scope")
        if context["memory_read_previous"] != (self.context["config"]=="full"):
            raise ValueError("Memory read policy differs from configuration")
        if context["call"]!="call_"+str(self.last_call+1) or self.last_date and context["on"]<self.last_date:
            raise ValueError("Call order/date invalid")
        identified=stamp()
        phone=context["customer_phone"]
        channel=context.get("channel","phone")
        channel_identity=context.get("channel_identity")
        unlinked_channel=channel in ("zalo","facebook") and bool(channel_identity) and context.get("cross_channel_confirmed") is not True
        if context.get("anonymous") or unlinked_channel:
            # A channel identifier is not authority to merge a phone profile.
            crm={"found":False,"ambiguous":False}
        elif channel=="zalo" and channel_identity:
            crm=self.call_tool("crm.get_customer",{"zalo_id":channel_identity})
        elif channel=="facebook" and channel_identity:
            crm=self.call_tool("crm.get_customer",{"fb_id":channel_identity})
        else:
            crm=self.call_tool("crm.get_customer",{"phone":phone})
        if not isinstance(crm,dict):
            raise ValueError("Customer identity lookup returned an invalid result")
        ambiguous=bool(crm.get("ambiguous"))
        customer=crm.get("customer_id") if crm.get("found") else None
        if ambiguous:
            # A shared phone is not an identity. Keep this call isolated until
            # a person resolves it; never attach another profile's memory.
            customer="unresolved-"+hashlib.sha256((self.context["namespace"]+context["call"]+str(context["scenario_id"])).encode()).hexdigest()[:16]
        elif unlinked_channel:
            customer="unlinked-"+hashlib.sha256((self.context["namespace"]+str(channel_identity)).encode()).hexdigest()[:16]
        elif not customer:
            customer="local-"+hashlib.sha256((self.context["namespace"]+phone).encode()).hexdigest()[:16]
        self.customer_id=customer
        persisted_context={k:v for k,v in context.items() if k!="customer_phone"}
        persisted_context["customer_phone_hash"]=hashlib.sha256(phone.encode()).hexdigest()
        if self.candidate:
            persisted_context["candidate_id"]=self.candidate["candidate_id"]
            persisted_context["candidate_hash"]=self.candidate["content_hash"]
        self.store.open_call(customer, persisted_context)
        self.call=copy.deepcopy(context)
        from .mcp_memory import LocalMCPMemoryReader
        self.memory_reader=LocalMCPMemoryReader(self.store,customer)
        self.turn=0
        self.messages=[]
        self.writes=[]
        self.at=context["on"]+"T00:00:00+07:00"
        date.fromisoformat(context["on"])
        visible=self.snapshot()
        previous=self.memory_reader.sessions(limit=10) if context["memory_read_previous"] else []
        from .memory import MemoryAgent
        brief_lines=MemoryAgent.render_brief(visible["facts"],previous)
        values={f["key"]:f["value"] for f in visible["facts"]}
        ready=stamp()
        identity_status="ambiguous" if ambiguous else "cross_channel_unlinked" if unlinked_channel else "verified" if crm.get("found") else "new_or_unverified"
        self.brief={"identity_status":identity_status,"customer_phone":phone,
            "customer_name":None if ambiguous else crm.get("name"),
            "honorific":None if ambiguous else crm.get("honorific",context.get("honorific")),"is_returning":bool(previous),
            "n_previous_sessions":len(previous),"last_session":previous[-1] if previous else None,
            "profile_facts":values,"products_advised":previous[-1].get("products_advised",[]) if previous else [],"open_blockers":[values["blocker"]] if values.get("blocker") else [],
            "lines":brief_lines,
            "must_not_ask":list(values),"suggested_opening":"Xác nhận danh tính trước khi đọc hồ sơ." if ambiguous or unlinked_channel else "Xác nhận tiếp nối ngắn gọn, không hỏi mở slot đã có.",
            "generated_at":ready,"latency_ms":round((datetime.fromisoformat(ready)-datetime.fromisoformat(identified)).total_seconds()*1000),
            "stale_warnings":["Giá/KM/tồn kho phải tra tool theo ngày hiện tại; brief không xác nhận giá cũ."]}
        self.tier="ambiguous" if ambiguous else "verified" if crm.get("found") and crm.get("verified",True) else "new"
        return {"customer_id":customer,"memory_snapshot":visible,"call_brief":self.brief,
                "identified_at":identified,"brief_ready_at":ready}

    def snapshot(self):
        if self.call is None:
            raise RuntimeError("No current call snapshot")
        facts=[]
        stored_facts=self.memory_reader.facts() if self.memory_reader and self.call["memory_read_previous"] else self.store.facts(self.customer_id)
        for fact in stored_facts:
            active=fact["state"]=="active" and fact["valid_from"]<=self.at and (fact["valid_until"] is None or self.at<fact["valid_until"])
            current=fact["source"]["context"]["call"]==self.call["call"]
            if active and (self.call["memory_read_previous"] or current):facts.append(fact)
        return {"customer_id":self.customer_id,"namespace":self.context["namespace"],"facts":facts,"writes":copy.deepcopy(self.writes)}

    def validate_facts(self, draft, text):
        proposals=draft["facts"]
        seen=set()
        for item in proposals:
            key,value=item["key"],item["value"]
            if key in seen or key not in ("room_area_m2","budget_vnd","has_children","size","color","blocker","address","intent","product","product_variant","customer_quote_vnd","promotion_interest","callback_request","decision_maker","customer_outcome","order_reference"):
                raise ValueError("Duplicate/unsupported memory slot")
            seen.add(key)
            if type(item["start"]) is not int or type(item["end"]) is not int or not 0<=item["start"]<item["end"]<=len(text) or text[item["start"]:item["end"]]!=item["quote"]:
                raise ValueError("Memory quote/span does not match customer input")
            if "█" in item["quote"] or re.search(r"(?<!\d)\d{12}(?!\d)",item["quote"]):
                raise ValueError("Sensitive ID must not enter profile memory")
            if item["op"]=="delete":
                if value is not None:raise ValueError("Delete value must be null")
            elif item["op"]!="set" or key in ("room_area_m2","budget_vnd","customer_quote_vnd") and (type(value) not in (int,float) or value<=0) or key=="has_children" and type(value) is not bool or key not in ("room_area_m2","budget_vnd","customer_quote_vnd","has_children") and (not isinstance(value,str) or not value.strip()):
                raise ValueError("Invalid memory value type/action")
            if type(value) in (int,float) and not isfinite(value):raise ValueError("Nonfinite memory value")
            if key in ("budget_vnd","customer_quote_vnd") and item["op"]=="set" and type(value) is not int:raise ValueError("VND values must be integer")
    def commit_facts(self, draft, text, source_turn=None, *, in_transaction=False):
        self.validate_facts(draft, text)
        from contextlib import nullcontext
        with nullcontext() if in_transaction else self.store.transaction():
            for item in draft["facts"]:
                key=item["key"]
                previous=self.store.fact(self.customer_id,key)
                origin={"context":{k:self.call[k] for k in ("run_id","config","scenario_id","call")},"field":"customer_text"}
                origin["context"]["turn"]=self.turn if source_turn is None else source_turn
                fact={"key":key,"value":item["value"],"customer_id":self.customer_id,"source":origin,
                      "valid_from":self.at,"valid_until":(date.fromisoformat(self.call["on"])+timedelta(days=180)).isoformat()+"T00:00:00+07:00" if key=="address" else None,
                      "state":"deleted" if item["op"]=="delete" else "active"}
                op="delete" if item["op"]=="delete" else "supersede" if previous else "set"
                self.store.write_fact(self.customer_id,key,fact,
                                      {"quote":item["quote"],"start":item["start"],"end":item["end"]})
                self.writes.append({"key":key,"value":item["value"],"customer_id":self.customer_id,"source":origin,"op":op})

    def run_turn(self, text):
        if self.closed or self.call is None or self.failed:raise RuntimeError("Call is not open")
        request=stamp()
        self.turn+=1
        try:
            model_text, pii_spans=mask_pii(text)
            if pii_spans and self.emit:
                self.emit({"kind":"pii_masked_before_model","span_count":len(pii_spans)})
            self.messages.append(HumanMessage(content=model_text))
            self.timeline.append({"role":"user","content":text,"turn":self.turn})
            facts=self.snapshot()["facts"]
            self.lane=self.route(model_text)
            self.tool_results=[]
            self.tool_event_index=0
            from .memory import MemoryAgent
            brief_lines=MemoryAgent.render_brief(facts,self.memory_reader.sessions(limit=3) if self.call["memory_read_previous"] else [])
            state={"messages":self.messages,"tier":self.tier,"lane":self.lane,"tool_results":self.tool_results,
                   "brief":{"lines":brief_lines},
                   "freshness":{"warnings":["Không dùng giá/KM cũ; tra tool hiện tại."]}}
            resources=self.context.get("resources",{})
            state["knowledge"]="\n\n".join(str(resources[k]) for k in ("prompt","kb") if resources.get(k))
            if self.candidate:
                state["knowledge"]+="\n\nFAQ đã được QA duyệt cho sandbox này; chỉ áp dụng trong đúng source scope:\n"+self.candidate["answer"]+"\nNguồn: "+self.candidate["source_path"]
                if self.emit:
                    self.emit({"kind":"candidate_consumed","resource":"knowledge_gap_candidate",
                               "candidate_id":self.candidate["candidate_id"],"candidate_hash":self.candidate["content_hash"],
                               "source_path":self.candidate["source_path"]})
            if self.emit:
                for name in ("prompt","kb"):
                    if isinstance(resources.get(name),str):
                        self.emit({"kind":"candidate_consumed","resource":name,"candidate_hash":hashlib.sha256(resources[name].encode()).hexdigest()})
            updates=self.advisor.process(state,**self.options)
            source_draft=updates["draft"]
            draft_reply=updates["draft"]["reply"]
            text_out=self.guard_reply(draft_reply)
            if self.policy is not None and text_out == draft_reply:
                try:
                    verdict=self.policy.process({"draft":text_out,"tool_results":self.tool_results,
                        "tier":self.tier,"policy_snippets":resources.get("kb",""),"now":self.call["on"]},**self.options)
                    if not verdict["passed"]:
                        writes=[event for event in self.store.business_events(self.customer_id,self.call["call"])
                                if event.get("source",{}).get("turn")==self.turn and event.get("tool") in ("order.create","schedule.callback","handoff.transfer","order.cancel_or_return")]
                        if not writes:
                            repair_draft=self.advisor.process({**state,"block_reasons":[item["reason"] for item in verdict["violations"]]},**self.options)["draft"]
                            repaired=repair_draft["reply"]
                            text_out=self.guard_reply(repaired)
                            if text_out==repaired:
                                source_draft=repair_draft
                                second=self.policy.process({"draft":repaired,"tool_results":self.tool_results,
                                    "tier":self.tier,"policy_snippets":resources.get("kb",""),"now":self.call["on"]},**self.options)
                                verdict=second
                                if not second["passed"]:
                                    text_out="Dạ, em chưa thể xác nhận nội dung này theo chính sách hiện tại. Em xin phép kiểm tra lại hoặc chuyển nhân viên phụ trách ạ."
                            if self.emit:self.emit({"kind":"policy_repair","attempts":1,"accepted":text_out==repaired})
                        else:
                            text_out="Dạ, em chưa thể xác nhận nội dung này theo chính sách hiện tại. Em xin phép kiểm tra lại hoặc chuyển nhân viên phụ trách ạ."
                    if self.emit:self.emit({"kind":"policy_review","passed":verdict["passed"],"violations":verdict["violations"]})
                except Exception as exc:
                    text_out="Dạ, em chưa thể xác nhận nội dung này. Em xin phép kiểm tra lại hoặc chuyển nhân viên phụ trách ạ."
                    if self.emit:self.emit({"kind":"policy_review","status":"UNDETERMINED","error_type":type(exc).__name__})
            used_lines=source_draft.get("used_brief_lines",[]) if text_out==source_draft["reply"] else []
            if not isinstance(used_lines,list) or any(not isinstance(line,str) or line not in {item["id"] for item in brief_lines} for line in used_lines):
                raise ValueError("Advisor cited an unavailable Call Brief line")
            self.messages.append(AIMessage(content=text_out))
            self.timeline.append({"role":"assistant","content":text_out,"turn":self.turn})
            completed=stamp()
            self.store.write_turn(self.customer_id, self.call["call"], self.turn, {"customer_text":model_text,"agent_text":text_out,"used_brief_lines":used_lines,
                                                                                "brief_sources":[item["source"] for item in brief_lines if item["id"] in used_lines],
                                                                                "request_at":request,"completed_at":completed})
            return {"agent_text":text_out,"mode":"nonstream","request_at":request,"first_token_at":completed,
                    "completed_at":completed,"memory_snapshot":self.snapshot(),"usage":None,
                    "usage_missing_reason":"Runtime caller must attach per-hook model usage; billing unknown"}
        except Exception:
            self.failed=True
            self.store.fail(self.customer_id, self.call["call"])
            raise

    def route(self, text):
        """Deterministic conservative router; identity gates precede intent."""
        return self.orchestrator.process({"tier":self.tier,"customer_text":text,"flags":{},
                                          "has_previous_session":bool(self.brief and self.brief["is_returning"])})["lane"]

    def guard_reply(self, reply):
        """Fail closed on sensitive identifiers and unsupported price claims."""
        from .pii import contains_pii
        if contains_pii(reply):
            return "Dạ, em xin phép không nhắc lại thông tin nhạy cảm trong tin nhắn. Em có thể hỗ trợ anh/chị kiểm tra bằng thông tin sản phẩm hoặc chuyển nhân viên phụ trách ạ."
        claims=re.findall(r"(?<!\d)(\d[\d.,]*)\s*(đồng|vnđ|vnd|₫|triệu|nghìn|ngàn|%)",reply.casefold())
        verified=set()
        def collect(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if ("price" in key or "discount" in key or "percent" in key or "promo" in key) and type(item) in (int,float):
                        verified.add(("%" if "percent" in key else "vnd",float(item)))
                    else:collect(item)
            elif isinstance(value,list):
                for item in value:collect(item)
        for event in getattr(self,"tool_results",[]):collect(event.get("result"))
        def grounded(number,unit):
            try:
                if unit=="%":
                    return ("%",float(number.replace(",","."))) in verified
                if unit in ("triệu","nghìn","ngàn"):
                    amount=round(float(number.replace(",","."))*(1000000 if unit=="triệu" else 1000))
                else:
                    amount=int(re.sub(r"\D","",number))
                return ("vnd",float(amount)) in verified
            except ValueError:return False
        if any(not grounded(number,unit) for number,unit in claims):
            return "Dạ, giá và khuyến mãi cần được kiểm tra theo thông tin hiện tại. Em xin phép tra lại hoặc chuyển anh/chị cho nhân viên phụ trách ạ."
        return reply

    def end_call(self):
        if self.call is None and self.last_end is not None:
            return copy.deepcopy(self.last_end)
        if self.call is None or self.failed:raise RuntimeError("Cannot complete failed/missing call")
        events=self.store.business_events(self.customer_id,self.call["call"])
        if any(event.get("outcome") in ("attempted","unknown") for event in events):
            raise RuntimeError("Tool outcome requires reconciliation; call cannot complete")
        with self.store.job_lock(self.customer_id,self.call["call"],"persist"):
            self._persist_call(events)
        snapshot=self.snapshot()
        finished_call=self.call["call"]
        self.last_call+=1
        self.last_date=self.call["on"]
        self.call=None
        self.last_end={"completed":True,"barrier_complete":True,"memory_snapshot":snapshot}
        if self.qa is not None and self.context.get("qa_criteria"):
            self.store.enqueue_job(self.customer_id,finished_call,"qa")
            self.store.set_job_status(self.customer_id,finished_call,"qa","RUNNING")
            qa_complete=True
            for criterion in self.context.get("qa_criteria",[]):
                try:
                    verdict=self.qa.process({"criterion":criterion,
                        "agent_utterances":[mask_pii(item["content"])[0] for item in self.timeline if item["role"]=="assistant"],
                        "verified_evidence":{"business_events":[{"tool":e.get("tool"),"outcome":e.get("outcome")} for e in events]}},**self.options)
                    self.store.save_qa_review(self.customer_id,finished_call,criterion["id"],{"status":"COMPLETE","verdict":verdict})
                    if self.emit:self.emit({"kind":"qa_verdict","verdict":verdict})
                except Exception as exc:
                    qa_complete=False
                    self.store.save_qa_review(self.customer_id,finished_call,criterion.get("id","UNKNOWN"),
                                              {"status":"UNDETERMINED","error_type":type(exc).__name__})
                    if self.emit:self.emit({"kind":"qa_verdict","criterion_id":criterion.get("id"),"status":"UNDETERMINED","error_type":type(exc).__name__})
            self.store.set_job_status(self.customer_id,finished_call,"qa","COMPLETED" if qa_complete else "FAILED")
        return copy.deepcopy(self.last_end)

    def _persist_call(self, events):
        self.store.enqueue_job(self.customer_id,self.call["call"],"persist")
        if not self.store.claim_job(self.customer_id,self.call["call"],"persist"):
            if not getattr(self,"recover_persist",False) or self.store.job_status(self.customer_id,self.call["call"],"persist")!="RUNNING":
                raise RuntimeError("After-call job requires reconciliation")
        try:
            drafts=[]
            if self.memory is None and not getattr(self,"reconciliation",None):
                raise RuntimeError("MemoryAgent is required for ordinary after-call persistence")
            for turn,payload in ([] if self.memory is None else self.store.turn_history(self.customer_id,self.call["call"])):
                customer_text=payload["customer_text"]
                draft=self.memory.process({"customer_text":customer_text},**self.options)
                rejected=[item for item in draft.get("facts",[]) if "█" in item.get("quote","") or "█" in str(item.get("value",""))]
                if rejected and self.emit:self.emit({"kind":"memory_pii_rejected","turn":turn,"count":len(rejected)})
                draft["facts"]=[item for item in draft.get("facts",[]) if item not in rejected]
                if draft.get("span_resolutions") and self.emit:
                    self.emit({"kind":"memory_span_resolution","strategy":"unique_quote_v1","resolutions":draft["span_resolutions"],"turn":turn})
                self.validate_facts(draft,customer_text)
                drafts.append((turn,customer_text,draft))
            with self.store.transaction():
                for turn,customer_text,draft in drafts:
                    self.commit_facts(draft,customer_text,source_turn=turn,in_transaction=True)
                changed=sorted({item["key"] for item in self.writes})
                facts=self.snapshot()["facts"]
                session=self._episode(events,changed,facts)
                self.store.finalize(self.customer_id,self.call["call"],session,in_transaction=True)
        except Exception:
            self.writes=[]
            self.store.set_job_status(self.customer_id,self.call["call"],"persist","FAILED")
            self.failed=True
            self.store.fail(self.customer_id,self.call["call"])
            raise

    def _episode(self, events, changed, facts):
        products=[]
        for event in events:
            if event.get("tool")=="catalog.search" and event.get("outcome")=="completed":
                products.extend({"sku":item.get("sku"),"name":item.get("name")} for item in event.get("result",{}).get("items",[]) if item.get("sku"))
        products=list({item["sku"]:item for item in products}.values())
        tools=sorted({event.get("tool") for event in events if event.get("outcome")=="completed"})
        fragments=[]
        if changed:fragments.append("đã cập nhật thông tin "+", ".join(changed))
        if products:fragments.append("đã tra cứu sản phẩm "+", ".join(item["sku"] for item in products))
        elif tools:fragments.append("đã tra cứu qua "+", ".join(tools))
        summary="Khách đã trao đổi; "+"; ".join(fragments)+"." if fragments else "Đã trao đổi; chưa ghi nhận thay đổi thông tin hoặc tra cứu tool hoàn tất."
        session={"session_id":self.call["call"],"date":self.call["on"],"channel":self.call.get("channel","phone"),
                 "summary":summary,"summary_source":{"run_id":self.call["run_id"],"config":self.call["config"],"scenario_id":self.call["scenario_id"],"call":self.call["call"],"turn_count":self.turn,"derived_fact_slots":changed},
                 "source_turn_span":[1,self.turn] if self.turn else None,
                 "business_event_refs":[{"call":event.get("source",{}).get("call"),"turn":event.get("source",{}).get("turn"),"event_index":event.get("source",{}).get("event_index"),"tool":event.get("tool")} for event in events],
                 "products_advised":products,"facts_at_end":[{"key":fact["key"],"value":fact["value"]} for fact in facts],
                 "outcome":"chot_don" if "order.create" in tools else "hen_goi_lai" if "schedule.callback" in tools else "chuyen_may" if "handoff.transfer" in tools else "khac"}
        if getattr(self,"reconciliation",None):
            session["outcome"]="interrupted"
            session["reconciliation"]=self.reconciliation
        return session

    def close(self):
        if not self.closed:
            self.store.close()
            self.closed=True
