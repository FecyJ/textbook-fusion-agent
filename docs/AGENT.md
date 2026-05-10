# Docs Agent Guide

## Scope

Applies to `docs/`.

## Required Documents

- `docs/需求分析.md`
- `docs/系统设计.md`
- `docs/Agent 架构说明.md`
- `docs/接口文档.md` if time allows

## Writing Rules

- Write in Chinese unless a quoted API/schema name is clearer in English.
- Keep claims tied to implemented behavior or planned implementation stages.
- For architecture diagrams, use Mermaid.
- Explain tradeoffs, not just what was built.
- Include RAG chunking rationale, duplicate decision criteria, compression ratio definition, and teaching-continuity safeguards.

## Agent Architecture Document Must Cover

- Number of agents/modules and responsibility boundaries.
- Why this architecture was chosen.
- Full data flow for upload, graph build, integration, RAG, and teacher feedback.
- Key interfaces and input/output shapes.
- Prompt engineering and hallucination controls.
- Known limitations and concrete future improvements.
- Innovation section if P1/P2 features are added.

## Known Pitfalls

- Do not describe unimplemented features as completed. Mark them as planned, partial, or implemented.
- The grading puts heavy weight on `docs/Agent 架构说明.md`; write this before polishing lower-priority docs.
- If using benchmark numbers, they must come from actual runs and should include conditions such as chunk size, embedding model, and dataset size.

