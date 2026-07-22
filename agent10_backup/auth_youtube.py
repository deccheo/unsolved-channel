#!/usr/bin/env python3
import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

from google_auth_oauthlib.flow import Flow

from config import CLIENT_SECRET_FILE, SCOPES, TOKEN_FILE


def main() -> None:
    if not CLIENT_SECRET_FILE.exists():
        raise SystemExit(f"Không tìm thấy: {CLIENT_SECRET_FILE}")

    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_FILE),
        scopes=SCOPES,
        redirect_uri="http://localhost:8080/",
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    print("\n=== XÁC THỰC YOUTUBE ===")
    print("1. Mở đường dẫn dưới đây trên trình duyệt điện thoại.")
    print("2. Đăng nhập đúng tài khoản quản lý kênh YouTube.")
    print("3. Chấp nhận quyền.")
    print("4. Trình duyệt có thể báo không truy cập được localhost.")
    print("5. Sao chép TOÀN BỘ đường dẫn đang hiện trên thanh địa chỉ và dán vào đây.\n")
    print(auth_url)
    print()

    redirected_url = input("Dán toàn bộ URL sau khi cấp quyền: ").strip()
    if not redirected_url:
        raise SystemExit("Chưa nhận được URL xác thực.")

    flow.fetch_token(authorization_response=redirected_url)
    TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")
    TOKEN_FILE.chmod(0o600)

    print(f"\nĐã lưu token: {TOKEN_FILE}")
    print("Xác thực YouTube thành công.")

if __name__ == "__main__":
    main()
