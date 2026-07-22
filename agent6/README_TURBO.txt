AGENT 6 TURBO
=============

Tối ưu:
- Chạy song song mặc định 2 worker (AGENT6_MAX_WORKERS, tối đa 4).
- Cache WAV theo model + voice + narration.
- Dùng lại audio trong database nếu narration giống hệt.
- Resume: chỉ lấy cảnh PENDING/RETRY.
- Retry thông minh chỉ cho lỗi tạm thời 429/5xx/timeout.
- SQLite WAL + busy_timeout.
- Thống kê API calls, retry, cache và thời gian.

Mặc định:
AGENT6_MAX_CLIPS=10
AGENT6_MAX_WORKERS=2
AGENT6_RETRY_LIMIT=2
AGENT6_RETRY_DELAY=12

Chạy bằng venv:
cd /opt/unsolved-channel
source agent1/venv/bin/activate
python3 agent6/main.py
