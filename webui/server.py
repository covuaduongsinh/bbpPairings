#!/usr/bin/env python3
"""Giao diện web cục bộ cho bbpPairings — gọi trực tiếp bbpPairings.exe.
Chỉ dùng thư viện chuẩn Python. Chạy:  python webui/server.py
Rồi mở http://localhost:8765
"""
import http.server
import socketserver
import json
import subprocess
import tempfile
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import trfbuild  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = pathlib.Path(__file__).resolve().parent
EXE = ROOT / "bbpPairings.exe"
PORT = 8765


def run_exe(args, cwd):
    """Chạy exe, trả (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            [str(EXE)] + args,
            capture_output=True, text=True, cwd=str(cwd), timeout=60,
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:  # noqa
        return -1, "", str(e)


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
            chk = (dd / "chk.txt")
            checklist = chk.read_text(encoding="utf-8") if chk.exists() else ""
            return {"code": code, "pairing": "", "checklist": checklist, "stderr": err}
        # ghép cặp: pairing ra stdout (không truyền output-file), checklist qua -c
        code, out, err = run_exe([system, "t.trf", "-p"], dd)
        # checklist đầy đủ (chạy riêng chế độ -c, không chặn nếu lỗi)
        c2, cout, cerr = run_exe([system, "t.trf", "-c", "-l", "chk.txt"], dd)
        chk = (dd / "chk.txt")
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


def api_pair_state(body):
    """Ghép cặp vòng kế tiếp từ TRẠNG THÁI giải (kỳ thủ + kết quả từng vòng)."""
    system = body.get("system", "--dutch")
    trf = trfbuild.build_trf(body)
    with tempfile.TemporaryDirectory() as d:
        dd = pathlib.Path(d)
        (dd / "t.trf").write_text(trf, encoding="utf-8", newline="")
        code, out, err = run_exe([system, "t.trf", "-p"], dd)
        run_exe([system, "t.trf", "-c", "-l", "chk.txt"], dd)
        chk = (dd / "chk.txt")
        checklist = chk.read_text(encoding="utf-8") if chk.exists() else ""
    return {
        "code": code, "pairing": out, "checklist": checklist, "trf": trf,
        "round": len(body.get("results", [])) + 1, "stderr": err,
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    def _json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (WEB / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        elif self.path == "/api/version":
            self._json(api_version())
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        try:
            if self.path == "/api/pair":
                self._json(api_pair(body))
            elif self.path == "/api/check":
                self._json(api_pair(body, checker=True))
            elif self.path == "/api/generate":
                self._json(api_generate(body))
            elif self.path == "/api/pair_state":
                self._json(api_pair_state(body))
            else:
                self.send_error(404)
        except Exception as e:  # noqa
            self._json({"code": -1, "error": str(e)}, 500)

    def log_message(self, *a):  # yên lặng
        pass


if __name__ == "__main__":
    if not EXE.exists():
        print(f"KHÔNG tìm thấy {EXE} — hãy build trước.", file=sys.stderr)
        sys.exit(1)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"BBP Pairings UI  ->  http://localhost:{PORT}")
        print(f"engine: {EXE}")
        httpd.serve_forever()
