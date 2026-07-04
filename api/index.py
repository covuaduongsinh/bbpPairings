"""Vercel serverless entrypoint cho giao diện web bbpPairings.

Vercel gọi biến `handler` (lớp con BaseHTTPRequestHandler) một lần mỗi request.
Ta tái dùng nguyên lớp định tuyến `Handler` trong webui/server.py, chỉ thay:
  - store: Upstash Redis (KV) thay cho file trên đĩa (Vercel không có đĩa bền);
  - engine: binary Linux tĩnh đóng gói, copy sang /tmp và chmod +x để chạy được
    (thư mục bundle chỉ đọc);
  - đường dẫn index.html trỏ tới webui/ đã bundle.

Định tuyến toàn bộ request vào hàm này qua rewrite trong vercel.json; hàm tự
phân nhánh theo self.path (phục vụ index.html cho '/', xử lý '/api/*').
"""
import os
import pathlib
import shutil
import stat
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent   # gốc deployment
WEBUI = ROOT / "webui"
sys.path.insert(0, str(WEBUI))

import server      # noqa: E402  (webui/server.py — logic định tuyến dùng chung)
import store_kv    # noqa: E402

# --- binary engine: copy bản Linux tĩnh đã bundle sang nơi ghi được + chmod +x
_BUNDLED_EXE = pathlib.Path(os.environ.get("BBP_EXE", str(ROOT / "bin" / "bbpPairings")))
_RUN_EXE = pathlib.Path("/tmp") / "bbpPairings"


def _ensure_exe():
    try:
        if not _RUN_EXE.exists() or _RUN_EXE.stat().st_size != _BUNDLED_EXE.stat().st_size:
            shutil.copy(str(_BUNDLED_EXE), str(_RUN_EXE))
            _RUN_EXE.chmod(_RUN_EXE.stat().st_mode | stat.S_IEXEC
                           | stat.S_IXGRP | stat.S_IXOTH)
    except Exception as e:  # noqa
        # Để lỗi lộ rõ ở request đầu tiên thay vì âm thầm.
        sys.stderr.write(f"Không chuẩn bị được engine: {e}\n")
    return _RUN_EXE


# --- nối module server dùng chung cho môi trường serverless ---
server.WEB = WEBUI                                   # phục vụ webui/index.html
server.EXE = _ensure_exe()                           # đường dẫn engine
server.TIMEOUT = int(os.environ.get("BBP_TIMEOUT", "30"))
server.TOKEN = os.environ.get("BBP_TOKEN", "")       # rỗng = công khai
server.STORE = store_kv.KVStore()                    # Upstash từ biến môi trường

handler = server.Handler                             # Vercel gọi lớp này
