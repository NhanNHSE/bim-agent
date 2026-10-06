# Hướng dẫn sử dụng Understand Anything cho dự án BIM AI Agent

Tài liệu này hướng dẫn cách chạy phân tích mã nguồn và khởi động giao diện đồ thị kiến trúc trực quan (Dashboard) của dự án **BIM AI Agent** bất cứ khi nào bạn cần mà không cần trợ lý AI.

---

## 1. Khởi động nhanh Dashboard (Xem sơ đồ hiện tại)

Nếu sơ đồ dự án đã được tạo sẵn (trong thư mục `.understand-anything/knowledge-graph.json`), bạn chỉ cần khởi động máy chủ giao diện Vite để xem.

### Bước 1: Mở Terminal (PowerShell hoặc CMD trên Windows)

Chạy các lệnh sau để di chuyển vào thư mục Dashboard và thiết lập biến môi trường trỏ đến dự án BIM:

**Trên PowerShell:**
```powershell
# Di chuyển đến thư mục dashboard của Understand Anything
cd D:\Project\Understand-Anything\understand-anything-plugin\packages\dashboard

# Khai báo đường dẫn dự án cần phân tích
$env:GRAPH_DIR="D:\Project\LLM\BIM"

# Khởi chạy máy chủ giao diện
npx vite --host 127.0.0.1
```

**Trên Command Prompt (CMD):**
```cmd
cd /d D:\Project\Understand-Anything\understand-anything-plugin\packages\dashboard
set GRAPH_DIR=D:\Project\LLM\BIM
npx vite --host 127.0.0.1
```

### Bước 2: Lấy link truy cập kèm Token
Khi chạy thành công, màn hình terminal sẽ hiển thị dòng chữ tương tự như sau:
```text
  🔑  Dashboard URL: http://127.0.0.1:5173?token=<token-hiển-thị-trên-terminal>
```
*   **Quan trọng:** Bạn **bắt buộc** phải sao chép toàn bộ đường dẫn bao gồm cả phần `?token=...` dán vào trình duyệt web để vượt qua cổng xác thực bảo mật của Dashboard.

---

## 2. Cách chạy lại phân tích dự án khi có thay đổi Code

Khi bạn thêm file mới hoặc thay đổi cấu trúc mã nguồn của dự án BIM, bạn cần cập nhật lại đồ thị kiến trúc (`knowledge-graph.json`).

Nếu bạn đang sử dụng **AI Coding Assistant** (như Gemini CLI, Claude Code, Cursor, Codex...):

### Cách 1: Sử dụng Slash Command (Nếu công cụ hỗ trợ)
Bạn chỉ cần gõ lệnh sau trong cửa sổ chat với AI:
```bash
/understand
```
Lệnh này sẽ tự động kích hoạt tiến trình phân tích 6 bước để ghi đè đồ thị mới.

### Cách 2: Yêu cầu AI Assistant chạy hộ bằng ngôn ngữ tự nhiên
Bạn có thể ra lệnh cho AI trong khung chat:
> *"Hãy dùng công cụ understand-anything để quét và phân tích lại dự án này."*

---

## 3. Cấu hình loại trừ file (`.understandignore`)

Để quá trình quét diễn ra nhanh và không bị quá tải bởi các file rác hoặc file dữ liệu lớn, cấu hình loại trừ đã được thiết lập sẵn tại:
👉 `D:\Project\LLM\BIM\.understand-anything\.understandignore`

Mặc định hệ thống đã bỏ qua:
*   Các file mô hình 3D BIM (`.ifc` ở mọi thư mục)
*   Thư mục lưu trữ tài liệu PDF (`data/qcvn/`, `data/tcvn/`)
*   Thư mục virtual environment, node_modules, cache, và file logs.

*Nếu bạn muốn phân tích thêm hoặc ẩn đi một thư mục nào đó, hãy mở file `.understandignore` lên và chỉnh sửa tương tự như file `.gitignore`.*

---

## 4. Các phím tắt khi xem trên Dashboard

Khi giao diện Dashboard đã mở trên trình duyệt, bạn có thể tương tác nhanh bằng các thao tác:
*   **Cuộn chuột:** Thu phóng sơ đồ (Zoom In/Out).
*   **Giữ chuột trái và kéo:** Di chuyển vùng nhìn đồ thị (Pan).
*   **Click chuột vào 1 Node:** Hiện thông tin tóm tắt ở thanh bên phải, đồng thời hiển thị toàn bộ mã nguồn của file đó ở khung phía dưới.
*   **Click đúp chuột (Double Click) vào Node:** Tập trung (Focus) và mở rộng các node liên quan trực tiếp.
