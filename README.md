# 🏗️ BIM AI Agent — Trợ lý Quy chuẩn Xây dựng

AI Agent tra cứu QCVN/TCVN xây dựng Việt Nam, sử dụng **GraphRAG** (Knowledge Graph + Vector Search) kết hợp **Gemini AI**, tích hợp động cơ sinh mô hình thiết kế tự động (**IFC4 BIM Generator**).

[![CI](https://github.com/your-org/bim-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/bim-agent/actions)

## Kiến trúc hệ thống

```
┌──────────────────────────────────────────────────────────────────┐
│                        Ubuntu Server (WSL)                       │
│  ┌──────────┐   ┌──────────────────┐   ┌────────────────────┐   │
│  │ Frontend  │──▶│  Backend (FastAPI)│──▶│  GraphRAG Pipeline │   │
│  │  (Nginx)  │   │  Port 8000       │   │                    │   │
│  │  Port 80  │   │                  │   │  ┌──────────────┐  │   │
│  └──────────┘   │  • Agent Router   │   │  │ Qdrant       │  │   │
│                  │  • Tool Registry  │   │  │ (Vector DB)  │  │   │
│                  │  • Reflection     │   │  ├──────────────┤  │   │
│                  │  • IFC Generator  │   │  │ Neo4j        │  │   │
│                  └──────────────────┘   │  │ (Graph DB)   │  │   │
│                                         │  ├──────────────┤  │   │
│  ┌──────────┐   ┌──────────────────┐   │  │ Gemini API   │  │   │
│  │ Postgres │   │     Redis        │   │  │ (LLM)        │  │   │
│  │ (Users)  │   │     (Cache)      │   │  └──────────────┘  │   │
│  └──────────┘   └──────────────────┘   └────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## Tính năng nổi bật

| Chức năng | Mô tả |
|---|---|
| 🔍 **GraphRAG** | Kết hợp Vector Search + Knowledge Graph cho suy luận đa chặng chuyên sâu (multi-hop reasoning) về QCVN/TCVN. |
| 📋 **Tra cứu QCVN/TCVN** | Tra cứu thông minh, trích dẫn chính xác điều khoản quy chuẩn xây dựng Việt Nam. |
| 🌉 **Thiết kế cầu dầm BTCT** | AI tự động sinh mô hình cầu dầm bê tông cốt thép hoàn chỉnh (mố cầu, trụ cầu, dầm dọc chữ I, bản mặt cầu, hệ gối cầu, lan can thép, và hệ thống móng cọc khoan nhồi) chuẩn IFC4. |
| 🏢 **Thiết kế tòa nhà** | AI sinh mô hình hình học tòa nhà 3D tự động từ mô tả ngôn ngữ tự nhiên. |
| 📊 **Xuất dữ liệu PLAXIS 3D** | Tự động xuất thông số kích thước cấu kiện móng cọc mố trụ sang file JSON làm đầu vào phân tích địa kỹ thuật cho PLAXIS 3D. |
| 🧊 **3D Viewer** | Render mô hình BIM trực tiếp trên trình duyệt sử dụng Three.js, hỗ trợ tương tác chọn cấu kiện hiển thị bảng thuộc tính trực quan. |
| 💬 **Streaming SSE** | Server-Sent Events cho phản hồi phản ánh thời gian thực của đại lý (Agent). |
| 🔐 **Auth + RBAC** | JWT authentication, phân quyền dựa trên vai trò (Role-Based Access Control). |

---

## Yêu cầu hệ thống

- **OS**: Ubuntu 22.04+ hoặc Windows 11 với **WSL2** (Ubuntu-22.04+)
- **Docker**: 24.0+ & Docker Compose v2
- **RAM**: ≥ 8GB (khuyến nghị 16GB)
- **Disk**: ≥ 10GB trống
- **API Key**: Google Gemini API key

---

## Cài đặt & Khởi chạy

### 1. Khởi động Docker trong WSL (Nếu dùng Windows)
Nếu chạy trên Windows thông qua WSL, bạn cần chắc chắn Docker daemon đã hoạt động. Khởi động dịch vụ trực tiếp với quyền `root` để tránh các lỗi phân quyền:
```bash
wsl -u root service docker start
```

### 2. Clone Dự án & Cấu hình môi trường
```bash
git clone https://github.com/your-org/bim-agent.git
cd bim-agent

cp .env.example .env
# Chỉnh sửa file .env điền GEMINI_API_KEY, POSTGRES_PASSWORD, NEO4J_PASSWORD, JWT_SECRET_KEY
```

### 3. Build & Khởi chạy Container
```bash
# Chạy ở môi trường Production (cổng 3001)
docker compose up -d --build

# Bật chế độ phát triển (bật hot-reload và mở cổng DB ra máy host)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

### 4. Nạp cơ sở dữ liệu quy chuẩn (Qdrant & Neo4j)
```bash
# Nạp dữ liệu văn bản mẫu
docker exec bim-backend python scripts/ingest_qcvn.py

# Xây dựng đồ thị tri thức GraphRAG
docker exec bim-backend python scripts/build_graph.py
```

### 5. Cấp quyền quản trị
Người dùng chỉ tự đăng ký được vai trò `engineer`, `architect` hoặc `viewer`. Vai trò `admin` / `project_manager` do người vận hành cấp cho tài khoản đã đăng ký:
```bash
docker exec bim-backend python scripts/set_role.py --email user@example.com --role admin
```

---

## Truy cập Dịch vụ

| Thành phần | Đường dẫn | Ghi chú |
|---|---|---|
| **Frontend UI** | [http://localhost:3001](http://localhost:3001) | Giao diện Chat + Visualizer 3D |
| **API Docs (Swagger)** | [http://localhost:8001/docs](http://localhost:8001/docs) | Tài liệu API FastAPI |
| **Qdrant Dashboard** | [http://localhost:6335/dashboard](http://localhost:6335/dashboard) | Quản lý Vector DB *(Chỉ Dev)* |
| **Neo4j Browser** | [http://localhost:7475](http://localhost:7475) | Truy vấn đồ thị tri thức *(Chỉ Dev)* |

---

## 🧪 Hệ thống Kiểm thử (Testing Suite)

Dự án tích hợp đầy đủ hệ thống kiểm thử tự động từ Unit/Integration Tests cho tới kiểm thử giao diện người dùng E2E.

Mọi push/PR đều chạy CI (`.github/workflows/ci.yml`): lint, quét secret, unit test + coverage, pip-audit, build Docker, và integration test trên stack Docker thật. Cấu hình pytest/coverage/ruff nằm trong `backend/pyproject.toml`; chi tiết cách chạy ở [backend/tests/README.md](backend/tests/README.md).

Chạy toàn bộ unit test trên máy (không cần Docker):
```bash
cd backend
pip install -r requirements.txt
pip install -e . --no-deps          # để import được package `src`
python -m pytest tests/unit
```

### 1. Chạy Backend Pipeline & Thiết kế Cầu (38 Test Cases)
Hệ thống kiểm thử này phủ toàn bộ luồng thiết kế cầu dầm BTCT, tính tuân thủ quy chuẩn, sinh hình học IFC4, trích xuất lưới và định tuyến câu lệnh thiết kế:
```bash
docker exec bim-backend pytest tests/unit/test_ifc_pipeline.py -v --tb=short
```

* **`TestBridgeSpec`**: Kiểm tra giá trị mặc định, tự động tính số trụ cầu (`num_piers = num_spans - 1`), kiểm tra ràng buộc kích thước (`ValueError` cho giá trị $\le 0$).
* **`TestBridgeCompliance`**: Kiểm tra tính tuân thủ quy chuẩn đường bộ/đường sắt TCVN ( clearance, deck thickness, L/h ratio...).
* **`TestBridgeIFCGeneration`**: Kiểm tra tính toàn vẹn của mô hình IFC4 được sinh động, đảm bảo mố, trụ, dầm chữ I, gối cầu, lan can, cọc nhồi được tạo đúng dạng hình học.
* **`TestDesignToolRouting`**: Xác thực cơ chế định tuyến từ khóa tiếng Việt (có dấu, không dấu, false-positive).

### 2. Kiểm thử Giao diện người dùng E2E (Playwright Visual Verification)
Để kiểm thử toàn bộ luồng trực quan hóa trên màn hình (đăng nhập, chuyển chế độ Thiết kế, gửi prompt thiết kế, click nút **Xem 3D**, tương tác mô hình Three.js, hiển thị thuộc tính cấu kiện):

#### Bước A: Cài đặt Playwright trên máy host Windows
```powershell
pip install playwright
playwright install chromium
```

#### Bước B: Chạy chẩn đoán giao diện nhanh (Diagnostic Check)
```powershell
python scratch/check_visibility.py
```

#### Bước C: Chạy kịch bản E2E mở trực tiếp Trình duyệt (Headed Mode)
Script sẽ tự động khởi chạy Chromium trên desktop của bạn để bạn có thể xem trực quan từng bước tương tác tự động và lưu 10 ảnh chụp tuần tự:
```powershell
python scratch/test_bridge_web.py
```

---

## Cấu trúc thư mục

```
bim-agent/
├── backend/
│   ├── src/
│   │   ├── api/              # API router điều hướng FastAPI
│   │   ├── core/             # Cấu hình chung, kết nối LLM Gemini
│   │   ├── database/         # Cơ sở dữ liệu người dùng (Postgres)
│   │   ├── data_pipeline/    # Động cơ sinh mô hình IFC cầu dầm & tòa nhà
│   │   ├── embeddings/       # Khởi tạo embedding nhanh (FastEmbed)
│   │   ├── knowledge_graph/  # Kết nối Neo4j, sinh truy vấn Cypher
│   │   └── rag/              # Trình phối hợp tác tử (Agent orchestrator)
│   │       └── tools/        # Công cụ RAG, IFC, Đồ thị, Thiết kế cầu
│   ├── alembic/              # Lịch sử cấu trúc DB (Migration)
│   ├── tests/                # Bộ kiểm thử Pytest
│   └── scripts/              # Tập lệnh nạp dữ liệu QCVN/TCVN
├── frontend/
│   ├── index.html            # Giao diện chính người dùng (Chat + 3D)
│   ├── css/ & js/            # CSS và Logic tương tác (Three.js Viewer)
│   └── nginx.conf            # Cấu hình máy chủ web tĩnh Nginx
└── docker-compose.yml        # Tệp cấu hình các container
```

---

## License

Private — All rights reserved. © 2026.
