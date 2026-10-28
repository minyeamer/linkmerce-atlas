import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from . import ai, auth
from .graph import Graph
from .indexer import Indexer

root = Path(os.getenv("LINKMERCE_ROOT", "/source/linkmerce"))
graph = None
index_lock = asyncio.Lock()


def build():
    snapshot = Indexer(root).build()
    result = Graph(snapshot)
    path = auth.DATA / "snapshot.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False))
    temporary.replace(path)
    return result


@asynccontextmanager
async def lifespan(app):
    global graph
    graph = await asyncio.to_thread(build)
    yield


app = FastAPI(title="Linkmerce Atlas", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=auth.SESSION_SECRET, same_site="lax", https_only=auth.PUBLIC_URL.startswith("https://"), max_age=43200)


@app.middleware("http")
async def browser_boundary(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        expected = auth.PUBLIC_URL
        if origin and origin.rstrip("/") != expected:
            return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth.router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
def home():
    return FileResponse(Path(__file__).parent / "static/index.html")


@app.get("/api/health")
def health():
    return {"ok": graph is not None, "engine": "wirelog", "wirelog_revision": os.getenv("WIRELOG_REV", "local")}


@app.get("/api/stats")
def stats():
    return {**graph.data["meta"], "nodes": len(graph.nodes), "edges": len(graph.edges),
            "derived_paths": len(graph.engine.pairs), "layers": dict(Counter(n["layer"] for n in graph.nodes.values())),
            "kinds": dict(Counter(n["kind"] for n in graph.nodes.values())), "warnings": graph.data["warnings"],
            "engine": "Wirelog C11", "wirelog_revision": os.getenv("WIRELOG_REV", "local"),
            "admin_required": bool(os.getenv("ADMIN_TOKEN"))}


@app.get("/api/search")
def search(q: str = "", kind: str | None = None, limit: int = 40):
    return graph.search(q[:300], max(1, min(limit, 100)), kind)


@app.get("/api/node")
def node(id: str):
    if id not in graph.nodes:
        raise HTTPException(404, "Node not found")
    return graph.neighborhood(id)


@app.get("/api/path")
def path(source: str, target: str):
    if source not in graph.nodes or target not in graph.nodes:
        raise HTTPException(404, "Node not found")
    result = graph.path(source, target)
    return {"reachable": bool(result), "edges": result, "evidence": [graph.data["evidence"][e["evidence"]] for e in result]}


@app.get("/api/evidence/{id}")
def evidence(id: str):
    if id not in graph.data["evidence"]:
        raise HTTPException(404, "Evidence not found")
    return graph.data["evidence"][id]


@app.post("/api/reindex")
async def reindex(request: Request):
    global graph
    expected = os.getenv("ADMIN_TOKEN", "")
    if expected and not secrets.compare_digest(request.headers.get("x-admin-token", ""), expected):
        raise HTTPException(403, "Admin token required")
    if index_lock.locked():
        raise HTTPException(409, "Index build already in progress")
    async with index_lock:
        result = await asyncio.to_thread(build)
        graph = result
    return {"ok": True, "nodes": len(graph.nodes), "fingerprint": graph.data["meta"]["fingerprint"]}


@app.get("/api/models")
async def models(request: Request):
    key, provider = await auth.credential(request)
    return await ai.models(key, provider)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1800)
    focus: str | None = None
    mode: str = "evidence"
    model: str = Field(default=os.getenv("OPENAI_MODEL", "gpt-6-luna"), max_length=150)


@app.post("/api/ask")
async def ask(body: Question, request: Request):
    current = graph
    context = current.context(body.question, body.focus)
    if body.mode == "ai":
        key, provider = await auth.credential(request)
        effort = "low" if body.model in {"gpt-6-luna", "gpt-6.1-sol", "gpt-6.1-terra"} else None
        result = await ai.answer(context, key, body.model,
                                 max_output_tokens=4096 if provider == "openai" else None,
                                 reasoning_effort=effort)
    elif body.mode == "evidence":
        provider = "evidence"
        result = current.evidence_answer(context)
    else:
        raise HTTPException(400, "Unknown answer mode")
    citations = set(re.findall(r"\[(E[0-9a-f]{12})\]", result))
    known = {e["id"] for e in context["evidence"]}
    audit = []
    if citations - known:
        audit.append("AI가 제공된 근거에 없는 출처를 인용했습니다. 답변을 확인하세요.")
    if provider != "evidence" and not citations & known:
        audit.append("AI 답변에 확인 가능한 출처 인용이 없습니다.")
    return {"answer": result, "provider": provider, "evidence": context["evidence"],
            "entities": context["entities"], "relations": context["relations"], "audit": audit,
            "fingerprint": current.data["meta"]["fingerprint"], "scope": context["scope"]}
