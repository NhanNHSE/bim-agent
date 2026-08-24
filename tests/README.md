# 🧪 Test Directory & Output Guidelines

Thư mục này tập trung toàn bộ các file phục vụ kiểm thử (test files) và kết quả/sản phẩm kiểm thử (test outputs) của dự án **BIM AI Agent**, tránh gây rối codebase.

---

## 📁 Cấu trúc thư mục `tests/`

```
tests/
├── unit/                 # Các bài test tự động (Pytest unit & integration tests)
│   ├── conftest.py       # Fixtures & Pytest setup
│   ├── test_auth.py      # Test hệ thống Authentication & RBAC
│   ├── test_chat.py      # Test API Chat & Conversations
│   ├── test_graph_safety.py  # Test an toàn Cypher query Neo4j
│   ├── test_ifc_pipeline.py  # Test sinh file IFC & trích xuất hình học
│   ├── test_reflection.py    # Test quy trình suy luận Agent reflection
│   └── test_security.py      # Test bảo mật & chống injection
│
├── scripts/              # Các kịch bản test độc lập (Smoke test, API bridge test, Utility)
│   ├── count_json.py        # Utility đếm dữ liệu JSON
│   ├── test_bridge_api.sh   # Bash script test API giao tiếp Cầu dầm BTCT
│   ├── test_geometry.py     # Script test trích xuất 3D mesh hình học
│   └── test_ifc_v2.py       # Smoke test bộ sinh IFC v2
│
└── outputs/              # Nơi LƯU TRỮ TOÀN BỘ KẾT QUẢ TEST (Screenshots, Logs, Test IFC/JSON outputs)
    ├── chat_full_ui.png     # Screenshots minh họa UI
    ├── chat_ui.png
    └── [Tất cả kết quả test phát sinh trong tương lai]
```

---

## 📌 Quy định lưu trữ kết quả test (Test Outputs Rule)
* **KHÔNG** lưu file ảnh screenshot, file log tạm hay file JSON kết quả test ở thư mục gốc (`/`) hoặc trong `backend/`/`frontend/`.
* **TẤT CẢ** sản phẩm kết quả sau khi test (hình ảnh render, log test, file IFC/JSON tạo ra từ test) phải được lưu vào thư mục **`tests/outputs/`**.
