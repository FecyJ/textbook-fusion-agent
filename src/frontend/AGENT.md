# Frontend Agent Guide

## Scope

Applies to `src/frontend/`.

## Stack

- React 19
- TypeScript
- Vite
- ECharts for knowledge graph visualization
- lucide-react for icons

## Responsibilities

- Single-page app with textbook management, graph canvas, and right-side functional panels.
- Upload UX: drag-and-drop, file list, parse status, errors.
- Knowledge graph interaction: zoom, pan, drag nodes, click detail panel, search/highlight, textbook color and frequency size/depth.
- Integration panel: merge/keep/remove decisions, reasons, confidence, compression ratio, before/after comparison.
- RAG panel: question input, answer body, citation list, relevance score, expandable source chunks.
- Teacher chat panel: persistent session context and decision updates.

## UI Rules

- Keep the main graph area visually dominant.
- Use dense operational UI rather than a landing page.
- Avoid nested cards and decorative gradients/orbs.
- Use icons for common commands when available.
- Make labels fit at 1920x1080 and avoid overlapping controls.

## API Rules

- Use Vite proxy for `/api` to backend `http://localhost:8000`.
- Keep API response types explicit in TypeScript.
- Handle loading, empty, and error states for every backend operation.

## Commands

- Install frontend dependencies:
  `npm --prefix src/frontend install`
- Dev server:
  `npm --prefix src/frontend run dev -- --host 0.0.0.0`
- Build:
  `npm --prefix src/frontend run build`

## Known Pitfalls

- Network install can fail with `EPERM` through the local proxy in the default sandbox. Rerun the same `npm --prefix src/frontend install` command with escalation.
- `src/frontend/dist/` and `*.tsbuildinfo` are generated build artifacts and must stay ignored.
- The root `npm run dev` already starts both backend and frontend via `concurrently`; avoid starting an extra Vite server on the same port unless you first check `5173`.
- Local page checks should bypass proxy for localhost:
  `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost curl -I http://127.0.0.1:5173/`

