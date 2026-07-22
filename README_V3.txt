AGENT 2 V3

Tính năng chính:
- Ưu tiên overall_score DESC; nếu bằng điểm thì created_at DESC.
- Retry tối đa 3 lần.
- Backoff mặc định 5 phút -> 30 phút -> lần thứ 3 chuyển FAILED.
- Không xử lý case chưa đến next_retry_at.
- Nguồn được lưu/reuse trong case_sources.
- VERIFIED chuyển production_status=VERIFIED để Agent 3 nhận.
- NEEDS_REVIEW chuyển production_status=REVIEW.
- FAILED không được xử lý lại.

Cài đặt:
1. Backup agent2 hiện tại.
2. Giải nén file vào /opt/unsolved-channel.
3. Dùng venv của agent1.
4. Chạy py_compile rồi test main.py.

Biến .env tùy chọn:
AGENT2_GEMINI_MODEL=gemini-3.1-flash-lite
AGENT2_MAX_CASES=5
AGENT2_MAX_SOURCES=8
AGENT2_MIN_SOURCES=2
AGENT2_MIN_SCORE=40
AGENT2_MAX_RETRIES=3
AGENT2_BACKOFF_MINUTES=5,30,120
