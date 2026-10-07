# Kiến trúc BIM AI Agent — cách hệ thống đang chạy (as-is)

> Mô tả **code hiện có trên `main`** (cập nhật 2026-10-07, sau PR #10), không phải kiến trúc mục tiêu.
> Lộ trình và việc tiếp theo: `.agent/PROGRESS.md` (file cục bộ). Khi một PR đổi luồng nào dưới đây, cập nhật file này **trong cùng PR**.
> Ký hiệu: nét đứt `-.->` = chưa nối / dự kiến; ⚠️ = lỗi hoặc giới hạn đã biết (mục 7).

## 1. Tổng quan triển khai (`docker-compose.yml`)

```mermaid
flowchart LR
    U["Trình duyệt<br/>HTML + Vanilla JS + Three.js"]
    subgraph compose["docker compose — mạng bim-network"]
        FE["bim-frontend<br/>Nginx :3001→80<br/>file tĩnh + proxy /api/"]
        BE["bim-backend<br/>FastAPI :8001→8000"]
        PG[("bim-postgres<br/>users, conversations,<br/>messages, audit")]
        RD[("bim-redis<br/>bộ đếm rate limit")]
        QD[("bim-qdrant<br/>qcvn_chunks · ifc_elements<br/>384 chiều, cosine")]
        N4[("bim-neo4j<br/>đồ thị quy chuẩn + IFC")]
        VOL[["volume ifc_data<br/>/app/data/ifc"]]
    end
    GM["Google Gemini API<br/>(internet)"]

    U -->|HTTP| FE
    FE -->|/api/*| BE
    BE --> PG
    BE --> RD
    BE --> QD
    BE --> N4
    BE --> VOL
    BE -->|google-genai| GM
```

- Embedding chạy **trong backend** (FastEmbed `paraphrase-multilingual-MiniLM-L12-v2`, ghim `fastembed==0.4.1`), không gọi API ngoài.
- Router: `/api/v1/health`, `/api/v1/auth/*`, `/api/v1/chat` + `/conversations`, `/api/v1/documents`, `/api/v1/graph/*`, `/api/v1/ifc/*` (đăng ký trong `backend/src/main.py`).

## 2. Luồng chat — `POST /api/v1/chat` (SSE)

`AGENT_MODE` chọn bộ điều phối: **`multi_agent` (mặc định)** → `agents/coordinator.py`; `langgraph` → `rag/agent.py` (tên cũ, không dùng LangGraph); `simple` → `rag/graph_rag.py`.

```mermaid
sequenceDiagram
    autonumber
    participant FE as Frontend
    participant API as router_chat
    participant RL as rate_limit (Redis)
    participant PG as PostgreSQL
    participant CO as coordinator
    participant AG as Agent chuyên trách
    participant QD as Qdrant
    participant N4 as Neo4j
    participant GM as Gemini

    FE->>API: POST /chat (JWT)
    API->>RL: hit 20/phút và 300/ngày theo user
    RL-->>API: vượt hạn mức thì 429 + Retry-After
    API->>PG: tạo/lấy Conversation, lưu tin nhắn user, lấy 10 tin gần nhất
    API->>CO: ask(question, history)
    CO->>GM: classify_question → tools + entities (từ khóa thiết kế thì bỏ qua LLM)
    CO->>AG: AGENT_MAP: QCVNAgent / BIMAgent / DesignAgent
    AG->>QD: vector search (qcvn_chunks hoặc ifc_elements)
    AG->>N4: Cypher theo mẫu, hoặc LLM sinh Cypher (chặn từ khóa ghi)
    AG->>GM: DesignAgent: mô tả → spec JSON → sinh file IFC
    CO->>GM: _rerank tài liệu
    CO->>GM: generate_content_stream
    CO-->>API: stream + sources
    API-->>FE: SSE meta, rồi từng chunk
    API->>PG: lưu tin nhắn assistant + sources, ghi audit
    API->>GM: reflection.evaluate_response → confidence
    API-->>FE: SSE done (sources, confidence)
```

| Intent (classifier) | Agent | Truy hồi |
|---|---|---|
| `qcvn_search`, `graph_reasoning`, `material_check` | `QCVNAgent` | Qdrant `qcvn_chunks` + Neo4j |
| `ifc_query` | `BIMAgent` | Qdrant `ifc_elements` + `qcvn_chunks` |
| `design_building` | `DesignAgent` | `rag/tools/design_tool.py` → nhà hoặc cầu |
| `general_chat` | — | trả lời thẳng, không truy hồi |

## 3. Luồng IFC / BIM — `/api/v1/ifc/*`

```mermaid
flowchart TD
    subgraph up["POST /upload"]
        U1["kiểm tên file (path traversal),<br/>≤ IFC_MAX_UPLOAD_MB, 5 req/phút"] --> U2["lưu /app/data/ifc/*.ifc"]
        U2 --> U3["parse_ifc (IfcOpenShell)"]
        U3 --> U4["chunk theo cấu kiện → FastEmbed"]
        U4 --> U5[("Qdrant ifc_elements ⚠️")]
        U3 --> U6[("Neo4j: build_ifc_graph ⚠️")]
    end
    subgraph de["POST /design · POST /generate-sample"]
        D1["mô tả tiếng Việt"] --> D2{"_detect_structure_type"}
        D2 -->|nhà| D3["Gemini → spec → ifc_generator_v2<br/>(IFC4, IfcLocalPlacement)"]
        D2 -->|cầu| D4["Gemini → spec → ifc_bridge_generator<br/>+ kiểm tra bridge_compliance"]
        D3 --> D5["file .ifc trong /app/data/ifc"]
        D4 --> D5
    end
    subgraph view["Xem / tải"]
        V1["GET /geometry/{filename} ⚠️"] --> V2["Three.js viewer"]
        V3["GET /download/{filename}"]
        V4["GET /stats · GET /elements"]
    end
    D5 --> V1
    U2 --> V1
```

Hàm xuất móng sang JSON cho PLAXIS 3D có trong `ifc_bridge_generator.py` nhưng chưa có endpoint riêng.

## 4. Pipeline dữ liệu quy chuẩn (script chạy tay)

```mermaid
flowchart LR
    subgraph src["Nguồn công khai"]
        V["vbpl.vn<br/>Server Action"]
        CB["Công báo<br/>(kiểm tra sha256)"]
    end
    CR["scripts/crawl_vbpl_bxd.py"]
    subgraph store["backend/data/vbpl_bxd"]
        CAT["catalog.json<br/>(commit vào git)"]
        TXT["text/*.txt<br/>(không commit)"]
        FIL["files/**/*.pdf|docx|doc<br/>(không commit)"]
    end
    V --> CR
    CB --> CR
    CR --> CAT
    CR --> TXT
    CR --> FIL

    SG["sample_data_generator.py<br/>dữ liệu MẪU ~27 điều"] --> JS["data/qcvn/*.json"]
    PDF["data/pdf/*.pdf"] -.-> QP["qcvn_parser.py ⚠️"]
    QP -.-> JS
    TXT -.->|"chưa nối: cần parser mới"| QP
    FIL -.-> QP
    JS --> IN["scripts/ingest_qcvn.py<br/>chunker → FastEmbed"]
    IN --> QDC[("Qdrant qcvn_chunks")]
    JS --> BG["scripts/build_graph.py"]
    BG --> N4G[("Neo4j: Standard, Article,<br/>BuildingType, Material...")]
```

- **Hiện tại chatbot trả lời từ dữ liệu mẫu** (`data/qcvn/*.json`). Dữ liệu thật đã tải (51 QCVN, `catalog.json`) **chưa được nạp**. Việc tiếp theo là viết parser cho thư mục `data/vbpl_bxd`.
- `ingest_qcvn.py` và `build_graph.py` tự sinh dữ liệu mẫu nếu thư mục rỗng.

## 5. CI/CD — `.github/workflows/ci.yml` (mọi PR vào `main`, push `main`/`develop`)

```mermaid
flowchart LR
    PR["Pull request"] --> L["Lint<br/>ruff + compileall"]
    PR --> S["Secret Scan<br/>gitleaks, toàn lịch sử"]
    PR --> T["Unit Tests<br/>pytest, coverage ≥ 51%<br/>pip-audit chặn"]
    T --> D["Docker Build<br/>+ unit test trong image"]
    D --> I["Integration<br/>compose stack thật<br/>Neo4j · Qdrant · Redis · Postgres"]
    L --> M{"đủ 5/5 xanh<br/>trên head SHA"}
    S --> M
    I --> M
    M -->|có| MG["merge commit vào main"]
```

## 6. Bản đồ module `backend/src`

| Thư mục | Vai trò | File chính |
|---|---|---|
| `api/` | HTTP, xác thực, rate limit, SSE | `router_chat.py`, `router_ifc.py`, `router_auth.py`, `router_graph.py` |
| `agents/` | Bộ điều phối đa agent (mặc định) | `coordinator.py`, `qcvn_agent.py`, `bim_agent.py`, `design_agent.py` |
| `rag/` | Classifier + tools, GraphRAG đơn giản, rerank, reflection, kiểm tra tuân thủ | `agent.py`, `graph_rag.py`, `tools/*`, `reflection.py`, `compliance_checker.py`, `bridge_compliance.py` |
| `knowledge_graph/` | Neo4j: driver, schema, truy vấn mẫu, LLM sinh Cypher có kiểm tra | `neo4j_client.py`, `graph_builder.py`, `graph_query_generator.py`, `ifc_to_graph.py` |
| `embeddings/` | FastEmbed + Qdrant | `embedding_service.py`, `vector_store.py` |
| `data_pipeline/` | Parse QCVN/IFC, sinh IFC nhà/cầu, chunk | `qcvn_parser.py`, `ifc_parser.py`, `ifc_generator_v2.py`, `ifc_bridge_generator.py`, `chunker.py` |
| `core/` | Config, JWT/RBAC, lỗi, rate limit, audit, logging, client LLM | `config.py`, `security.py`, `rate_limit.py`, `errors.py`, `llm.py` |
| `database/` | SQLAlchemy models + session (bảng tạo bằng `create_all`, chưa dùng Alembic) | `models.py`, `session.py` |

Ngoài `src`: `backend/scripts/` (crawl, ingest, build_graph, set_role), `backend/tests/{unit,integration,smoke}`, `frontend/` (Nginx + `js/{app,api,auth,graph,ifc-upload}.js`).

## 7. Lỗi / giới hạn đã biết (⚠️ trong sơ đồ)

| Vị trí | Vấn đề |
|---|---|
| `vector_store.upsert_chunks` | Point id = số thứ tự (`id=i`) → upload IFC sau **ghi đè** vector của file trước; nạp lại để sót điểm rác |
| `ifc_to_graph.py` | `Storey.name` UNIQUE → "Tầng 1" của mọi tòa nhà gộp làm một node |
| `qcvn_parser.py` | Chỉ nhận "Chương/Điều", QCVN thật đánh số `x.y.z` → giữ ~1,5% nội dung; regex đơn vị `m` khớp cả `mm` |
| `router_ifc.py` | `GET /geometry/{filename}` khai báo **2 lần** — chỉ route đầu có hiệu lực |
| 3 bộ điều phối | `coordinator.py`, `rag/agent.py`, `rag/graph_rag.py` trùng chức năng; `SYSTEM_PROMPT` của agent không được dùng khi sinh câu trả lời |
| `/health` | Trả 200 cả khi một dịch vụ "degraded" |
