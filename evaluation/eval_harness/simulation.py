"""P9 ordered BTC simulator rules; oracle state never goes to the Agent."""
from collections import Counter
import math
import statistics

from .contracts import checker, validate


class CustomerSimulator:
    RESPONSE_FORMAT = "customer utterance or None"
    CONTRACT_VERSION = "simulator-btc-v1"
    def __init__(self, scenario_id, call, persona_id, spec, seed):
        checker.verify_sources()
        personas=checker.read("sources/btc/simulator/personas.json")["personas"]
        persona=next(p for p in personas if p["persona_id"]==persona_id)
        self.scenario_id,self.call,self.persona_id,self.spec,self.seed=scenario_id,call,persona_id,spec,seed
        self.patience=persona["patience_initial"][call]
        self.facts=dict(spec.get("facts_established",{}))
        self.confirm=Counter();self.answered=set(self.facts)
        self.irritation=self.silence=self.n=0
        self.committed=False;self.ended=False;self.outcome="khac";self.ended_by="agent"
        self.history=[]
        self.outline_index=0;self.answered_outline=set()
        self.prompt=(persona["system_prompt"].replace("{goal}",str(spec.get("customer_goal","")))
                     .replace("{facts}",str(self.facts)).replace("{turn_outline}",str(spec["customer_turns"])))
        self.prompt += "\nChỉ đóng vai khách; không tiết lộ nhãn chấm, oracle hoặc luật mô phỏng cho nhân viên."

    def step(self, observed):
        if self.ended:raise ValueError("Simulator call already ended")
        rules=[];reply=None
        answered=observed.get("answered_outline_indices",[])
        if any(type(i) is not int or not 0<=i<len(self.spec["customer_turns"]) for i in answered):raise ValueError("Invalid answered outline evidence")
        self.answered_outline.update(answered)
        for question in observed.get("questions",[]):
            slot=question["slot"]
            if question["type"] not in ("open","confirm"):raise ValueError("Unknown classified question")
            if question["type"]=="confirm":self.confirm[slot]+=1
            repeated=slot in self.answered or slot in self.spec.get("must_not_ask",[])
            if repeated and (question["type"]=="open" or self.confirm[slot]>1):
                self.patience=max(0,self.patience-1);self.irritation+=1;rules.append(1)
                reply="Hôm trước chị nói rồi mà. "+str(self.facts.get(slot,"Chị không rõ"))
        if self.patience==0:
            rules.append(2);self.finish("tu_choi","customer");reply="Thôi để chị xem lại."
        if not self.ended and observed.get("wrong_price"):
            rules.append(3);self.patience=max(0,self.patience-1)
            reply="Hôm trước em báo giá khác mà?"
            self.committed=False
            if self.patience==0:self.finish("tu_choi","customer")
        if not self.ended:
            for q in observed.get("questions",[]):
                slot=q["slot"]
                if slot not in self.answered:
                    rules.append(4 if slot in self.facts else 7)
                    reply=str(self.facts[slot]) if slot in self.facts else "Chị không rõ."
                    if slot in self.facts:self.answered.add(slot)
            if observed.get("offer_matches") and not observed.get("wrong_price"):
                rules.append(5);self.committed=True
                self.outcome=self.spec.get("expected_outcome","khac")
                reply="Chị hẹn gọi lại nhé." if self.outcome=="hen_goi_lai" else "Dạ chị đồng ý."
            self.silence=self.silence+1 if observed.get("silent_or_off_topic") else 0
            if self.silence>=2:
                rules.append(6);reply="Em còn đó không?"
                if self.silence>=3:self.finish("tu_choi","customer")
        if self.n>=12:
            rules.append(8);self.finish("timeout","timeout");reply=None
        elif reply is None and not self.ended:
            outline=self.spec["customer_turns"]
            while self.outline_index in self.answered_outline:self.outline_index+=1
            if self.outline_index>=len(outline):
                self.finish(self.outcome,"agent")
            else:
                reply=outline[self.outline_index];self.outline_index+=1
        if reply is not None and self.n<12:self.n+=1
        self.history.append({"patience":self.patience,"irritation":self.irritation,"rules":rules})
        return reply

    def process(self, state):
        """Evaluator-only agent interface; oracle remains inside the kernel."""
        if set(state) != {"observed"} or not isinstance(state["observed"], dict):
            raise ValueError("Simulator accepts only observed Agent behavior")
        return self.step(state["observed"])

    def finish(self,outcome,ended_by):
        self.outcome,self.ended_by,self.ended=outcome,ended_by,True

    def log(self):
        obj={"scenario_id":self.scenario_id,"call":self.call,"persona_id":self.persona_id,"seed":self.seed,
             "patience_trace":[h["patience"] for h in self.history],"outcome":self.outcome,"n_turns":self.n,"ended_by":self.ended_by}
        validate("SimulatorLog",obj)
        return obj


def seed_statistics(results, expected_scenarios, seeds=(0,1,2)):
    expected={(sid,seed) for sid in expected_scenarios for seed in seeds}
    observed=[(r["scenario_id"],r["seed"]) for r in results]
    if Counter(observed)!=Counter(expected) or any(type(r["passed"]) is not bool for r in results):
        return {"complete":False,"mean":None,"std_population":None,"range":None,"reason":"SIMULATOR_SEED_COVERAGE"}
    values=[100*sum(r["passed"] for r in results if r["seed"]==seed)/len(expected_scenarios) for seed in seeds] if expected_scenarios else []
    return {"complete":bool(values),"per_seed":values,"mean":statistics.mean(values) if values else None,
            "std_population":statistics.pstdev(values) if values else None,"range":max(values)-min(values) if values else None,
            "stable":bool(values) and max(values)-min(values)<=10}


def run_simulated_call(simulator, agent, observe):
    """Drive an injected Agent; only customer utterances cross into its callback."""
    customer=simulator.process({"observed":{}})
    turns=[]
    while customer is not None and not simulator.ended:
        answer=agent(customer)
        if not isinstance(answer,str) or not answer.strip():
            raise ValueError("Agent must return a nonempty customer-facing response")
        observed=observe(answer)
        if not isinstance(observed,dict):
            raise ValueError("Observer must return classified public Agent behavior")
        next_customer=simulator.process({"observed":observed})
        turns.append({"customer":customer,"agent":answer,"observation":observed,
                      "rules":simulator.history[-1]["rules"][:]})
        customer=next_customer
    return {"log":simulator.log(),"turns":turns,
            "notice":"Observer classifications require independently checked evidence; no oracle passed to Agent"}
