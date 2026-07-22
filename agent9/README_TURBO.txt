AGENT 9 TURBO
- Phát hiện nguồn JSON có kiểm soát, tránh quét nhầm metadata đầu ra.
- Fingerprint SHA-256 và REUSE: không gọi API lại nếu nguồn không đổi.
- Retry thông minh cho 429, timeout và lỗi 5xx.
- Chuẩn hóa title <=100 ký tự, description <=5000, tags dưới giới hạn YouTube.
- Ghi file nguyên tử để tránh file JSON dở dang khi VPS bị ngắt.
- State nguyên tử, lưu lỗi riêng, có thống kê API/retry/reuse.
- Đầu ra tương thích Agent 10 trong /opt/unsolved-channel/output/metadata.

Chạy trong venv:
cd /opt/unsolved-channel
source agent1/venv/bin/activate
python3 agent9/main.py
