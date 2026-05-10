# Report Agent Guide

## Scope

Applies to `report/`.

## Required Output

- `report/整合报告.md`

## Report Content

The report must match actual system output for the seven provided textbooks:

- Original textbook count and total characters.
- Integrated character count and compression ratio.
- Decision summary: merge, keep, remove counts.
- Graph statistics before and after integration.
- Three to five representative integration decisions with reasons.
- Teaching-completeness analysis and any remaining knowledge gaps.

## Data Rules

- Do not invent numbers. Generate or recompute statistics from backend outputs.
- Keep source references traceable to textbook, chapter, and page metadata.
- The report is committed; raw textbooks and generated indexes are not.

## Known Pitfalls

- The local `textbooks/` PDFs are ignored and must not be copied into `report/`.
- If the system is run multiple times, regenerate the report from the latest integration result so compression ratio and decision counts stay consistent.
- Do not include `.env` values, model tokens, or hidden local paths beyond normal project-relative paths.

