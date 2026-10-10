"""Pinned BTC RAG chunk catalog; no answer generation or external model."""
import re

from .assets import Assets, read_json
from .contracts import ROOT, checker

_SECTION = re.compile(r"^## \[([A-Z0-9-]+)\]", re.MULTILINE)
_PRIVATE = {"ghi-chu-nhap-hang-NOI-BO.md": "restricted",
            "noi-quy-nhan-vien.md": "internal",
            "playbook-telesale.md": "internal",
            "chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md": "historical"}


def chunk_catalog():
    checker.verify_sources()
    assets=Assets(ROOT)
    chunks={}
    for path in sorted((ROOT/"sources/btc/policy").glob("*.md")):
        ref=assets.ref(str(path.relative_to(ROOT)))
        body=assets.resolve(ref,json_content=False).read_text(encoding="utf-8")
        matches=list(_SECTION.finditer(body))
        for index,match in enumerate(matches):
            chunk_id=match.group(1)
            if chunk_id in chunks:raise ValueError("Duplicate BTC chunk ID: "+chunk_id)
            chunks[chunk_id]={"chunk_id":chunk_id,"text":body[match.start():matches[index+1].start() if index+1<len(matches) else len(body)].strip(),
                              "source_ref":ref,"access":_PRIVATE.get(path.name,"public"),
                              "version":path.name}
    if len(chunks)!=99:raise ValueError("BTC RAG corpus requires 99 pinned chunks")
    qa=read_json(ROOT/"sources/btc/rag/qa_labeled.json")["questions"]
    if len(qa)!=60 or len({q["qid"] for q in qa})!=60:raise ValueError("BTC RAG requires 60 unique qids")
    missing={chunk_id for q in qa for chunk_id in q["relevant_chunk_ids"] if chunk_id not in chunks}
    if missing:raise ValueError("RAG gold references unknown chunks: "+str(sorted(missing)))
    return chunks


def customer_chunks(catalog):
    """Only public text may be passed to a customer-facing retriever/model."""
    return {key:value for key,value in catalog.items() if value["access"]=="public"}


def postgres_search(cursor, catalog, question, *, limit=5, audience="customer"):
    """Local PostgreSQL full-text retrieval; returns IDs/scores, never chunk text."""
    if audience not in ("customer","staff") or type(limit) is not int or not 1<=limit<=10:
        raise ValueError("Explicit audience and bounded top-k required")
    tokens=list(dict.fromkeys(re.findall(r"\w+",question.casefold(),re.UNICODE)))
    if not tokens or len(tokens)>100:raise ValueError("Nonempty bounded question required")
    visible=customer_chunks(catalog) if audience=="customer" else catalog
    rows=sorted(visible.items())
    if not rows:return []
    values=",".join(["(%s,%s)"]*len(rows))
    sql=("WITH docs(chunk_id,body) AS (VALUES "+values+") "
         "SELECT chunk_id, ts_rank_cd(to_tsvector('simple',body),to_tsquery('simple',%s)) AS rank "
         "FROM docs WHERE to_tsvector('simple',body) @@ to_tsquery('simple',%s) "
         "ORDER BY rank DESC, chunk_id LIMIT %s")
    query=" | ".join(tokens)
    params=[part for key,value in rows for part in (key,value["text"])]+[query,query,limit]
    cursor.execute(sql,params)
    return [{"chunk_id":row[0],"score":float(row[1]),"source_ref":visible[row[0]]["source_ref"],
             "version":visible[row[0]]["version"],"access":visible[row[0]]["access"]}
            for row in cursor.fetchall()]
