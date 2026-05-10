# Project Agent Guide

## Scope

This file applies to the whole repository. More specific `AGENT.md` files under component folders override these instructions for their subtree.

## Project Goal

Build a web application for the AI full-stack hackathon task: load multiple textbooks, parse chapters, extract knowledge points, visualize knowledge graphs, merge duplicate knowledge across textbooks, provide cited RAG answers, support teacher feedback, and generate required documentation/reports.

## Repository Layout

- `src/backend/`: FastAPI backend, parsing, graph, integration, RAG, LLM orchestration, API routes.
- `src/frontend/`: React/Vite frontend, upload UI, graph visualization, RAG/chat/report panels.
- `docs/`: required design and architecture documents.
- `report/`: generated integration report for the seven provided textbooks.
- `textbooks/`: local textbook PDFs only. Never commit this directory or any PDF.
- `.env`: local secrets. Never print, paste, or commit it.

## Commands

- Install all dependencies:
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && npm install && npm --prefix src/frontend install`
- Start dev servers:
  `npm run dev`
- Backend:
  `http://localhost:8000`
- Frontend:
  `http://localhost:5173`
- Backend health check:
  `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost curl -sS http://127.0.0.1:8000/api/health`
- Frontend build:
  `npm --prefix src/frontend run build`

## Git And Secrets

- The repository is initialized on branch `main`.
- Make necessary Git commits to preserve work after each coherent milestone, especially before risky refactors, dependency changes, deployment work, or long-running generation. Do not leave substantial completed work only in the working tree.
- `.env`, `.venv/`, `node_modules/`, logs, build outputs, textbook PDFs, and generated caches must stay ignored.
- Before staging, check:
  `git status --short --ignored`
- Do not use commands that would print `.env` values. It is acceptable to list variable names only.

## Known Local Environment Pitfalls

- The command sandbox can expose `.git` as a read-only tmpfs. Real Git operations may require running the same Git command with escalation.
- Network installs are blocked in the default sandbox. If `pip` or `npm` fails with proxy/EPERM errors, rerun the same install command with escalation instead of changing package sources.
- Localhost HTTP checks can go through the proxy and return `502` or fail. Set both `NO_PROXY=127.0.0.1,localhost` and `no_proxy=127.0.0.1,localhost` for `curl` or Python HTTP checks.
- Port checks with `ss` can need escalation because netlink access is restricted.
- If a temporary Uvicorn process is started for verification, clean it up and check ports before restarting dev servers.
- Do not rely on FastAPI `TestClient` in this environment: the anyio blocking portal can hang on exit. Prefer running Uvicorn and checking the HTTP endpoint.

## Implementation Priorities

- Keep P0 complete before P1/P2 work.
- Prefer deterministic local fallbacks for hackathon speed: parse and cache local files, avoid repeated LLM calls where cached structured results are enough.
- Every answer or report statistic must trace back to stored textbook/chapter/page metadata.
- Keep generated data out of Git unless it is a required Markdown deliverable under `docs/` or `report/`.
