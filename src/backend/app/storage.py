from __future__ import annotations

import json
from pathlib import Path

from .schemas import AppState


ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CACHE_DIR = DATA_DIR / "cache"
INDEX_DIR = DATA_DIR / "indexes"
STATE_PATH = CACHE_DIR / "state.json"


def ensure_dirs() -> None:
    for directory in (DATA_DIR, UPLOAD_DIR, CACHE_DIR, INDEX_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def load_state() -> AppState:
    ensure_dirs()
    if not STATE_PATH.exists():
        return AppState()
    with STATE_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return AppState.model_validate(data)


def save_state(state: AppState) -> None:
    ensure_dirs()
    tmp_path = STATE_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state.model_dump(), handle, ensure_ascii=False, indent=2)
    tmp_path.replace(STATE_PATH)


def safe_filename(filename: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-（）()[]【】 " else "_" for ch in filename)
    return safe.strip() or "upload"

