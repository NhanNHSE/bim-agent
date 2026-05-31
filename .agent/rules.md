# BIM AI Agent — Project Rules

## Kiến trúc

```
backend/src/
├── api/           → HTTP layer (routing, auth, SSE)
├── core/          → Config, LLM, security, logging
├── database/      → Models, migrations
├── data_pipeline/ → IFC generators, parsers, specs
├── embeddings/    → Vector search
├── knowledge_graph/ → Neo4j
└── rag/           → Agent, tools, compliance

frontend/
├── index.html     → SPA (vanilla HTML/CSS/JS)
├── js/            → Modules (app, api, ifc-upload, ...)
└── css/           → Dark theme
```

**Nguyên tắc:**
- Flow phụ thuộc 1 chiều: `api → rag → data_pipeline → core`. Không circular import.
- Frontend là vanilla JS, 3D dùng Three.js. Không framework.
- Mọi structure type (nhà, cầu, ...) kế thừa `BaseSpec`. Thêm loại mới = thêm spec + generator + compliance + update frontend adaptive.

## Code conventions

- Python 3.11+, type hints, docstrings cho public functions
- Logging: `structlog` (không `print`)
- Config: qua env vars / `.env`, không hardcode secrets
- Error: API layer raise `HTTPException`, tool layer return dict
- LLM: retry + fallback model
- Frontend: detect `spec.structure_type` để render adaptive UI
- Đơn vị kích thước trong Spec: millimeters (mm)
- IFC schema: IFC4

## Tiêu chuẩn xây dựng

- Building: QCVN 06:2022
- Bridge: TCVN 11823:2017 (LRFD), tải trọng HL-93
- Mỗi structure type có compliance checker riêng, violations gồm: `rule`, `issue`, `suggestion`, `severity`

## Security

- JWT auth (HS256), secret ≥ 32 chars
- Parameterized queries cho Neo4j
- Không log passwords/tokens/API keys
- Không commit `.env`
