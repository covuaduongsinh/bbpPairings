"""Tạo file TRF chuẩn cột từ trạng thái giải đấu, để ghép cặp từ vòng 1.

Cột (0-indexed) suy ra từ file TRF thật:
  001 [0:3] | id [4:8] | name [14:47] | rating [48:52] | score [80:84] |
  rank [85:89] | vòng thứ k bắt đầu ở cột 91, mỗi vòng rộng 10:
      opp[+0:+4] ' ' color[+5] ' ' result[+7] '  '
"""


def _fmt_score(x: float) -> str:
    # 1 chữ số thập phân, ví dụ 0.0 / 0.5 / 2.0 / 10.5
    return f"{x:.1f}"


def _round_entry(opp: str, color: str, result: str) -> str:
    # đúng 10 ký tự: opp(4) space color space result 2-space
    return f"{opp:>4} {color} {result}  "


def _team_line(name: str, member_ids) -> str:
    # Dòng 013 (khai báo đội) khớp bố cục cột engine đọc:
    #   "013" [0:3] | space [3] | tên đội rộng 32 [4:36] |
    #   id 4 chữ số theo bước 5 ký tự từ cột 36 (id + 1 space phân tách)
    nm = (str(name) or "Team")[:32]
    line = "013 " + nm.ljust(32)
    for mid in member_ids:
        line += f"{int(mid):>4} "
    return line.rstrip()


def _bye_line(round_no: int, ids) -> str:
    # Dòng 240 (bye yêu cầu) — dùng để loại kỳ thủ đã bỏ giải khỏi vòng đang
    # ghép. Bố cục: "240" [0:3] | vòng rộng 3 ở cột 6-8 | id 4 chữ số theo bước
    # 5 ký tự từ cột 10. Engine gán bye tự thân (0 điểm, không bắt cặp).
    line = "240   " + f"{int(round_no):>3}"
    for pid in ids:
        line += f" {int(pid):>4}"
    return line


def build_trf(state: dict) -> str:
    name = state.get("name", "Giai co vua")
    total = int(state.get("totalRounds", 5))
    initial = state.get("initialColor", "white1")  # white1 | black1
    players = state.get("players", [])
    results = state.get("results", [])  # danh sách vòng đã đá

    # entries[pid][round_1based] = (opp, color, result). Lập chỉ số theo SỐ VÒNG
    # (không phải theo thứ tự) để một kỳ thủ bỏ lỡ vòng giữa (vd bye nửa điểm)
    # rồi đá lại vẫn giữ đúng cột: các vòng bỏ lỡ được chèn ô trống.
    entries = {int(p["id"]): {} for p in players}
    scores = {int(p["id"]): 0.0 for p in players}

    for ri, rnd in enumerate(results, start=1):
        for b in rnd.get("boards", []):
            w = int(b["white"]); bl = int(b["black"]); r = b.get("w", "=")
            entries[w][ri] = (f"{bl:04d}", "w", r)
            br = {"1": "0", "0": "1", "=": "="}.get(r, "=")
            entries[bl][ri] = (f"{w:04d}", "b", br)
            scores[w] += {"1": 1.0, "0": 0.0, "=": 0.5}.get(r, 0.5)
            scores[bl] += {"1": 1.0, "0": 0.0, "=": 0.5}.get(br, 0.5)
        bye = rnd.get("bye")
        if bye is not None:
            bye = int(bye)
            entries[bye][ri] = ("0000", "-", "U")  # bye trọn điểm
            scores[bye] += 1.0

    lines = [f"012 {name}"]
    for p in sorted(players, key=lambda x: int(x["id"])):
        pid = int(p["id"])
        buf = [" "] * 91  # cột 0..90; vòng đầu tiên bắt đầu ở cột 91
        buf[0:3] = list("001")
        s_id = f"{pid:>4}"; buf[4:8] = list(s_id)
        nm = (str(p.get("name", "")) or f"KT{pid}")[:33]
        buf[14:14 + len(nm)] = list(nm)
        rt = f"{int(p.get('rating', 0)):>4}"; buf[48:52] = list(rt[-4:])
        sc = f"{_fmt_score(scores[pid]):>4}"; buf[80:84] = list(sc[-4:])
        rk = f"{int(p.get('rank', pid)):>4}"; buf[85:89] = list(rk[-4:])
        line = "".join(buf)  # luôn giữ đủ 89 cột (engine yêu cầu >= 84)
        pe = entries[pid]
        last = max(pe) if pe else 0
        for k in range(1, last + 1):  # tới vòng cuối có ván; không có đuôi trống
            e = pe.get(k)
            line += _round_entry(*e) if e else " " * 10  # vòng bỏ lỡ = ô trống
        lines.append(line)
    lines.append(f"XXR {total}")
    lines.append(f"XXC {initial}")
    # Đội (013): mỗi đội gồm danh sách id thành viên. Engine sẽ cấm các thành
    # viên cùng đội gặp nhau ở mọi vòng.
    for t in state.get("teams", []):
        members = [m for m in t.get("members", []) if m]
        if members:
            lines.append(_team_line(t.get("name", "Team"), members))
    # Kỳ thủ đã bỏ giải: yêu cầu bye (240) cho vòng sắp ghép để engine không
    # bắt cặp họ nữa. Điểm của họ được giữ nguyên (bye 0 điểm).
    withdrawn = [int(w) for w in state.get("withdrawn", []) if w]
    if withdrawn:
        next_round = len(results) + 1
        lines.append(_bye_line(next_round, sorted(set(withdrawn))))
    return "\n".join(lines) + "\n"
