# BIM Design Copilot

> Định hướng sản phẩm, chốt với chủ dự án ngày 2026-11-05. Quyết định kiến trúc đi kèm: [ADR-0001](../adr/0001-kieu-nha-la-du-lieu.md), [ADR-0002](../adr/0002-nghiem-thu-model-bang-cong-cu-mo.md).

## Bài toán

Làm sao giúp sinh viên và kỹ sư có ý tưởng **biến ý tưởng thành model nhà đúng chuẩn, hiểu vì sao nó đúng, và dựng tiếp được**, với nhiều kiểu nhà và mở rộng được sang loại kiến trúc khác?

Người dùng chính: sinh viên, kỹ sư trẻ, kỹ sư và kiến trúc sư đang đi làm. Họ có kiến thức và trí tưởng tượng nhưng chưa biết biểu diễn thế nào cho đúng, hoặc chưa biết dựng model 3D.

## Vì sao phải đổi cách sinh model

Bộ sinh hiện tại cho LLM điền khoảng 40 con số vào spec, rồi code đặt các khối hộp, dùng khoảng 20 loại đối tượng IFC. Kết quả có ba loại lỗi: **hình học sai** (tường không nối, cửa không nằm trong tường), **bố trí phi lý**, và **quá thô** (thiếu cấu kiện). Thêm tham số vào cách này không nâng được chất lượng.

## Hướng đi

- **Kiểu nhà là dữ liệu, không phải code.** Lõi chung chạy theo chuỗi:
  1. LLM đọc mô tả tiếng Việt và lập chương trình công năng: phòng, diện tích, phòng nào cạnh phòng nào, số tầng, lô đất;
  2. bộ giải ràng buộc xếp mặt bằng;
  3. lưới kết cấu khớp với mặt bằng, rồi sinh cấu kiện IFC4;
  4. bộ kiểm tra chạy; lần sinh nào trượt thì sinh lại;
  5. mỗi cấu kiện được gắn lời giải thích.
- **Mỗi kiểu nhà là một gói** gồm mẫu chương trình công năng, luật riêng của kiểu và bộ mô tả mẫu để test.
- **Lớp giải thích** nêu lý do, điều khoản QCVN và cách biểu diễn đúng, không phụ thuộc phần mềm. Nhờ vậy model vừa là kết quả để dùng tiếp, vừa là bài học.
- **Hỏi đáp BIM** dùng lại pipeline RAG của phần quy chuẩn.

## Tiêu chí nghiệm thu (chạy tự động, chi tiết ở ADR-0002)

- **IFC hợp lệ:** `ifcopenshell.validate` không báo lỗi; IDS kiểm đủ cấu kiện và thuộc tính LOD 200.
- **Hình học:**
  - 0 va chạm;
  - mọi cửa đi và cửa sổ nằm trong lỗ mở của tường;
  - tường nối nhau tại góc;
  - cột nằm trên giao điểm lưới trục;
  - sàn khép kín theo tường bao.
- **Bố trí:** mọi phòng là một `IfcSpace` và có lối vào; cầu thang và thoát nạn đạt QCVN 06:2022.
- **Đủ cấu kiện LOD 200:** móng, cột, dầm, sàn, tường, cửa đi, cửa sổ, cầu thang, lan can, mái, phòng.
- **Nhìn bằng mắt:** ảnh render mặt bằng và phối cảnh bằng Blender/Bonsai chạy không giao diện.
- **Golden set** khoảng 30 mô tả mỗi kiểu nhà, chặn trong CI.
- **Cuối cùng:** kỹ sư mở model bằng Revit và duyệt bảng "luật cần kỹ sư xác nhận".

## Giả định cần kiểm chứng

- [ ] **Rủi ro lớn nhất:** bộ giải ràng buộc xếp được mặt bằng *hợp lý*, không chỉ *hợp lệ*. Kiểm bằng một bản thử 1–2 tuần trên nhà phố trước khi cam kết.
- [ ] LLM trích đúng chương trình công năng từ tiếng Việt. Đo bằng golden set.
- [ ] Blender + Bonsai chạy được không giao diện trong WSL và CI.
- [ ] Người dùng muốn hiểu, không chỉ muốn nhận file. Thử với 3–5 người.
- [ ] Có nguồn tri thức BIM được phép dùng: hướng dẫn BIM của Bộ Xây dựng và đặc tả IFC4 là công khai; ISO 19650 và tài liệu Autodesk có bản quyền.

## MVP, theo thứ tự

1. Sửa các lỗi tìm thấy khi rà soát: tải IFC trả 401, upload lớn hơn 1 MB trả 413, rate limit đăng nhập dùng chung cho mọi người.
2. Golden set và bộ kiểm tra model trong CI; đo bộ sinh hiện tại để có điểm xuất phát.
3. Bản thử bộ giải ràng buộc trên nhà phố. Nếu không đạt thì quay lại chọn hướng khác.
4. Lõi chung và các gói kiểu nhà, làm lần lượt; kiểu nào đạt bộ kiểm tra mới sang kiểu sau: **nhà phố → chung cư thấp tầng (≤ 9 tầng) → văn phòng/trường học nhỏ → biệt thự**.
5. Lớp giải thích trong viewer 3D, hỏi đáp BIM.
6. Kỹ sư duyệt.

## Không làm (và lý do)

- **Hồ sơ nộp/thi công, LOD 300+:** cần thuyết minh tính toán kết cấu, cốt thép, và chữ ký kỹ sư có chứng chỉ hành nghề. Chỉ xem lại sau khi LOD 200 đạt và có kỹ sư đồng hành.
- **Cầu và đường:** tạm dừng đầu tư, giữ code hiện có. Một loại công trình làm tốt hơn ba loại làm sơ sài.
- **Hướng dẫn thao tác Revit, add-in Revit, trình chỉnh sửa model trên web:** không kiểm chứng tự động được, hoặc mỗi thứ là một dự án riêng.
- **Kiểu nhà thứ 5 trở đi trong MVP:** sau MVP, thêm kiểu nhà chỉ cần thêm một gói dữ liệu.

## Câu hỏi còn mở

- Đầu vào lô đất: người dùng nhập kích thước, hay chọn từ mẫu?
- Chọn công cụ IDS và cách chạy Blender/Bonsai trong CI (sẽ chốt trong spec bước 2).
