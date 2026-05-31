# BIM AI Agent — Development Workflow

## Quy trình

```
Phân tích → Code → Build → Test → Verify UI
```

### 1. Phân tích
- Xác định scope: backend, frontend, hay cả hai
- Đọc code liên quan trước khi sửa

### 2. Code
- Sửa từ layer thấp lên: `core → data_pipeline → rag → api → frontend`
- Giữ nguyên comments/docstrings không liên quan

### 3. Build
```bash
# Backend thay đổi
docker compose up -d --build backend

# Frontend thay đổi (static files → chỉ cần refresh browser)
# Trừ khi sửa nginx.conf → rebuild frontend

# Cả hai
docker compose up -d --build backend frontend
```

### 4. Test
```bash
# Health check
curl -sf http://localhost:8001/api/v1/health

# Unit tests
docker exec bim-backend python -m pytest tests/ -v

# Backend logs
docker compose logs backend --tail 20
```

### 5. Verify UI
- Mở `http://localhost:3001`, test luồng chính
- Kiểm tra feature mới hoạt động
- Kiểm tra feature cũ không bị ảnh hưởng (regression)

## Commit
```
feat: mô tả ngắn gọn
fix: mô tả ngắn gọn
refactor: mô tả ngắn gọn
```
