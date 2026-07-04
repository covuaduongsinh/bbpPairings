#!/bin/sh
# Khởi động giao diện web BBP Pairings (dùng cho LAN nhiều máy).
#   ./webui/start.sh
# Sau đó mở http://localhost:8765 trên máy này, hoặc http://<IP-máy>:8765 từ
# máy khác trong cùng mạng LAN (địa chỉ được in ra khi khởi động). Ctrl+C để dừng.
cd "$(dirname "$0")/.." || exit 1
if [ ! -f bbpPairings.exe ]; then
  echo "Không tìm thấy bbpPairings.exe. Hãy build engine trước:  make static=yes" >&2
  exit 1
fi
if command -v python3 >/dev/null 2>&1; then
  exec python3 webui/server.py
elif command -v python >/dev/null 2>&1; then
  exec python webui/server.py
else
  echo "Chưa cài Python 3." >&2
  exit 1
fi
