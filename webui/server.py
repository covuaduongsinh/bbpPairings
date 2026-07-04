#!/usr/bin/env python3
"""Máy chủ web cục bộ/LAN cho bbpPairings — gọi trực tiếp bbpPairings.exe.

Chỉ dùng thư viện chuẩn Python 3. Chạy:

    python webui/server.py

Rồi mở http://<địa-chỉ-IP-máy-chủ>:8765 từ bất kỳ máy nào trong cùng mạng LAN
(hoặc http://localhost:8765 ngay trên máy chủ).

Biến môi trường (tùy chọn):
    BBP_PORT   cổng lắng nghe (mặc định 8765)
    BBP_HOST   địa chỉ bind (mặc định 0.0.0.0 = mọi giao diện mạng, cho LAN)
    BBP_EXE    đường dẫn tới bbpPairings.exe (mặc định cạnh thư mục webui)
    BBP_DATA   thư mục lưu giải đấu (mặc định webui/data)
    BBP_TOKEN  nếu đặt, mọi request phải kèm ?token=... hoặc header X-Token
    BBP_TIMEOUT thời gian tối đa mỗi lần gọi engine, giây (mặc định 120)

Trạng thái giải được lưu ở phía máy chủ (BBP_DATA/*.json), nên làm mới trình
duyệt không mất dữ liệu và nhiều thiết bị thấy cùng một giải. Ghi có kiểm tra
phiên bản (optimistic locking) để hai trọng tài không ghi đè lẫn nhau.
"""
import http.server
import json
import os
import pathlib
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import trfbuild  # noqa: E402

WEB = pathlib.Path(__file__).resolve().parent
ROOT = WEB.parent
EXE = pathlib.Path(os.environ.get("BBP_EXE", str(ROOT / "bbpPairings.exe")))
DATA = pathlib.Path(os.environ.get("BBP_DATA", str(WEB / "data")))
PORT = int(os.environ.get("BBP_PORT", "8765"))
HOST = os.environ.get("BBP_HOST", "0.0.0.0")
TOKEN = os.environ.get("BBP_TOKEN", "")
TIMEOUT = int(os.environ.get("BBP_TIMEOUT", "120"))


def run_exe(args, cwd):
    """Chạy engine, trả (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            [str(EXE)] + args,
            capture_output=True, text=True, cwd=str(cwd), timeout=TIMEOUT,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"engine quá thời gian ({TIMEOUT}s)"
    except Exception as e:  # noqa
        return -1, "", str(e)


# --------------------------------------------------------------------------- #
# Kho lưu trữ giải đấu (server-side, an toàn đồng thời)
# --------------------------------------------------------------------------- #

class TournamentStore:
    """Lưu mỗi giải thành một file JSON, với khóa cho các thao tác đọc-ghi."""

    def __init__(self, data_dir):
        self.dir = pathlib.Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, tid):
        # Chỉ chấp nhận id an toàn (chống path traversal).
        if not tid or not all(c.isalnum() or c in "-_" for c in tid):
            raise ValueError("id giải không hợp lệ")
        return self.dir / f"{tid}.json"

    def list(self):
        with self._lock:
            out = []
            for p in sorted(self.dir.glob("*.json")):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                except Exception:  # noqa
                    continue
                st = d.get("state", {})
                out.append({
                    "id": d.get("id", p.stem),
                    "name": st.get("name") or d.get("name") or p.stem,
                    "updatedAt": d.get("updatedAt", 0),
                    "version": d.get("version", 0),
                    "players": len(st.get("players", [])),
                    "totalRounds": st.get("totalRounds", 0),
                    "playedRounds": len(st.get("results", [])),
                    "nTeams": st.get("nTeams", 0),
                })
            out.sort(key=lambda x: x["updatedAt"], reverse=True)
            return out

    def create(self, name, state):
        with self._lock:
            tid = uuid.uuid4().hex[:12]
            state = dict(state or {})
            state["name"] = name or state.get("name") or "Giải mới"
            rec = {"id": tid, "state": state, "version": 1,
                   "updatedAt": time.time()}
            self._path(tid).write_text(
                json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            return rec

    def load(self, tid):
        with self._lock:
            p = self._path(tid)
            if not p.exists():
                return None
            return json.loads(p.read_text(encoding="utf-8"))

    def save(self, tid, state, base_version):
        """Ghi có kiểm tra phiên bản. Trả (rec, None) hoặc (None, current_rec)
        nếu xung đột phiên bản."""
        with self._lock:
            p = self._path(tid)
            if not p.exists():
                return None, {"error": "not_found"}
            cur = json.loads(p.read_text(encoding="utf-8"))
            if base_version is not None and cur.get("version", 0) != base_version:
                return None, cur  # xung đột: người khác đã ghi trước
            rec = {"id": tid, "state": state,
                   "version": cur.get("version", 0) + 1,
                   "updatedAt": time.time()}
            p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            return rec, None

    def delete(self, tid):
        with self._lock:
            p = self._path(tid)
            if p.exists():
                p.unlink()
                return True
            return False


STORE = TournamentStore(DATA)


# --------------------------------------------------------------------------- #
# Các thao tác engine
# --------------------------------------------------------------------------- #

def pair_from_state(state):
    """Xây TRF từ trạng thái giải, ghép cặp vòng kế, và (nếu có đội) đọc bảng
    xếp hạng đội từ chính engine qua -t. Trả dict kết quả."""
    system = state.get("system", "--dutch")
    trf = trfbuild.build_trf(state)
    has_teams = bool([t for t in state.get("teams", []) if t.get("members")])
    with tempfile.TemporaryDirectory() as d:
        dd = pathlib.Path(d)
        (dd / "t.trf").write_text(trf, encoding="utf-8", newline="")
        args = [system, "t.trf", "-p"]
        if has_teams:
            args += ["-t", "teams.txt"]
        code, out, err = run_exe(args, dd)
        run_exe([system, "t.trf", "-c", "-l", "chk.txt"], dd)
        chk = dd / "chk.txt"
        checklist = chk.read_text(encoding="utf-8") if chk.exists() else ""
        team_standings = ""
        tp = dd / "teams.txt"
        if has_teams and tp.exists():
            team_standings = tp.read_text(encoding="utf-8")
    return {
        "code": code, "pairing": out, "checklist": checklist, "trf": trf,
        "teamStandings": team_standings,
        "round": len(state.get("results", [])) + 1, "stderr": err,
    }


def api_version():
    _, out, _ = run_exe([], ROOT)
    return {"version": out.strip()}


def api_pair(body, checker=False):
    system = body.get("system", "--dutch")
    trf = body.get("trf", "")
    with tempfile.TemporaryDirectory() as d:
        dd = pathlib.Path(d)
        (dd / "t.trf").write_text(trf, encoding="utf-8", newline="")
        if checker:
            code, out, err = run_exe([system, "t.trf", "-c", "-l", "chk.txt"], dd)
            chk = dd / "chk.txt"
            checklist = chk.read_text(encoding="utf-8") if chk.exists() else ""
            return {"code": code, "pairing": "", "checklist": checklist, "stderr": err}
        code, out, err = run_exe([system, "t.trf", "-p"], dd)
        run_exe([system, "t.trf", "-c", "-l", "chk.txt"], dd)
        chk = dd / "chk.txt"
        checklist = chk.read_text(encoding="utf-8") if chk.exists() else ""
        return {"code": code, "pairing": out, "checklist": checklist, "stderr": err}


def api_generate(body):
    system = body.get("system", "--dutch")
    lines = [
        f"PlayersNumber={int(body.get('players', 8))}",
        f"RoundsNumber={int(body.get('rounds', 5))}",
        f"HighestRating={int(body.get('hi', 2400))}",
        f"LowestRating={int(body.get('lo', 1600))}",
        f"DrawPercentage={int(body.get('draw', 30))}",
    ]
    seed = int(body.get("seed", 42))
    with tempfile.TemporaryDirectory() as d:
        dd = pathlib.Path(d)
        (dd / "cfg.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        code, out, err = run_exe(
            [system, "-g", "cfg.txt", "-o", "out.trf", "-s", str(seed)], dd)
        of = dd / "out.trf"
        trf = of.read_text(encoding="utf-8") if of.exists() else ""
    return {"code": code, "trf": trf, "stderr": err}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "bbpPairingsUI/2.0"

    # -- tiện ích --
    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        if not TOKEN:
            return True
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        return (q.get("token", [""])[0] == TOKEN
                or self.headers.get("X-Token", "") == TOKEN)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _route(self):
        from urllib.parse import urlparse
        return urlparse(self.path).path

    # -- GET --
    def do_GET(self):
        path = self._route()
        if path in ("/", "/index.html"):
            html = (WEB / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        try:
            if path == "/api/version":
                return self._json(api_version())
            if path == "/api/tournaments":
                return self._json({"tournaments": STORE.list()})
            if path.startswith("/api/tournaments/"):
                tid = path.rsplit("/", 1)[-1]
                rec = STORE.load(tid)
                if rec is None:
                    return self._json({"error": "not_found"}, 404)
                return self._json(rec)
            self.send_error(404)
        except Exception as e:  # noqa
            self._json({"error": str(e)}, 500)

    # -- POST/PUT/DELETE --
    def do_POST(self):
        path = self._route()
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        try:
            body = self._body()
            if path == "/api/pair":
                return self._json(api_pair(body))
            if path == "/api/check":
                return self._json(api_pair(body, checker=True))
            if path == "/api/generate":
                return self._json(api_generate(body))
            if path == "/api/pair_state":
                return self._json(pair_from_state(body))
            if path == "/api/tournaments":
                rec = STORE.create(body.get("name", ""), body.get("state", {}))
                return self._json(rec, 201)
            if path.endswith("/pair") and path.startswith("/api/tournaments/"):
                tid = path[len("/api/tournaments/"):-len("/pair")]
                rec = STORE.load(tid)
                if rec is None:
                    return self._json({"error": "not_found"}, 404)
                return self._json(pair_from_state(rec.get("state", {})))
            self.send_error(404)
        except Exception as e:  # noqa
            self._json({"error": str(e)}, 500)

    def do_PUT(self):
        path = self._route()
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        try:
            body = self._body()
            if path.startswith("/api/tournaments/"):
                tid = path.rsplit("/", 1)[-1]
                rec, conflict = STORE.save(
                    tid, body.get("state", {}), body.get("version"))
                if conflict is not None:
                    if conflict.get("error") == "not_found":
                        return self._json({"error": "not_found"}, 404)
                    return self._json({"error": "conflict", "current": conflict}, 409)
                return self._json(rec)
            self.send_error(404)
        except Exception as e:  # noqa
            self._json({"error": str(e)}, 500)

    def do_DELETE(self):
        path = self._route()
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        try:
            if path.startswith("/api/tournaments/"):
                tid = path.rsplit("/", 1)[-1]
                return self._json({"deleted": STORE.delete(tid)})
            self.send_error(404)
        except Exception as e:  # noqa
            self._json({"error": str(e)}, 500)

    def log_message(self, fmt, *args):  # log gọn (tắt khi BBP_QUIET)
        if os.environ.get("BBP_QUIET"):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _lan_ips():
    ips = []
    try:
        import socket
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if "." in ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:  # noqa
        pass
    return ips


if __name__ == "__main__":
    if not EXE.exists():
        print(f"KHÔNG tìm thấy engine tại {EXE} — hãy build trước "
              f"(make static=yes) hoặc đặt biến BBP_EXE.", file=sys.stderr)
        sys.exit(1)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"BBP Pairings UI đang chạy (đa luồng, LAN):")
    print(f"  • Trên máy chủ:  http://localhost:{PORT}")
    for ip in _lan_ips():
        print(f"  • Trong mạng LAN: http://{ip}:{PORT}")
    print(f"  engine: {EXE}")
    print(f"  dữ liệu: {DATA}")
    if TOKEN:
        print("  (bảo vệ bằng BBP_TOKEN)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng.")
