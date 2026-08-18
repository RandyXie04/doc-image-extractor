from __future__ import annotations

import getpass
import hashlib


password = getpass.getpass("輸入要設定的公開服務密碼：")
confirmation = getpass.getpass("再次輸入密碼確認：")
if not password or password != confirmation:
    raise SystemExit("密碼為空白或兩次輸入不一致。")

password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
print("\n請將以下內容貼到 Streamlit Community Cloud 的 App settings → Secrets：\n")
print(f'APP_PASSWORD_HASH = "{password_hash}"')
print("\n請只保存雜湊值，不要把實際密碼提交到 GitHub。")
