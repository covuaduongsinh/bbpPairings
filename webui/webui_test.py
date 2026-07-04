#!/usr/bin/env python3
"""Integration test cho máy chủ webui: khởi động server thật trong một luồng
nền, rồi lái trọn một giải đội qua HTTP đúng như frontend làm, và kiểm tra
lưu trữ server-side + optimistic locking + ràng buộc cùng đội.

    python webui/webui_test.py                 # dùng ../bbpPairings.exe
    BBP_EXE=/path/to/exe python webui/webui_test.py

Trả mã 0 nếu mọi kiểm tra đạt, 1 nếu có lỗi, 2 nếu thiếu môi trường.
"""
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Client:
    def __init__(self, base):
        self.base = base

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as f:
            return f.status, json.loads(f.read().decode("utf-8"))


def parse_pairing(txt):
    lines = [l for l in (txt or "").strip().splitlines() if l.strip()]
    boards, bye = [], None
    for ln in lines[1:]:
        a, b = (int(x) for x in ln.split())
        if b == 0:
            bye = a
        else:
            boards.append((a, b))
    return boards, bye


def main():
    exe = pathlib.Path(os.environ.get("BBP_EXE", str(ROOT / "bbpPairings.exe")))
    if not exe.exists():
        print(f"Không tìm thấy engine {exe} (build static=yes trước).",
              file=sys.stderr)
        return 2

    port = free_port()
    tmp = tempfile.TemporaryDirectory()
    os.environ["BBP_EXE"] = str(exe)
    os.environ["BBP_DATA"] = tmp.name
    os.environ["BBP_HOST"] = "127.0.0.1"
    os.environ["BBP_PORT"] = str(port)
    os.environ["BBP_QUIET"] = "1"
    # import sau khi đặt biến môi trường để server đọc đúng cấu hình
    sys.path.insert(0, str(HERE))
    import server  # noqa
    # BBP_TEST_STORE=kv → dùng KVStore trên một mock Upstash trong tiến trình
    # (cùng đường mã như bản Vercel); mặc định dùng file store (bản local).
    if os.environ.get("BBP_TEST_STORE") == "kv":
        import kv_test
        import store_kv
        from http.server import HTTPServer
        mock_port = free_port()
        mock = HTTPServer(("127.0.0.1", mock_port), kv_test.MockHandler)
        threading.Thread(target=mock.serve_forever, daemon=True).start()
        server.STORE = store_kv.KVStore(
            url=f"http://127.0.0.1:{mock_port}", token="test")
    else:
        server.STORE = server.TournamentStore(server.DATA)

    httpd = server.ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    c = Client(f"http://127.0.0.1:{port}")

    failures = []

    def check(name, cond, detail=""):
        if cond:
            print(f"  [ok]   {name}")
        else:
            failures.append(name)
            print(f"  [FAIL] {name}: {detail}")

    try:
        # 1) version
        _, v = c.call("GET", "/api/version")
        check("version endpoint", "BBP Pairings" in v.get("version", ""), v)

        # 2) tạo giải đội (3 đội, 6 kỳ thủ, 3 vòng)
        teams_of = {1: 1, 4: 1, 2: 2, 5: 2, 3: 3, 6: 3}
        players = [{"id": i, "name": f"P{i}", "rating": 2600 - i * 10,
                    "team": teams_of[i]} for i in range(1, 7)]
        state = {"system": "--dutch", "name": "Giai doi test", "totalRounds": 3,
                 "initialColor": "white1", "nTeams": 3,
                 "teamNames": ["Alpha", "Beta", "Gamma"], "players": players,
                 "results": [],
                 "teams": [{"name": "Alpha", "members": [1, 4]},
                           {"name": "Beta", "members": [2, 5]},
                           {"name": "Gamma", "members": [3, 6]}]}
        _, rec = c.call("POST", "/api/tournaments",
                        {"name": state["name"], "state": state})
        tid, version = rec["id"], rec["version"]
        check("create tournament", bool(tid) and version == 1, rec)

        # 3) chơi trọn giải: ghép -> nhập kết quả -> lưu -> ghép tiếp
        import random
        rng = random.Random(12345)
        results = []
        last_teams = ""
        for rnd in range(1, 4):
            _, d = c.call("POST", "/api/pair_state", {**state, "results": results})
            check(f"round {rnd} paired (code 0)", d["code"] == 0, d.get("stderr"))
            if d["code"] != 0:
                break
            boards, bye = parse_pairing(d["pairing"])
            # KHÔNG có cặp cùng đội
            same = [(a, b) for (a, b) in boards if teams_of[a] == teams_of[b]]
            check(f"round {rnd} no teammates", not same, same)
            last_teams = d.get("teamStandings", "")
            # nhập kết quả ngẫu nhiên và lưu
            rboards = [{"white": a, "black": b,
                        "w": rng.choice(["1", "0", "="])} for (a, b) in boards]
            results.append({"boards": rboards, "bye": bye})
            state["results"] = results
            _, saved = c.call("PUT", f"/api/tournaments/{tid}",
                              {"state": state, "version": version})
            version = saved["version"]
        check("all rounds saved (version advanced)", version == 4,
              f"version={version}")

        # 3b) kỳ thủ bỏ giải: sau khi rút, không được bắt cặp ở vòng kế
        wd_state = {"system": "--dutch", "totalRounds": 4, "initialColor": "white1",
                    "players": [{"id": i, "name": f"P{i}", "rating": 2600 - i * 10}
                                for i in range(1, 7)],
                    "results": [{"boards": [{"white": 1, "black": 4, "w": "1"},
                                            {"white": 2, "black": 5, "w": "1"},
                                            {"white": 3, "black": 6, "w": "="}],
                                 "bye": None}],
                    "withdrawn": [3]}
        _, wd = c.call("POST", "/api/pair_state", wd_state)
        paired = set()
        for ln in (wd.get("pairing") or "").strip().splitlines()[1:]:
            a, b = (int(x) for x in ln.split())
            paired.add(a)
            if b:
                paired.add(b)
        check("withdrawn player excluded from pairing",
              wd["code"] == 0 and 3 not in paired, f"paired={sorted(paired)}")

        # 4) bảng đội từ engine có cột tiebreak (4 trường: rank,total,tb,name,..)
        rows = [ln for ln in last_teams.strip().splitlines()[1:] if ln.strip()]
        ok_cols = all(len(r.split("\t")) >= 4 for r in rows) and len(rows) == 3
        check("engine team standings has tiebreak column", ok_cols, last_teams)

        # 5) tải lại từ máy chủ giữ nguyên trạng thái
        _, full = c.call("GET", f"/api/tournaments/{tid}")
        check("reload preserves rounds",
              len(full["state"]["results"]) == 3, full["state"].get("results"))

        # 6) optimistic locking: ghi với phiên bản cũ -> 409
        conflict = False
        try:
            c.call("PUT", f"/api/tournaments/{tid}", {"state": state, "version": 1})
        except urllib.error.HTTPError as e:
            conflict = (e.code == 409)
        check("stale save rejected (409)", conflict)

        # 7) list + delete
        _, lst = c.call("GET", "/api/tournaments")
        check("list shows tournament",
              any(t["id"] == tid for t in lst["tournaments"]), lst)
        _, dele = c.call("DELETE", f"/api/tournaments/{tid}")
        check("delete tournament", dele.get("deleted") is True, dele)

        # 8) nhập TRF: dựng TRF từ một state rồi nhập lại, kiểm tra tái tạo
        import trfbuild
        src = {"name": "Import src", "totalRounds": 4, "initialColor": "white1",
               "players": [{"id": i, "name": f"Q{i}", "rating": 2500 - i * 10}
                           for i in range(1, 5)],
               "results": [{"boards": [{"white": 1, "black": 3, "w": "1"},
                                       {"white": 2, "black": 4, "w": "="}],
                            "bye": None}]}
        trf = trfbuild.build_trf(src)
        _, irec = c.call("POST", "/api/import/trf", {"trf": trf, "name": "Nhap"})
        _, ifull = c.call("GET", f"/api/tournaments/{irec['id']}")
        ist = ifull["state"]
        check("TRF import reconstructs players/rounds",
              len(ist["players"]) == 4 and len(ist["results"]) == 1
              and ist["results"][0]["boards"][0]["white"] == 1,
              ist.get("results"))
        c.call("DELETE", f"/api/tournaments/{irec['id']}")
    finally:
        httpd.shutdown()
        tmp.cleanup()

    print(f"\nWebUI integration: {'PASS' if not failures else 'FAIL'} "
          f"({len(failures)} lỗi)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
