# ADR-0001: Kiểu nhà là gói dữ liệu trên một lõi sinh model chung

## Trạng thái

Đề xuất, 2026-11-05. Chuyển sang "Chấp nhận" khi bản thử bộ giải ràng buộc trên nhà phố đạt (xem Rủi ro).

## Bối cảnh

`data_pipeline/ifc_generator_v2.py` sinh nhà theo cách: LLM điền khoảng 40 tham số vào `BuildingSpec` (`data_pipeline/base_spec.py`), rồi code đặt các khối hộp. Không có bước nào bảo đảm tường nối nhau, cửa nằm trong tường, phòng có lối vào hay thoát nạn đạt quy chuẩn. Chủ dự án đánh giá model sinh ra "quá đơn giản, nhiều lỗi sai, khó áp dụng". Định hướng mới ([docs/ideas/bim-design-copilot.md](../ideas/bim-design-copilot.md)) cần 4 kiểu nhà trong MVP và phải mở rộng được sang loại kiến trúc khác.

## Yếu tố quyết định

- Thêm một kiểu nhà không được tốn công bằng viết lại bộ sinh.
- Kết quả phải kiểm chứng tự động được (ADR-0002).
- Mỗi cấu kiện phải giải thích được vì sao nó ở đó.
- Cùng một mô tả phải cho cùng một model (tất định), để test được.

## Các phương án

1. **Mỗi kiểu nhà một bộ sinh viết bằng code.** Dễ bắt đầu, nhưng N kiểu nhà tốn N lần công và luật bị lặp giữa các kiểu.
2. **LLM sinh thẳng hình học hoặc IFC.** Linh hoạt nhất, nhưng không tất định, không bảo đảm đúng hình học, và rất khó test.
3. **Lõi chung và gói dữ liệu cho từng kiểu.** LLM chỉ lập chương trình công năng; bộ giải ràng buộc xếp mặt bằng; lõi chung sinh cấu kiện; bộ kiểm tra chạy sau cùng.

## Quyết định

Chọn **phương án 3**.

- **LLM** chỉ chuyển mô tả tiếng Việt thành *chương trình công năng* có schema: phòng, diện tích, quan hệ kề nhau, số tầng, lô đất. Đầu ra được validate bằng Pydantic.
- **Bộ giải ràng buộc** xếp mặt bằng một cách tất định. Ứng viên là CP-SAT của OR-Tools, chốt sau bản thử.
- **Lõi chung** đi từ mặt bằng tới lưới trục, tầng, rồi cấu kiện IFC4 (`ifcopenshell.file(schema="IFC4")`), có quan hệ đúng giữa cấu kiện: lỗ mở trong tường, tường nối nhau, phòng là `IfcSpace`.
- **Gói kiểu nhà** gồm ba thành phần dữ liệu: mẫu chương trình công năng, luật riêng của kiểu, và bộ mô tả mẫu cho test. Luật nào có nguồn QCVN thì ghi điều khoản; luật nào là kinh nghiệm thì đánh dấu "cần kỹ sư xác nhận".

## Hệ quả

**Tích cực**
- Kiểu nhà mới, hoặc loại kiến trúc mới, chỉ cần một gói dữ liệu cùng bộ test của nó.
- Kết quả tất định, nên golden set và CI chặn được lỗi hồi quy.
- Mỗi luật đều có nguồn, đó là nền cho lớp giải thích.

**Tiêu cực**
- Phải viết lại phần lõi; bộ sinh nhà hiện tại chỉ còn dùng để so sánh với điểm xuất phát.
- Thêm dependency là OR-Tools.

**Rủi ro**
- Bộ giải xếp được mặt bằng *hợp lệ* nhưng *không hợp lý* (phòng méo, lối đi vòng). Giảm rủi ro bằng bản thử 1–2 tuần trên nhà phố, đánh giá bằng bộ kiểm tra và ảnh render. Nếu không đạt thì xem lại phương án 1 với một số ít kiểu nhà.
- Luật kinh nghiệm sai từ gốc mà chỉ phát hiện ở buổi duyệt cuối của kỹ sư.

## Quyết định liên quan

- ADR-0002: nghiệm thu model bằng công cụ mở.
