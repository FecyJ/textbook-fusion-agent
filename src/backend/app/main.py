from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .graph_builder import build_graph_for_textbook
from .integration import apply_teacher_feedback, run_integration
from .parser import new_textbook, parse_textbook
from .rag import build_rag_index, query_rag
from .reporting import write_integration_report
from .storage import UPLOAD_DIR, ensure_dirs, load_state, safe_filename, save_state

app = FastAPI(
    title="Textbook Fusion Agent API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "name": "Textbook Fusion Agent API",
        "status": "ok",
        "frontend": "http://localhost:5173",
        "health": "/api/health",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "llm": {
            "provider": "deepseek",
            "model": settings.deepseek_model,
            "base_url": settings.deepseek_api_base_url,
            "api_key_configured": bool(settings.deepseek_api_key),
        },
    }


@app.get("/api/textbooks")
def list_textbooks() -> dict[str, object]:
    state = load_state()
    return {"textbooks": [summary_textbook(textbook) for textbook in state.textbooks.values()]}


@app.get("/api/textbooks/{textbook_id}")
def get_textbook(textbook_id: str) -> dict[str, object]:
    state = load_state()
    textbook = state.textbooks.get(textbook_id)
    if not textbook:
        raise HTTPException(status_code=404, detail="Textbook not found")
    return textbook.model_dump()


@app.post("/api/textbooks/upload")
async def upload_textbooks(files: list[UploadFile] = File(...)) -> dict[str, object]:
    ensure_dirs()
    state = load_state()
    results = []
    for upload in files:
        filename = upload.filename or "upload"
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".md", ".markdown", ".txt", ".docx"}:
            results.append({"filename": filename, "status": "failed", "error": f"Unsupported file type: {suffix}"})
            continue
        target = UPLOAD_DIR / f"{Path(safe_filename(filename)).stem}_{len(state.textbooks) + 1}{suffix}"
        size = 0
        with target.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                handle.write(chunk)
        textbook = new_textbook(filename=filename, file_format=suffix.lstrip("."), size_bytes=size, upload_path=str(target))
        textbook.status = "parsing"
        state.textbooks[textbook.textbook_id] = textbook
        save_state(state)
        try:
            textbook = parse_textbook(textbook)
        except Exception as exc:
            textbook.status = "failed"
            textbook.error = str(exc)
        state.textbooks[textbook.textbook_id] = textbook
        save_state(state)
        results.append(summary_textbook(textbook))
    return {"textbooks": results}


@app.post("/api/graphs/build")
async def build_graph(payload: dict[str, object] = Body(default_factory=dict)) -> dict[str, object]:
    state = load_state()
    textbook_ids = payload.get("textbook_ids") or list(state.textbooks.keys())
    use_llm = bool(payload.get("use_llm", True))
    built = []
    for textbook_id in textbook_ids:
        textbook = state.textbooks.get(str(textbook_id))
        if not textbook:
            continue
        if textbook.status != "completed":
            continue
        graph = await build_graph_for_textbook(textbook, use_llm=use_llm)
        state.graphs[textbook.textbook_id] = graph
        built.append({"textbook_id": textbook.textbook_id, "nodes": len(graph.nodes), "edges": len(graph.edges)})
    save_state(state)
    return {"built": built, "graphs": [graph.model_dump() for graph in state.graphs.values()]}


@app.get("/api/graphs/{textbook_id}")
def get_graph(textbook_id: str) -> dict[str, object]:
    state = load_state()
    if textbook_id == "integrated":
        return {"nodes": [node.model_dump() for node in state.integration.nodes], "edges": [edge.model_dump() for edge in state.integration.edges]}
    graph = state.graphs.get(textbook_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    return graph.model_dump()


@app.post("/api/integration/run")
def integrate_graphs() -> dict[str, object]:
    state = load_state()
    integration = run_integration(state)
    save_state(state)
    return integration.model_dump()


@app.get("/api/integration/decisions")
def get_integration() -> dict[str, object]:
    return load_state().integration.model_dump()


@app.post("/api/integration/feedback")
def teacher_feedback(payload: dict[str, str] = Body(...)) -> dict[str, object]:
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    state = load_state()
    integration = apply_teacher_feedback(state, message)
    save_state(state)
    return integration.model_dump()


@app.post("/api/rag/index")
def index_rag() -> dict[str, object]:
    state = load_state()
    chunks = build_rag_index(state)
    save_state(state)
    return {"textbook_count": len(state.textbooks), "chunk_count": len(chunks), "indexed_at": state.rag_indexed_at}


@app.get("/api/rag/status")
def rag_status() -> dict[str, object]:
    state = load_state()
    return {"textbook_count": len(state.textbooks), "chunk_count": len(state.rag_chunks), "indexed_at": state.rag_indexed_at}


@app.post("/api/rag/query")
async def rag_query(payload: dict[str, str] = Body(...)) -> dict[str, object]:
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    state = load_state()
    answer = await query_rag(state, question)
    save_state(state)
    return answer.model_dump()


@app.get("/api/report/integration")
def integration_report() -> dict[str, object]:
    state = load_state()
    content = write_integration_report(state)
    save_state(state)
    return {"path": "report/整合报告.md", "content": content, "stats": state.integration.stats.model_dump()}


def summary_textbook(textbook) -> dict[str, object]:
    return {
        "textbook_id": textbook.textbook_id,
        "filename": textbook.filename,
        "title": textbook.title,
        "file_format": textbook.file_format,
        "size_bytes": textbook.size_bytes,
        "status": textbook.status,
        "error": textbook.error,
        "total_pages": textbook.total_pages,
        "total_chars": textbook.total_chars,
        "chapter_count": len(textbook.chapters),
        "created_at": textbook.created_at,
        "updated_at": textbook.updated_at,
    }
