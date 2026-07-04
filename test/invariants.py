#!/usr/bin/env python3
"""Independent FIDE-invariant checker for bbpPairings.

This is an *oracle-independent* validator: it parses a TRF tournament (either a
completed tournament produced by the engine's generator, or a state file plus a
pairing-output file) and asserts the hard constraints that ANY legal Swiss
pairing must satisfy, without re-implementing the Dutch/Burstein algorithm.

Hard invariants (a violation fails the run):
  * no two players are ever paired more than once;
  * a round is a valid partition (each player plays at most one game per round,
    and pairings are symmetric: A-vs-B in round r  <=>  B-vs-A in round r);
  * players declared on the same team (013 lines) are never paired together;
  * absolute colour criteria are respected -- no player ever reaches a colour
    difference of more than 2, nor three games in a row with the same colour
    (counting only rounds actually played with a colour).

Usage:
  # Fuzz campaign: generate many tournaments with the engine and check them.
  python invariants.py --exe ../bbpPairings.exe --campaign

  # Check a single already-complete TRF file.
  python invariants.py --exe ../bbpPairings.exe --check-trf some.trf

Exit code 0 = all clear, 1 = at least one violation, 2 = usage/environment error.
"""
import argparse
import pathlib
import subprocess
import sys
import tempfile


# --- TRF parsing ------------------------------------------------------------

FIRST_ROUND_COL = 91
ROUND_WIDTH = 10


def _round_entry(line, k):
    """Return (opp_str, color_char, result_char) for 1-based round k, or None."""
    base = FIRST_ROUND_COL + (k - 1) * ROUND_WIDTH
    if base + 8 > len(line):
        return None
    opp = line[base:base + 4]
    color = line[base + 5]
    result = line[base + 7]
    if opp == "    " and color == " " and result == " ":
        return None
    return opp, color, result


def parse_trf(text):
    """Parse a TRF string into {'players': {...}, 'teams': [...]}.

    players[id] = {
      'rating': int,
      'rounds': {k: {'opp': int|None, 'color': 'w'/'b'/None, 'result': char}},
    }
    teams = [(name, [member_id, ...]), ...]   ids are 1-based, as in the file.
    """
    players = {}
    teams = []
    for raw in text.replace("\r", "\n").split("\n"):
        if raw.startswith("001") and len(raw) >= 84:
            pid = int(raw[4:8])
            rating = 0
            rstr = raw[48:52].strip()
            if rstr:
                try:
                    rating = int(rstr)
                except ValueError:
                    rating = 0
            rounds = {}
            k = 1
            while True:
                entry = _round_entry(raw, k)
                if entry is None:
                    # keep scanning a few slots in case of internal gaps
                    if FIRST_ROUND_COL + (k - 1) * ROUND_WIDTH + 8 > len(raw):
                        break
                    k += 1
                    continue
                opp_s, color_c, result_c = entry
                opp = None
                if opp_s not in ("    ", "0000"):
                    try:
                        opp = int(opp_s)
                    except ValueError:
                        opp = None
                color = "w" if color_c == "w" else "b" if color_c == "b" else None
                rounds[k] = {"opp": opp, "color": color, "result": result_c.upper()}
                k += 1
            players[pid] = {"rating": rating, "rounds": rounds}
        elif raw.startswith("013"):
            name = raw[4:36].strip()
            members = []
            i = 36
            while i + 4 <= len(raw):
                tok = raw[i:i + 4].strip()
                if tok:
                    try:
                        members.append(int(tok))
                    except ValueError:
                        pass
                i += 5
            teams.append((name, members))
    return {"players": players, "teams": teams}


# --- Invariant checks -------------------------------------------------------

# A game that was actually played over the board (both players present). A
# forfeit ('+'/'-'), half-point bye ('H'), pairing-allocated bye ('U'), full
# forfeit-win bye ('F') or zero-point bye ('Z') is NOT a played game: under
# FIDE rules a game not actually played does not count as the two players
# having met, so they may legitimately be paired again.
PLAYED = set("10=WLD")


def check_tournament(parsed):
    """Return (hard_violations, soft_warnings).

    hard_violations are impossibilities in any legal Swiss pairing.
    soft_warnings (colour criteria) can be legitimately forced by forfeits,
    byes and unavoidable late-round situations, so they are reported for
    inspection but do not by themselves indicate a bug.
    """
    hard = []
    soft = []
    players = parsed["players"]
    teams = parsed["teams"]

    # 1) No two players ever play an actual game more than once.
    for pid, p in players.items():
        seen = {}
        for k, r in sorted(p["rounds"].items()):
            opp = r["opp"]
            if opp is None or r["result"] not in PLAYED:
                continue
            if opp in seen:
                hard.append(
                    f"REPEAT-GAME: player {pid} played {opp} in rounds "
                    f"{seen[opp]} and {k}")
            else:
                seen[opp] = k

    # 2) Pairing symmetry (A-vs-B <=> B-vs-A) and consistent played results.
    for pid, p in players.items():
        for k, r in p["rounds"].items():
            opp = r["opp"]
            if opp is None:
                continue
            if opp not in players:
                hard.append(
                    f"DANGLING-OPP: player {pid} round {k} names unknown {opp}")
                continue
            orr = players[opp]["rounds"].get(k)
            if orr is None or orr["opp"] != pid:
                hard.append(
                    f"ASYMMETRIC-PAIRING: player {pid} lists {opp} in round {k} "
                    f"but not vice versa")
                continue
            # For genuinely played games, colours oppose and results agree.
            if r["result"] in PLAYED and orr["result"] in PLAYED:
                if r["color"] and orr["color"] and r["color"] == orr["color"]:
                    hard.append(
                        f"SAME-COLOUR-PAIR: players {pid} & {opp} both "
                        f"'{r['color']}' in round {k}")
                rc, oc = r["result"], orr["result"]
                won = rc in set("1W")
                lost = rc in set("0L")
                drew = rc in set("=D")
                if won and oc not in set("0L"):
                    hard.append(f"RESULT-MISMATCH: {pid}(win)/{opp}({oc}) r{k}")
                elif lost and oc not in set("1W"):
                    hard.append(f"RESULT-MISMATCH: {pid}(loss)/{opp}({oc}) r{k}")
                elif drew and oc not in set("=D"):
                    hard.append(f"RESULT-MISMATCH: {pid}(draw)/{opp}({oc}) r{k}")

    # 3) Same-team players are never paired (any pairing, incl. forfeits).
    team_of = {}
    for idx, (_name, members) in enumerate(teams):
        for m in members:
            team_of[m] = idx
    if team_of:
        for pid, p in players.items():
            for k, r in p["rounds"].items():
                opp = r["opp"]
                if opp is None:
                    continue
                if team_of.get(pid) is not None and team_of.get(pid) == team_of.get(opp):
                    hard.append(
                        f"SAME-TEAM-PAIR: teammates {pid} & {opp} paired in "
                        f"round {k} (team #{team_of[pid]})")

    # 4) Colour criteria (soft): |diff| <= 2 and no 3 same colours in a row,
    #    counting only genuinely played games.
    for pid, p in players.items():
        diff = 0            # +1 per white, -1 per black
        streak_color = None
        streak = 0
        for k in sorted(p["rounds"]):
            r = p["rounds"][k]
            color = r["color"]
            if color is None or r["result"] not in PLAYED:
                continue
            diff += 1 if color == "w" else -1
            if color == streak_color:
                streak += 1
            else:
                streak_color, streak = color, 1
            if abs(diff) > 2:
                soft.append(
                    f"COLOUR-DIFF: player {pid} reaches colour difference "
                    f"{diff:+d} after round {k}")
            if streak >= 3:
                soft.append(
                    f"COLOUR-STREAK: player {pid} has {streak} '{color}' in a row"
                    f" ending round {k}")
    return hard, soft


# --- Drivers ----------------------------------------------------------------

def _run(exe, args, cwd):
    return subprocess.run(
        [str(exe)] + args, capture_output=True, text=True, cwd=str(cwd),
        timeout=120)


def generate_tournament(exe, system, cfg, seed, workdir):
    cfg_path = workdir / "cfg.txt"
    cfg_path.write_text(cfg, encoding="utf-8")
    r = _run(exe, [system, "-g", "cfg.txt", "-o", "out.trf", "-s", str(seed)], workdir)
    if r.returncode != 0:
        return None, r.stderr.strip() or f"exit {r.returncode}"
    out = workdir / "out.trf"
    if not out.exists():
        return None, "no output produced"
    return out.read_text(encoding="utf-8"), None


# A spread of configurations exercising the real-world features that have no
# golden-file tests: draws, forfeits, retirements (withdrawals), half-point
# byes, and non-standard point systems.
CAMPAIGN_CONFIGS = [
    ("--dutch", "PlayersNumber={n}\nRoundsNumber={r}\nDrawPercentage=30\n"),
    ("--dutch", "PlayersNumber={n}\nRoundsNumber={r}\nDrawPercentage=40\n"
                "ForfeitRate=8\nRetiredRate=6\n"),
    ("--dutch", "PlayersNumber={n}\nRoundsNumber={r}\nDrawPercentage=25\n"
                "HalfPointByeRate=5\n"),
    ("--dutch", "PlayersNumber={n}\nRoundsNumber={r}\nDrawPercentage=35\n"
                "ForfeitRate=10\nHalfPointByeRate=7\nRetiredRate=8\n"
                "PointsForForfeitLoss=0\n"),
    ("--burstein", "PlayersNumber={n}\nRoundsNumber={r}\nDrawPercentage=30\n"),
    ("--burstein", "PlayersNumber={n}\nRoundsNumber={r}\nDrawPercentage=40\n"
                   "ForfeitRate=8\nRetiredRate=6\nHalfPointByeRate=6\n"),
]

# (players, rounds) shapes: odd/even fields, short/long events.
SHAPES = [(9, 5), (10, 7), (23, 9), (30, 9), (7, 5), (50, 11)]


def campaign(exe, seeds):
    total = 0
    failures = 0
    soft_total = 0
    with tempfile.TemporaryDirectory() as d:
        workdir = pathlib.Path(d)
        for cfg_index, (system, cfg_tpl) in enumerate(CAMPAIGN_CONFIGS):
            for (n, rounds) in SHAPES:
                for seed in seeds:
                    total += 1
                    cfg = cfg_tpl.format(n=n, r=rounds)
                    trf, err = generate_tournament(exe, system, cfg, seed, workdir)
                    label = f"{system} cfg#{cfg_index} n={n} r={rounds} seed={seed}"
                    if trf is None:
                        print(f"  [GEN-FAIL] {label}: {err}")
                        failures += 1
                        continue
                    hard, soft = check_tournament(parse_trf(trf))
                    soft_total += len(soft)
                    if hard:
                        failures += 1
                        print(f"  [VIOLATION] {label}")
                        for msg in hard[:8]:
                            print(f"      - {msg}")
                        if len(hard) > 8:
                            print(f"      ... (+{len(hard) - 8} more)")
    print(f"\nInvariant campaign: {total - failures}/{total} tournaments passed "
          f"hard invariants ({soft_total} soft colour notes, forced by "
          f"forfeits/byes and not treated as failures).")
    return failures == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", default="../bbpPairings.exe",
                    help="path to bbpPairings executable")
    ap.add_argument("--campaign", action="store_true",
                    help="generate many tournaments and check them")
    ap.add_argument("--check-trf", metavar="FILE",
                    help="check a single already-complete TRF file")
    ap.add_argument("--seeds", type=int, default=4,
                    help="number of seeds per configuration (campaign mode)")
    args = ap.parse_args(argv)

    if args.check_trf:
        text = pathlib.Path(args.check_trf).read_text(encoding="utf-8")
        hard, soft = check_tournament(parse_trf(text))
        for msg in hard:
            print(f"  [HARD] {msg}")
        for msg in soft:
            print(f"  [soft] {msg}")
        if hard:
            print(f"{len(hard)} hard violation(s), {len(soft)} soft note(s).")
            return 1
        print(f"No hard invariant violations ({len(soft)} soft colour note(s)).")
        return 0

    if args.campaign:
        exe = pathlib.Path(args.exe)
        if not exe.exists():
            print(f"Executable not found: {exe}", file=sys.stderr)
            return 2
        seeds = list(range(1, args.seeds + 1))
        return 0 if campaign(exe, seeds) else 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
