#!/usr/bin/env python3
"""Đối chiếu chéo bbpPairings với JaVaFo (bản tham chiếu FIDE cho hệ Dutch).

Đây là kiểm chứng "gold standard": sinh nhiều giải bằng bbpPairings, rồi với mỗi
vòng, yêu cầu CẢ HAI engine ghép cặp cùng một trạng thái và so sánh. Các khác
biệt được báo cáo để rà soát — chúng KHÔNG tự động là lỗi, vì bbpPairings cài
đặt luật Dutch 2025 còn JaVaFo 1.4 cài đặt phiên bản cũ hơn; các điểm phân kỳ
đã biết được liệt kê trong README. Công cụ này để phát hiện phân kỳ, không phải
để khẳng định trùng khớp tuyệt đối.

Cần biến môi trường hoặc tham số trỏ tới JaVaFo jar; nếu không có Java hoặc jar,
công cụ BỎ QUA MỀM (in thông báo, trả 0) để không làm gãy CI.

    python javafo_compare.py --exe ../bbpPairings.exe --javafo /path/to/javafo.jar
    JAVAFO_JAR=/path/to/javafo.jar python javafo_compare.py
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

# Đầu ra có tiếng Việt; bảo đảm UTF-8 trên mọi console (cmd/CI/MSYS).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa
    pass

FIRST_ROUND_COL = 91
ROUND_WIDTH = 10
_PTS = {"1": 1.0, "W": 1.0, "+": 1.0, "U": 1.0, "F": 1.0,
        "=": 0.5, "D": 0.5, "H": 0.5}


def truncate_trf(text, keep, total):
    """Trả về TRF chỉ giữ `keep` vòng đầu, tính lại điểm, và ghi tổng số vòng.

    File do generator sinh ra KHÔNG chứa dòng tổng số vòng, nhưng chế độ ghép
    (-p) đòi hỏi nó; ta thay/thêm một dòng XXR <total> để engine ghép được vòng
    kế (total phải > keep).
    """
    out = []
    for raw in text.replace("\r", "\n").split("\n"):
        if raw.startswith("001") and len(raw) >= 84:
            prefix = raw[:91].ljust(91)
            kept = raw[FIRST_ROUND_COL:FIRST_ROUND_COL + keep * ROUND_WIDTH]
            score = 0.0
            for k in range(keep):
                base = k * ROUND_WIDTH
                res = (kept[base + 7:base + 8] or " ").upper()
                score += _PTS.get(res, 0.0)
            sc = f"{score:.1f}".rjust(4)[-4:]
            line = (prefix[:80] + sc + prefix[84:91] + kept).rstrip()
            out.append(line)
        elif raw.startswith("142") or raw.startswith("XXR"):
            continue                      # thay bằng dòng của ta
        elif raw.strip():
            out.append(raw.rstrip())
    out.append(f"XXR {total}")
    return "\n".join(out) + "\n"


def parse_pairing(txt):
    """Trả về (set các cặp không xét màu, người được bye)."""
    lines = [l for l in (txt or "").strip().splitlines() if l.strip()]
    pairs, bye = set(), None
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) < 2:
            continue
        a, b = int(parts[0]), int(parts[1])
        if b == 0:
            bye = a
        else:
            pairs.add(frozenset((a, b)))
    return pairs, bye


def run(cmd, cwd):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd),
                          timeout=120)


def find_javafo(arg):
    jar = arg or os.environ.get("JAVAFO_JAR", "")
    if not jar or not pathlib.Path(jar).exists():
        return None, "không tìm thấy JaVaFo jar (đặt --javafo hoặc JAVAFO_JAR)"
    if not shutil.which("java"):
        return None, "không tìm thấy 'java' trong PATH"
    return jar, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", default="../bbpPairings.exe")
    ap.add_argument("--javafo", default="")
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args(argv)

    exe = pathlib.Path(args.exe)
    if not exe.exists():
        print(f"Không tìm thấy engine {exe}", file=sys.stderr)
        return 2

    jar, why = find_javafo(args.javafo)
    if jar is None:
        print(f"[BỎ QUA] Đối chiếu JaVaFo: {why}.")
        print("  Cài JaVaFo (rrweb.org/javafo) và đặt JAVAFO_JAR để bật kiểm chứng.")
        # Vẫn kiểm tra pipeline cắt + ghép của bbpPairings để công cụ không im lặng.
        return _self_check(exe)

    shapes = [(11, 7), (24, 9), (40, 9)]
    total = agree = 0
    with tempfile.TemporaryDirectory() as d:
        w = pathlib.Path(d)
        for (n, rounds) in shapes:
            for seed in range(1, args.seeds + 1):
                (w / "cfg.txt").write_text(
                    f"PlayersNumber={n}\nRoundsNumber={rounds}\n"
                    f"DrawPercentage=30\n", encoding="utf-8")
                g = run([str(exe), "--dutch", "-g", "cfg.txt", "-o", "full.trf",
                         "-s", str(seed)], w)
                if g.returncode != 0:
                    print(f"  [gen-fail] n={n} r={rounds} seed={seed}")
                    continue
                full = (w / "full.trf").read_text(encoding="utf-8")
                for k in range(1, rounds):        # ghép vòng k+1 từ k vòng đầu
                    (w / "t.trf").write_text(truncate_trf(full, k, rounds),
                                             encoding="utf-8", newline="")
                    bp = run([str(exe), "--dutch", "t.trf", "-p"], w)
                    jf = run(["java", "-jar", jar, "t.trf", "-p"], w)
                    if bp.returncode != 0 or jf.returncode != 0:
                        continue
                    bp_pairs, _ = parse_pairing(bp.stdout)
                    jf_pairs, _ = parse_pairing(jf.stdout)
                    total += 1
                    if bp_pairs == jf_pairs:
                        agree += 1
                    else:
                        print(f"  [DIVERGE] n={n} r={rounds} seed={seed} round={k+1}")
                        print(f"      bbp only: {bp_pairs - jf_pairs}")
                        print(f"      jvf only: {jf_pairs - bp_pairs}")
    if total:
        print(f"\nJaVaFo comparison: {agree}/{total} rounds matched "
              f"({total - agree} divergences to review).")
    return 0


def _self_check(exe):
    """Không có JaVaFo: xác nhận pipeline cắt+ghép của bbpPairings chạy được."""
    with tempfile.TemporaryDirectory() as d:
        w = pathlib.Path(d)
        (w / "cfg.txt").write_text(
            "PlayersNumber=16\nRoundsNumber=7\nDrawPercentage=30\n",
            encoding="utf-8")
        g = run([str(exe), "--dutch", "-g", "cfg.txt", "-o", "full.trf",
                 "-s", "1"], w)
        if g.returncode != 0:
            print("  [self-check] không sinh được giải", file=sys.stderr)
            return 1
        full = (w / "full.trf").read_text(encoding="utf-8")
        ok = 0
        for k in range(1, 7):
            (w / "t.trf").write_text(truncate_trf(full, k, 7), encoding="utf-8",
                                     newline="")
            bp = run([str(exe), "--dutch", "t.trf", "-p"], w)
            if bp.returncode == 0 and bp.stdout.strip():
                ok += 1
            else:
                print(f"  [self-check] cắt {k} vòng: ghép lỗi "
                      f"({bp.returncode}) {bp.stderr.strip()[:80]}")
        print(f"  [self-check] pipeline cắt+ghép: {ok}/6 vòng OK.")
        return 0 if ok == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
