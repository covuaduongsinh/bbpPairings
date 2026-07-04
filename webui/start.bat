@echo off
REM ============================================================
REM  Khoi dong giao dien web BBP Pairings (dung cho LAN nhieu may)
REM  Nhay doi chuot vao file nay de chay. Sau do mo trinh duyet:
REM    - Tren may nay:   http://localhost:8765
REM    - Tu may khac:    http://<dia-chi-IP-may-nay>:8765
REM  (Dia chi LAN se duoc in ra man hinh khi khoi dong.)
REM  Nhan Ctrl+C de dung.
REM ============================================================
cd /d "%~dp0.."
if not exist "bbpPairings.exe" (
  echo Khong tim thay bbpPairings.exe. Hay build engine truoc:
  echo     make static=yes
  pause
  exit /b 1
)
where python >nul 2>nul
if %errorlevel%==0 (
  python webui\server.py
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py webui\server.py
  ) else (
    echo Chua cai Python 3. Hay tai tu https://www.python.org/downloads/
  )
)
pause
