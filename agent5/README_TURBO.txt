AGENT 5 TURBO

Thay đổi chính:
- Chạy song song mặc định 2 worker (AGENT5_MAX_WORKERS=2).
- Cache ảnh cũ trước khi gọi Gemini.
- Chỉ retry lỗi tạm thời như 429/5xx/timeout; lỗi cố định dừng ngay để tránh tốn phí.
- SQLite WAL + busy_timeout 30 giây để hỗ trợ worker song song.
- Benchmark thời gian từng cảnh và toàn bộ lần chạy.

Khuyến nghị:
- Giữ 2 worker lúc đầu.
- Chỉ tăng lên 3 bằng biến môi trường AGENT5_MAX_WORKERS=3 khi không gặp nhiều 429/503.
- Số worker không làm giảm số ảnh tính phí; nó chỉ giúp xử lý nhanh hơn.
