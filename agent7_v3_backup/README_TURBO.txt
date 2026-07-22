AGENT 7 TURBO

- Giữ nguyên engine renderer.py mà main.py đang sử dụng.
- Không hợp nhất hoặc xóa render.py.
- Render song song mặc định 2 cảnh.
- Resume: tái sử dụng clip tạm hợp lệ sau khi tiến trình bị ngắt.
- Retry lỗi FFmpeg tạm thời.
- Chỉ tạo video final khi đủ 100% cảnh có ảnh + audio.
- Kiểm tra video có cả hình, tiếng và thời lượng đúng trước khi cập nhật database.
- Xuất tên *-final.mp4 để Agent 10 nhận diện.
- Xóa file tạm sau khi hoàn tất; khi lỗi giữ lại để resume.

Biến môi trường tùy chọn:
AGENT7_MAX_WORKERS=2
AGENT7_PRESET=veryfast
AGENT7_CRF=23
AGENT7_RETRY_LIMIT=2
AGENT7_CLEAN_TEMP=1
AGENT7_REUSE_CLIPS=1
AGENT7_PREVIEW_MODE=0
