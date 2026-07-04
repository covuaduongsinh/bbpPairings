#!/usr/bin/env python3
"""Kiểm thử KVStore (Upstash Redis REST) không cần Upstash thật.

Dựng một mock REST Upstash trong bộ nhớ (đủ các lệnh KVStore dùng, kể cả CAS
qua EVAL) rồi chạy trọn vòng đời create/load/save/409/delete/list. Xác nhận
logic khóa lạc quan và interface khớp TournamentStore.

    python webui/kv_test.py
"""
import json
import pathlib
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import store_kv  # noqa: E402

# Kho khóa-giá trị trong bộ nhớ cho mock (strings + sets).
_KV = {}
_SETS = {}


def _exec(cmd):
    op = cmd[0].upper()
    a = cmd[1:]
    if op == "SET":
        _KV[a[0]] = a[1]
        return "OK"
    if op == "GET":
        return _KV.get(a[0])
    if op == "DEL":
        n = 0
        for k in a:
            if k in _KV:
                del _KV[k]
                n += 1
        return n
    if op == "MGET":
        return [_KV.get(k) for k in a]
    if op == "SADD":
        s = _SETS.setdefault(a[0], set())
        before = len(s)
        s.update(a[1:])
        return len(s) - before
    if op == "SREM":
        s = _SETS.get(a[0], set())
        n = 0
        for m in a[1:]:
            if m in s:
                s.discard(m)
                n += 1
        return n
    if op == "SMEMBERS":
        return sorted(_SETS.get(a[0], set()))
    if op == "EVAL":
        # a = [script, numkeys, key, base_version, candidate_json]
        key, bv, cand = a[2], a[3], a[4]
        cur = _KV.get(key)
        if not cur:
            return "NF"
        rec = json.loads(cur)
        if bv != "" and float(bv) != float(rec["version"]):
            return "CF:" + cur
        nr = json.loads(cand)
        nr["version"] = int(rec["version"]) + 1
        out = json.dumps(nr, ensure_ascii=False)
        _KV[key] = out
        return "OK:" + out
    raise ValueError("mock: lệnh chưa hỗ trợ: " + op)


class MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        cmd = json.loads(self.rfile.read(n) or b"[]")
        try:
            result = _exec(cmd)
            body = json.dumps({"result": result}).encode("utf-8")
        except Exception as e:  # noqa
            body = json.dumps({"error": str(e)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    port = free_port()
    httpd = HTTPServer(("127.0.0.1", port), MockHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    store = store_kv.KVStore(url=f"http://127.0.0.1:{port}", token="test")

    failures = []

    def check(name, cond, detail=""):
        if cond:
            print(f"  [ok]   {name}")
        else:
            failures.append(name)
            print(f"  [FAIL] {name}: {detail}")

    try:
        check("list empty initially", store.list() == [])

        rec = store.create("Giai KV", {"name": "Giai KV", "totalRounds": 3,
                                       "players": [{"id": 1}], "results": []})
        tid = rec["id"]
        check("create returns v1", rec["version"] == 1 and bool(tid))

        loaded = store.load(tid)
        check("load returns state", loaded["state"]["name"] == "Giai KV")

        lst = store.list()
        check("list shows one", len(lst) == 1 and lst[0]["id"] == tid
              and lst[0]["playedRounds"] == 0)

        rec2, conf = store.save(tid, {"name": "Giai KV", "totalRounds": 3,
                                      "players": [{"id": 1}],
                                      "results": [{"boards": [], "bye": 1}]},
                                base_version=1)
        check("save v1 -> v2", conf is None and rec2["version"] == 2)
        check("save persisted results",
              store.load(tid)["state"]["results"] and True)

        rec3, conf3 = store.save(tid, {"x": 1}, base_version=1)  # stale
        check("stale save -> conflict (409-equivalent)",
              rec3 is None and conf3 is not None
              and conf3.get("version") == 2)

        nf, nfc = store.save("khong-ton-tai", {"x": 1}, base_version=1)
        check("save missing -> not_found",
              nf is None and nfc.get("error") == "not_found")

        check("delete returns True", store.delete(tid) is True)
        check("list empty after delete", store.list() == [])
    finally:
        httpd.shutdown()

    print(f"\nKVStore test: {'PASS' if not failures else 'FAIL'} "
          f"({len(failures)} lỗi)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
