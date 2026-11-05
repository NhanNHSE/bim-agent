# ADR-0003: Ghim `fastembed==0.4.1` cho tới khi nâng cấp kèm nạp lại Qdrant

## Trạng thái

Chấp nhận, 2026-10-06. Chép vào repo ngày 2026-11-05; trước đó quyết định này chỉ nằm trong ghi chú cục bộ.

## Bối cảnh

Embedding chạy trong backend bằng FastEmbed với model `paraphrase-multilingual-MiniLM-L12-v2`. Từ bản 0.6, FastEmbed đổi cách gộp vector của model này từ CLS sang mean pooling. Vector của câu hỏi khi đó lệch với vector đã nạp trong Qdrant: truy hồi kém đi mà **không có lỗi nào được báo**. Bản 0.5.x vẫn khóa `pillow<11`.

## Quyết định

Ghim `fastembed==0.4.1` trong `backend/requirements.txt`. Các CVE của pillow bị kéo theo được chấp nhận, có ghi lý do và điều kiện gỡ trong `backend/.pip-audit-ignore`.

## Hệ quả

- Nâng FastEmbed phải làm **trong cùng một thay đổi** gồm: nạp lại toàn bộ Qdrant, đo truy hồi trước và sau bằng golden set, và gỡ các ID pillow khỏi `.pip-audit-ignore`.
- Chưa có golden set truy hồi thì chưa nâng được.
