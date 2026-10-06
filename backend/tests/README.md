# 🧪 Kiểm thử — BIM AI Agent backend

## Cấu trúc

```
backend/tests/
├── unit/          # Pytest, mock toàn bộ dịch vụ ngoài (Gemini, Neo4j, Qdrant; DB là SQLite in-memory)
├── integration/   # Pytest, chạy trong container backend với stack Docker thật — không mock
├── smoke/         # Script chạy tay (không phải pytest): sinh IFC mẫu, trích hình học, gọi API cầu
└── outputs/       # Kết quả sinh ra khi test (IFC/JSON, ảnh, log) — bị .gitignore, không commit
```

## Chạy

```bash
# Unit — trên máy (từ thư mục backend/, sau khi pip install -r requirements.txt && pip install -e . --no-deps)
python -m pytest tests/unit

# Unit — trong container
docker exec bim-backend pytest tests/unit -v

# Integration — cần stack đang chạy (docker compose up -d)
docker exec -e BIM_INTEGRATION=1 bim-backend pytest tests/integration -v

# Smoke
docker exec bim-backend python tests/smoke/smoke_ifc_v2.py
docker exec bim-backend python tests/smoke/smoke_geometry.py
bash backend/tests/smoke/smoke_bridge_api.sh
```

Không chạy `unit/` và `integration/` trong cùng một lệnh pytest: `unit/conftest.py` ghi đè biến môi trường (mật khẩu DB, chế độ agent) cho cả tiến trình.

## Quy ước

- Dịch vụ ngoài trong `unit/` luôn được mock; không gọi LLM thật, không cần API key.
- `integration/` tự bỏ qua nếu thiếu `BIM_INTEGRATION=1`.
- `/register` bị giới hạn 5 lần / IP / 15 phút (Redis): test integration dùng chung tài khoản qua fixture `engineer`.
- Mọi file kết quả ghi vào `tests/outputs/`, không ghi ra thư mục gốc hay `src/`.
- CI (`.github/workflows/ci.yml`) chạy cả unit (kèm coverage, ngưỡng trong `pyproject.toml`) và integration cho mọi PR.
