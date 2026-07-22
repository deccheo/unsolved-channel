AGENT 10 TURBO
- Tìm video trong mọi thư mục con của output/videos.
- Ưu tiên file full/final, chặn preview và part theo mặc định.
- Preflight video, audio, metadata và thumbnail.
- Chống đăng trùng bằng state/receipt.
- Checkpoint ngay sau khi YouTube upload thành công.
- Nếu Drive lỗi, lần chạy sau chỉ archive; KHÔNG upload YouTube lần hai.
- State JSON ghi nguyên tử, an toàn khi VPS dừng đột ngột.
- Giới hạn theo ngày và theo mỗi lần chạy.
- Log thống kê rõ ràng.

Chạy:
  source /opt/unsolved-channel/agent1/venv/bin/activate
  python3 /opt/unsolved-channel/agent10/main.py

Xác thực lần đầu:
  python3 /opt/unsolved-channel/agent10/auth_youtube.py
