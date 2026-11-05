# ADR-0002: Nghiệm thu model bằng công cụ mở chạy tự động, không dùng Revit

## Trạng thái

Chấp nhận, 2026-11-05.

## Bối cảnh

Người dùng mục tiêu chủ yếu làm việc trong Revit, nên lúc đầu tiêu chí đặt ra là "mở trong Revit không lỗi". Nhưng chủ dự án chưa dùng Revit, còn Revit có bản quyền, chỉ chạy trên Windows và không chạy được trong CI. Điều khiển Revit qua giao diện thì chậm, dễ vỡ và không lặp lại được. Phần lớn code do agent viết, nên tiêu chí nghiệm thu bắt buộc phải chạy được mà không cần người.

## Quyết định

Model sinh ra là **IFC4 chuẩn** và được nghiệm thu bằng các bước chạy tự động:

| Kiểm tra | Công cụ |
|---|---|
| IFC hợp lệ theo schema và luật của IFC4 | `ifcopenshell.validate` |
| Đủ cấu kiện và thuộc tính theo LOD 200 | IDS (Information Delivery Specification của buildingSMART), kiểm bằng IfcTester |
| Hình học: va chạm, cửa trong tường, cột trên trục, sàn khép kín | ifcopenshell geometry, test trong repo |
| Bố trí và quy chuẩn | luật trong gói kiểu nhà (ADR-0001) |
| Nhìn bằng mắt | Blender + Bonsai chạy không giao diện, render ảnh mặt bằng và phối cảnh |

Revit chỉ dùng **một lần ở cuối**: kỹ sư mở model và kiểm tra.

Phần giải thích cho người dùng **không phụ thuộc phần mềm**: biểu diễn thế nào cho đúng, chọn lớp IFC nào, theo điều khoản nào. Hướng dẫn thao tác Revit cụ thể để sau, khi có kỹ sư duyệt.

## Hệ quả

- Mọi tiêu chí đều chạy được trong CI và trên máy dev, không cần license.
- Bonsai dùng cùng thư viện ifcopenshell với backend, nên ảnh render phản ánh đúng file IFC.
- Còn khả năng model hợp lệ IFC nhưng Revit nhập vào bị lệch. Rủi ro này chỉ lộ ra ở buổi kiểm tra của kỹ sư.
- Cần cài Blender và Bonsai trong WSL và CI. Cách cài sẽ chốt trong spec bước 2.

## Quyết định liên quan

- ADR-0001: kiểu nhà là gói dữ liệu.
