from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Status = Literal["pending", "parsing", "completed", "failed"]
DecisionAction = Literal["merge", "keep", "remove"]


class Chapter(BaseModel):
    chapter_id: str
    title: str
    page_start: int = 1
    page_end: int = 1
    content: str
    char_count: int


class Textbook(BaseModel):
    textbook_id: str
    filename: str
    title: str
    file_format: str
    size_bytes: int
    upload_path: str
    status: Status = "pending"
    error: str | None = None
    total_pages: int = 0
    total_chars: int = 0
    chapters: list[Chapter] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class KnowledgeNode(BaseModel):
    id: str
    name: str
    definition: str
    category: str = "核心概念"
    chapter: str
    page: int = 1
    textbook_id: str
    textbook_title: str
    source_text: str = ""
    frequency: int = 1
    quality_score: float = 1.0
    extraction_method: str = "heuristic"
    warnings: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: Literal["prerequisite", "parallel", "contains", "applies_to"]
    description: str = ""


class TextbookGraph(BaseModel):
    textbook_id: str
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    built_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class IntegrationDecision(BaseModel):
    decision_id: str
    action: DecisionAction
    affected_nodes: list[str]
    result_node: str | None = None
    reason: str
    confidence: float = 0.0
    status: Literal["active", "overridden"] = "active"


class IntegrationStats(BaseModel):
    original_chars: int = 0
    integrated_chars: int = 0
    compression_ratio: float = 0.0
    original_nodes: int = 0
    integrated_nodes: int = 0
    original_edges: int = 0
    integrated_edges: int = 0
    merge_count: int = 0
    keep_count: int = 0
    remove_count: int = 0


class IntegrationState(BaseModel):
    decisions: list[IntegrationDecision] = Field(default_factory=list)
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    stats: IntegrationStats = Field(default_factory=IntegrationStats)
    updated_at: str | None = None
    conversation: list[dict[str, str]] = Field(default_factory=list)


class RagChunk(BaseModel):
    chunk_id: str
    textbook_id: str
    textbook: str
    chapter: str
    page: int
    text: str
    char_count: int


class RagCitation(BaseModel):
    textbook: str
    chapter: str
    page: int
    relevance_score: float


class RagAnswer(BaseModel):
    answer: str
    citations: list[RagCitation]
    source_chunks: list[str]


class AppState(BaseModel):
    textbooks: dict[str, Textbook] = Field(default_factory=dict)
    graphs: dict[str, TextbookGraph] = Field(default_factory=dict)
    integration: IntegrationState = Field(default_factory=IntegrationState)
    rag_chunks: list[RagChunk] = Field(default_factory=list)
    rag_indexed_at: str | None = None
