"""Kho lưu giải đấu trên Upstash Redis (REST) — bản thay thế TournamentStore
dùng cho môi trường serverless (Vercel), nơi không có đĩa bền.

Chỉ dùng thư viện chuẩn (urllib) nên không cần thêm dependency pip. Cùng
interface với TournamentStore (list/create/load/save/delete) nên lớp Handler
trong server.py dùng lại nguyên vẹn.

Ghi có kiểm tra phiên bản (optimistic locking) được thực hiện NGUYÊN TỬ bằng
một script Lua (EVAL): giữa các lần gọi serverless, khóa trong tiến trình vô
nghĩa, nên compare-and-set ở phía Redis mới bảo đảm hai người không ghi đè nhau.

Biến môi trường (Vercel tích hợp Upstash sẽ tự đặt một trong hai cặp):
    KV_REST_API_URL / KV_REST_API_TOKEN            (tên kiểu Vercel KV)
    UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
"""
import json
import os
import time
import urllib.request
import uuid

KEY_PREFIX = "bbp:t:"
INDEX_KEY = "bbp:index"

# Compare-and-set: chỉ ghi khi version khớp; trả bản hiện tại nếu lệch.
_CAS_LUA = """
local cur = redis.call('GET', KEYS[1])
if not cur then return 'NF' end
local rec = cjson.decode(cur)
if ARGV[1] ~= '' and tonumber(ARGV[1]) ~= tonumber(rec.version) then
  return 'CF:' .. cur
end
local nr = cjson.decode(ARGV[2])
nr.version = (tonumber(rec.version) or 0) + 1
local out = cjson.encode(nr)
redis.call('SET', KEYS[1], out)
return 'OK:' .. out
"""


def credentials():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get(
        "UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get(
        "UPSTASH_REDIS_REST_TOKEN")
    return url, token


class KVStore:
    def __init__(self, url=None, token=None, timeout=15):
        if url is None or token is None:
            u, t = credentials()
            url = url or u
            token = token or t
        if not url or not token:
            raise RuntimeError(
                "Thiếu cấu hình Upstash (KV_REST_API_URL / KV_REST_API_TOKEN).")
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # -- giao thức REST của Upstash --
    def _cmd(self, *args):
        body = json.dumps([str(a) for a in args]).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as f:
            d = json.loads(f.read().decode("utf-8"))
        if isinstance(d, dict) and d.get("error"):
            raise RuntimeError("Upstash error: " + str(d["error"]))
        return d.get("result") if isinstance(d, dict) else d

    @staticmethod
    def _valid(tid):
        return bool(tid) and all(c.isalnum() or c in "-_" for c in tid)

    def _key(self, tid):
        if not self._valid(tid):
            raise ValueError("id giải không hợp lệ")
        return KEY_PREFIX + tid

    @staticmethod
    def _summary(rec):
        st = rec.get("state", {})
        return {
            "id": rec.get("id"),
            "name": st.get("name") or rec.get("name") or rec.get("id"),
            "updatedAt": rec.get("updatedAt", 0),
            "version": rec.get("version", 0),
            "players": len(st.get("players", [])),
            "totalRounds": st.get("totalRounds", 0),
            "playedRounds": len(st.get("results", [])),
            "nTeams": st.get("nTeams", 0),
        }

    # -- interface giống TournamentStore --
    def list(self):
        ids = self._cmd("SMEMBERS", INDEX_KEY) or []
        if not ids:
            return []
        keys = [KEY_PREFIX + i for i in ids]
        vals = self._cmd("MGET", *keys) or []
        out = []
        for raw in vals:
            if not raw:
                continue
            try:
                out.append(self._summary(json.loads(raw)))
            except Exception:  # noqa
                continue
        out.sort(key=lambda x: x["updatedAt"], reverse=True)
        return out

    def create(self, name, state):
        tid = uuid.uuid4().hex[:12]
        state = dict(state or {})
        state["name"] = name or state.get("name") or "Giải mới"
        rec = {"id": tid, "state": state, "version": 1,
               "updatedAt": time.time()}
        self._cmd("SET", self._key(tid), json.dumps(rec, ensure_ascii=False))
        self._cmd("SADD", INDEX_KEY, tid)
        return rec

    def load(self, tid):
        raw = self._cmd("GET", self._key(tid))
        return json.loads(raw) if raw else None

    def save(self, tid, state, base_version):
        candidate = {"id": tid, "state": state, "version": 0,
                     "updatedAt": time.time()}
        bv = "" if base_version is None else str(base_version)
        res = self._cmd(
            "EVAL", _CAS_LUA, "1", self._key(tid),
            bv, json.dumps(candidate, ensure_ascii=False))
        if res == "NF":
            return None, {"error": "not_found"}
        if isinstance(res, str) and res.startswith("CF:"):
            return None, json.loads(res[3:])
        if isinstance(res, str) and res.startswith("OK:"):
            return json.loads(res[3:]), None
        raise RuntimeError("Kết quả CAS bất ngờ: " + repr(res))

    def delete(self, tid):
        n = self._cmd("DEL", self._key(tid))
        self._cmd("SREM", INDEX_KEY, tid)
        return bool(n)
