# ADR-0004: Nâng mức chi tiết model sinh ra lên LOD 300 cho nhà phố

## Trạng thái

Chấp nhận, 2026-11-06. Thay thế dòng "LOD 300 trở lên" trong mục *Không làm* của [bim-design-copilot.md](../ideas/bim-design-copilot.md).

## Bối cảnh

PR #23 dựng được tòa nhà IFC4 mức LOD 200, qua cả 8 kiểm tra model với 0 lỗi. Khi xem 3D, chủ dự án đánh giá model "chưa thực tế, như mô hình đồ chơi". Chủ dự án đã chọn cả bốn hướng cải thiện:

- mặt tiền giống nhà phố Việt Nam;
- cấu kiện chi tiết (LOD 300);
- nội thất và thiết bị;
- vật liệu và cách hiển thị.

Chủ dự án giao cho Claude nghiên cứu để chọn chuẩn so sánh.

Kết quả nghiên cứu, ngày 2026-11-06:
- **ifcopenshell 0.8.1 không cần Blender** vẫn dựng được cửa đi và cửa sổ có tham số (khung bao, cánh, đố) bằng `geometry.add_door_representation` và `geometry.add_window_representation`. Hai hàm này nhận kích thước theo **đơn vị project (mm)**, khác với các hàm hình học còn lại vốn nhận mét.
- `geometry.add_railing_representation` có lỗi trong bản 0.8.1 (`'Usecase' object has no attribute 'settings'`). Lan can và tay vịn phải tự dựng.
- Bộ trích hình học cho viewer (`extract_geometry`) bỏ qua màu vật liệu mà không báo lỗi, vì đọc `colour` sai kiểu dữ liệu.

## Quyết định

Nâng model nhà phố lên LOD 300, làm theo bốn đợt. Mỗi đợt là một hoặc nhiều task, mỗi task có test nghiệm thu khóa và giữ 0 lỗi ở `model_checks`.

1. **Vật liệu và hiển thị** (task 021): `IfcMaterial` cho mọi cấu kiện, màu vật liệu đi tới viewer.
2. **Mặt tiền và tổ chức nhà phố:**
   - chiều cao tầng 3,9 / 3,6 / 3,3 m;
   - ban công đua ra ≤ 1,2 m khi lộ giới ≥ 7 m;
   - mặt tiền kính, mái đón, giếng trời;
   - tum thang, sân thượng, tường chắn mái 1,1 m;
   - phòng ngủ có WC riêng.
3. **Cấu kiện LOD 300:** cửa đi và cửa sổ có tham số, cầu thang có bậc thật và tay vịn, lan can có trụ và thanh.
4. **Nội thất và thiết bị:** `IfcFurniture`, `IfcSanitaryTerminal` và các thiết bị khác, đặt theo luật, không va chạm.

Số liệu chuẩn lấy từ:
- TCVN 4451:2012;
- phụ lục quy định nhà liền kề dẫn QCVN 01:2021/BXD;
- thông lệ thiết kế nhà phố.

Số nào chưa đối chiếu được với văn bản gốc thì đánh dấu `needs_engineer_review`. TCVN 13967:2024 (Nhà ở riêng lẻ) chưa đọc được bản đầy đủ.

## Hệ quả

- Model nặng hơn: nhiều cấu kiện hơn, hình học phức tạp hơn. Phải theo dõi thời gian dựng, thời gian trích hình học và dung lượng JSON gửi cho viewer.
- Kiểm tra va chạm sẽ chạy trên nhiều cấu kiện hơn (nội thất, thiết bị). Quy tắc đặt cấu kiện phải chặt chẽ hơn.
- Bộ sinh cũ (`ifc_generator_v2`) không được nâng cấp theo. Model không có vật liệu vẫn hiển thị bằng màu mặc định theo lớp IFC.
