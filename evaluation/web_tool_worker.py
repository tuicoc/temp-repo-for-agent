"""JSON-line bridge to the pinned BTC mock worker for authenticated web demos."""
import json
import sys

from eval_harness.environment import MockEnvironment


def send(value):
    sys.stdout.write(json.dumps(value,ensure_ascii=False,allow_nan=False)+"\n")
    sys.stdout.flush()


def main():
    config=json.loads(sys.stdin.readline())
    worker=MockEnvironment(config["run_id"],config["scenario_id"],"full",timeout=12)
    send({"type":"ready"})
    try:
        for line in sys.stdin:
            message=json.loads(line)
            if message.get("type")=="close":
                break
            try:
                result=worker.call_tool(message["name"],message["args"],call=message["call"],
                                        turn=message["turn"],on=message["on"])
                send({"type":"result","result":result})
            except Exception as error:
                send({"type":"error","error_type":type(error).__name__})
                break
    finally:
        worker.close()


if __name__=="__main__":
    try:
        main()
    except Exception as error:
        send({"type":"startup_error","error_type":type(error).__name__})
