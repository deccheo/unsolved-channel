AGENT 7 TURBO V2
================

Mục tiêu:
- Không chờ đủ toàn bộ câu chuyện mới render.
- Mỗi khi đủ một cụm cảnh liên tục, render thành một part.
- Khi toàn bộ cảnh đã READY, tự ghép các part thành final.mp4.

Mặc định:
- AGENT7_PART_SIZE=10
- AGENT7_MAX_WORKERS=2
- Chỉ render dãy cảnh liên tục bắt đầu từ cảnh 1.
- Part cuối dưới 10 cảnh chỉ render khi toàn bộ câu chuyện đã sẵn sàng.

Đầu ra:
- output/videos/<case>/parts/part_001_s001-e010.mp4
- output/videos/<case>/parts/part_002_s011-e020.mp4
- output/videos/<case>/final.mp4 (khi đủ toàn bộ cảnh)

Database:
- Tự tạo bảng video_parts.
- Không xóa hoặc đổi các bảng/cột cũ.

Chạy:
  cd /opt/unsolved-channel
  source agent1/venv/bin/activate
  python3 agent7/main.py

Biến môi trường tùy chọn:
  AGENT7_PART_SIZE=10
  AGENT7_MAX_WORKERS=2
  AGENT7_PRESET=veryfast
  AGENT7_CRF=23
