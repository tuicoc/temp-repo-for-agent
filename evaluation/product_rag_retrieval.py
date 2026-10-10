"""Run the product's actual kb_search with its own Python environment."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from src.mcp.servers.knowledge import kb_search  # noqa: E402


async def main():
    questions = json.load(sys.stdin)
    results = {}
    for item in questions:
        response = await kb_search(query=item["question"], k=5, on=item["on"])
        results[item["qid"]] = [hit["chunk_id"] for hit in response["hits"]]
    json.dump(results, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
