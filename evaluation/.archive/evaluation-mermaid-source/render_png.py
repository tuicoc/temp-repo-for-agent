"""Render this document's small Mermaid subset to offline PNGs.
Uses installed ELK (layout) and existing ReportLab styles; no browser/network.
PYTHONPATH=/private/tmp/qd-pdf-deps python3 .archive/evaluation-mermaid-source/render_png.py
"""
from pathlib import Path
import io, json, math, re, runpy, subprocess, html
import pymupdf
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors

ROOT = Path(__file__).resolve().parents[2]
BASE = runpy.run_path(str(ROOT / ".archive/evaluation-before-consolidation-2026-10-01/tools/build_evaluation_pdf.py"))
ELK = "/Users/vqd/.npm/_npx/668c188756b835f3/node_modules/elkjs/lib/elk.bundled.js"
NODE = ParagraphStyle("pngnode", parent=BASE["STYLES"]["node"], fontSize=12, leading=16)
LABEL = ParagraphStyle("pnglabel", parent=BASE["STYLES"]["label"], fontSize=10, leading=13)
JS = """const ELK=require(process.argv[1]); let s='';
process.stdin.on('data',x=>s+=x);
process.stdin.on('end',async()=>{try{
const g=await new ELK().layout(JSON.parse(s)); process.stdout.write(JSON.stringify(g));
}catch(e){console.error(e);process.exit(1)}});"""

def paragraph(text, style, width):
    p = Paragraph(text, style)
    _, height = p.wrap(width, 1000)
    return p, height

def parse(body):
    nodes = {}
    edges = []
    for line in body.splitlines():
        for n, shape, label in re.findall(r'(\w+)(\[|\{)"([^"]*)"[\]}]', line):
            nodes[n] = (label, shape == "{")
        line = re.sub(r'(\w+)(?:\[|\{)"[^"]*"[\]}]', r'\1', line).strip()
        m = re.fullmatch(r'(\w+)\s+(-->|-\.->)\s*(?:\|"([^"]*)"\|\s*)?(\w+)', line)
        if m:
            edges.append((m[1], m[4], m[3] or "", m[2] != "-->"))
    assert nodes and edges
    assert all(a in nodes and b in nodes for a,b,_,_ in edges)
    return nodes, edges

def render(body, index):
    nodes, edges = parse(body)
    children = []
    for ident, (label, decision) in nodes.items():
        _, ph = paragraph(label, NODE, 190)
        children.append(dict(id=ident, width=230, height=max(68, ph+36)))
    links = []
    for j, (a,b,label,dotted) in enumerate(edges):
        edge = dict(id=str(j), sources=[a], targets=[b])
        if label:
            width = max(38, min(150, BASE["pdfmetrics"].stringWidth(label, "Arial", 10)+12))
            _, ph = paragraph(html.escape(label), LABEL, width)
            edge["labels"] = [dict(text=label, width=width, height=ph+8)]
        links.append(edge)
    graph = dict(id="root", children=children, edges=links, layoutOptions={
        "elk.algorithm":"layered", "elk.direction":"LEFT" if index==1 else "DOWN",
        "elk.layered.cycleBreaking.strategy":"MODEL_ORDER",
        "elk.edgeRouting":"ORTHOGONAL", "elk.spacing.nodeNode":"52",
        "elk.layered.spacing.nodeNodeBetweenLayers":"82", "elk.spacing.edgeNode":"25",
        "elk.spacing.edgeEdge":"20", "elk.padding":"[top=25,left=25,bottom=25,right=25]",
        "elk.edgeLabels.placement":"CENTER"
    })
    result = subprocess.run(["node", "-e", JS, ELK], input=json.dumps(graph), text=True, capture_output=True, check=True)
    g = json.loads(result.stdout)
    width, height = g["width"]+40, g["height"]+70
    data=io.BytesIO()
    c=Canvas(data, pagesize=(width,height))
    c.setFillColor(colors.white); c.rect(0,0,width,height,fill=1,stroke=0)
    c.setFillColor(BASE["NAVY"]); c.setFont("ArialBold",13)
    c.drawString(24,height-24,f"EVALUATION • FLOW {index:02d}")
    ox, oy = 20, height-45
    def pt(p): return (ox+p["x"], oy-p["y"])
    for edge in g["edges"]:
        c.setStrokeColor(BASE["LINE"]); c.setLineWidth(1.3)
        c.setDash(5,3) if edges[int(edge["id"])][3] else c.setDash()
        for s in edge["sections"]:
            points=[pt(s["startPoint"])]+[pt(p) for p in s.get("bendPoints",[])]+[pt(s["endPoint"])]
            path=c.beginPath(); path.moveTo(*points[0])
            for p in points[1:]: path.lineTo(*p)
            c.drawPath(path)
            x,y=points[-1]; px,py=points[-2]; dist=math.hypot(x-px,y-py)
            ux,uy=(x-px)/dist,(y-py)/dist
            p=c.beginPath(); p.moveTo(x,y); p.lineTo(x-8*ux-3*uy,y-8*uy+3*ux); p.lineTo(x-8*ux+3*uy,y-8*uy-3*ux); p.close()
            c.setFillColor(BASE["LINE"]); c.drawPath(p,fill=1,stroke=0)
        c.setDash()
        for label in edge.get("labels",[]):
            x,y=ox+label["x"],oy-label["y"]-label["height"]
            c.setFillColor(colors.white);c.roundRect(x-2,y,label["width"]+4,label["height"],3,fill=1,stroke=0)
            p,ph=paragraph(html.escape(label["text"]),LABEL,label["width"]); p.drawOn(c,x,y+(label["height"]-ph)/2)
    for node in g["children"]:
        label,decision=nodes[node["id"]]
        x,y,w,h=ox+node["x"],oy-node["y"]-node["height"],node["width"],node["height"]
        c.setFillColor(BASE["AMBER"] if decision else BASE["TEAL"] if "active" in label.lower() or "pool" in label.lower() else BASE["BLUE"])
        c.setStrokeColor(BASE["LINE"]); c.setLineWidth(1)
        c.roundRect(x,y,w,h,12,fill=1,stroke=1)
        if decision:
            c.setFillColor(colors.HexColor("#b77913"));c.circle(x+10,y+h-10,3,fill=1,stroke=0)
        p,ph=paragraph(label,NODE,w-40);assert ph+30<=h
        p.drawOn(c,x+20,y+(h-ph)/2)
    c.showPage();c.save()
    doc=pymupdf.open(stream=data.getvalue(),filetype="pdf")
    out=ROOT/f"output/evaluation-assets/improved-v2-{index}.png"
    doc[0].get_pixmap(matrix=pymupdf.Matrix(2,2)).save(out)
    print(f"{index}: {int(width*2)}x{int(height*2)} nodes={len(nodes)} edges={len(edges)}")

if __name__=="__main__":
    source=(Path(__file__).with_name("evaluation-flow.md")).read_text()
    blocks=re.findall(r"```mermaid\n(.*?)\n```",source,re.S)
    assert len(blocks)==25, len(blocks)
    for i,body in enumerate(blocks,1): render(body,i)
