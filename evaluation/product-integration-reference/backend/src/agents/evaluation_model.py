"""One explicit evaluator model invocation; raw text/usage returned without repair."""
import json
import sys
from langchain_core.messages import HumanMessage
from .evaluation_bridge import CallMeter, provider_error_details
from ..llm.factory import LLMFactory
from ..llm.callback_handler import text_of


def main():
    data=json.loads(sys.stdin.read())
    config=dict(data["config"])
    if config["provider"] not in ("google_genai","groq"):raise ValueError("Retry-controlled evaluator provider required")
    config.update(max_retries=0,tracing=False)
    llm=LLMFactory.create_llm(config,agent_name="harness-extractor")
    meter=CallMeter(1)
    answer=llm.invoke([HumanMessage(content=data["prompt"])],config={"callbacks":[meter]})
    raw=text_of(answer)
    diagnostic=None
    if not raw:
        content=answer.content
        diagnostic={"content_type":type(content).__name__,
                    "blocks":[{"type":item.get("type"),"keys":sorted(item),
                               "extras_keys":sorted((item.get("extras") or {}))}
                              for item in content if isinstance(item,dict)] if isinstance(content,list) else [],
                    "finish_reason":answer.response_metadata.get("finish_reason")}
    print(json.dumps({"raw":raw,"usage":meter.usage_since(0,meter.calls),"model_calls":meter.calls,
                      "empty_diagnostic":diagnostic},ensure_ascii=False,allow_nan=False))


if __name__=="__main__":
    try:main()
    except Exception as exc:
        print(json.dumps({"error_type":type(exc).__name__,"raw":None,
                          **provider_error_details(exc),"notice":"No repair/retry/fallback"}))
        sys.exit(2)
