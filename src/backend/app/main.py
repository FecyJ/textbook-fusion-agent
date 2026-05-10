from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings

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

