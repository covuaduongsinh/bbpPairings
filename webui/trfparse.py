"""Đọc một file TRF thành trạng thái giải của webui (đảo ngược của trfbuild).

Dùng để NHẬP một giải đã có (từ phần mềm khác hoặc bản sao lưu TRF) vào giao
diện web. Đây là chuyển đổi "best-effort" cho mô hình đơn giản của webui (kết
quả 1/½/0 mỗi bàn, bye trọn điểm): ván thực đấu và bye trọn điểm được tái tạo
đầy đủ; xử thua/forfeit được quy về thắng/thua; các loại bye đặc biệt (nửa
điểm, không điểm) được bỏ qua ở phần tái tạo kết quả.
"""

FIRST_ROUND_COL = 91
ROUND_WIDTH = 10

_WHITE_FROM = {"1": "1", "W": "1", "+": "1",
               "0": "0", "L": "0", "-": "0",
               "=": "=", "D": "=", "H": "="}


def _round_entry(line, k):
    base = FIRST_ROUND_COL + (k - 1) * ROUND_WIDTH
    if base + 8 > len(line):
        return None
    opp, color, result = line[base:base + 4], line[base + 5], line[base + 7]
    if opp == "    " and color == " " and result == " ":
        return None
    return opp, color, result.upper()


def _invert(res):
    return {"1": "0", "0": "1", "=": "="}.get(res, "=")


def trf_to_state(text, name=None, system="--dutch"):
    """Trả về dict state dùng được cho trfbuild.build_trf / webui."""
    players = {}       # id -> {name, rating, rounds:{k:(opp,color,result)}}
    teams = []
    total_rounds = 0
    initial = "white1"
    max_k = 0

    for raw in text.replace("\r", "\n").split("\n"):
        if raw.startswith("001") and len(raw) >= 84:
            pid = int(raw[4:8])
            pname = raw[14:47].strip() or f"KT{pid}"
            rstr = raw[48:52].strip()
            rating = int(rstr) if rstr.isdigit() else 0
            rounds = {}
            k = 1
            while FIRST_ROUND_COL + (k - 1) * ROUND_WIDTH + 8 <= len(raw):
                e = _round_entry(raw, k)
                if e is not None:
                    opp_s, color_c, result_c = e
                    opp = None
                    if opp_s not in ("    ", "0000"):
                        try:
                            opp = int(opp_s)
                        except ValueError:
                            opp = None
                    color = ("w" if color_c == "w"
                             else "b" if color_c == "b" else None)
                    rounds[k] = (opp, color, result_c)
                    max_k = max(max_k, k)
                k += 1
            players[pid] = {"name": pname, "rating": rating, "rounds": rounds}
        elif raw.startswith("013"):
            tname = raw[4:36].strip()
            members = []
            i = 36
            while i + 4 <= len(raw):
                tok = raw[i:i + 4].strip()
                if tok.isdigit():
                    members.append(int(tok))
                i += 5
            if members:
                teams.append({"name": tname or f"Team {len(teams)+1}",
                              "members": members})
        elif raw.startswith("XXR") or raw.startswith("142"):
            tok = raw[3:].strip().split()
            if tok and tok[0].isdigit():
                total_rounds = int(tok[0])
        elif raw.startswith("XXC"):
            v = raw[3:].strip().lower()
            if v.startswith("black") or v == "b" or v == "black1":
                initial = "black1"
            elif v.startswith("white") or v == "w" or v == "white1":
                initial = "white1"

    # Tái tạo kết quả theo từng vòng từ lịch sử của từng kỳ thủ.
    results = []
    for k in range(1, max_k + 1):
        boards, bye, seen = [], None, set()
        for pid in sorted(players):
            if pid in seen:
                continue
            r = players[pid]["rounds"].get(k)
            if r is None:
                continue
            opp, color, result = r
            if opp is None:
                # bye/không đá: chỉ coi là bye trọn điểm khi kết quả là thắng
                if result in ("U", "F", "1", "W", "+"):
                    bye = pid
                seen.add(pid)
                continue
            if opp in seen or opp not in players:
                seen.add(pid)
                continue
            if color == "w":
                w, b, res = pid, opp, _WHITE_FROM.get(result, "=")
            elif color == "b":
                w, b, res = opp, pid, _invert(_WHITE_FROM.get(result, "="))
            else:
                seen.add(pid)
                continue
            boards.append({"white": w, "black": b, "w": res})
            seen.add(pid)
            seen.add(opp)
        results.append({"boards": boards, "bye": bye})

    return {
        "system": system,
        "name": name or "Giải nhập từ TRF",
        "totalRounds": total_rounds or max_k or 1,
        "initialColor": initial,
        "nTeams": len(teams),
        "teamNames": [t["name"] for t in teams],
        "players": [{"id": pid, "name": players[pid]["name"],
                     "rating": players[pid]["rating"],
                     "team": next((ti + 1 for ti, t in enumerate(teams)
                                   if pid in t["members"]), 0)}
                    for pid in sorted(players)],
        "results": results,
        "teams": teams,
        "withdrawn": [],
    }
