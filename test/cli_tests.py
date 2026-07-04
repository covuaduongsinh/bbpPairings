#!/usr/bin/env python3
"""Portable CLI behaviour + exit-code tests for bbpPairings.

The C++ harness (main.cpp / testing::run) treats any non-zero exit code as a
failure, so it cannot assert the engine's *error* contract. This script does:
it drives the executable through subprocess (whose returncode is portable
across Windows and POSIX) and pins the documented exit codes and behaviours
that have no other test -- the no-valid-pairing / invalid-file / file-error
paths, unrated players, half-point byes, and the Dutch checker mode (only the
Burstein checker was previously exercised).

Exit codes under test (see README "Command line arguments"):
  0 success | 1 no valid pairing | 3 invalid request | 5 file access error

Usage:  python cli_tests.py --exe ../bbpPairings.exe
"""
import argparse
import pathlib
import subprocess
import sys
import tempfile


# --- minimal column-exact TRF builder --------------------------------------

def player_line(pid, rating, score, rounds):
    """rounds: list of (opp_str_4wide, color 'w'/'b'/'-'/' ', result_char)."""
    b = [" "] * 91
    b[0:3] = list("001")
    b[4:8] = list(f"{pid:>4}")
    nm = f"P{pid}"
    b[14:14 + len(nm)] = list(nm)
    b[48:52] = list(f"{rating:>4}")
    b[80:84] = list(f"{score:>4.1f}"[-4:])
    b[85:89] = list(f"{pid:>4}")
    line = "".join(b)
    for (opp, color, result) in rounds:
        line += f"{opp:>4} {color} {result}  "
    return line


def trf(rounds_total, players, initial="white1", extra_lines=()):
    """players: list of (pid, rating, score, rounds)."""
    lines = ["012 CLI Test", f"XXC {initial}", f"142 {rounds_total}"]
    for (pid, rating, score, rounds) in players:
        lines.append(player_line(pid, rating, score, rounds))
    lines.extend(extra_lines)
    return "\n".join(lines) + "\n"


# --- test runner ------------------------------------------------------------

class Runner:
    def __init__(self, exe):
        self.exe = str(exe)
        self.failures = 0
        self.passed = 0

    def run(self, args, cwd, stdin=None):
        return subprocess.run(
            [self.exe] + args, capture_output=True, text=True, cwd=str(cwd),
            timeout=60)

    def expect(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            print(f"  [ok]   {name}")
        else:
            self.failures += 1
            print(f"  [FAIL] {name}: {detail}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", default="../bbpPairings.exe")
    args = ap.parse_args(argv)
    exe = pathlib.Path(args.exe)
    if not exe.exists():
        print(f"Executable not found: {exe}", file=sys.stderr)
        return 2
    r = Runner(exe)

    with tempfile.TemporaryDirectory() as d:
        w = pathlib.Path(d)

        # 1) File-access error -> exit 5 (input file does not exist).
        res = r.run(["--dutch", "does_not_exist.trf", "-p"], w)
        r.expect("missing-file -> exit 5", res.returncode == 5,
                 f"got {res.returncode}: {res.stderr.strip()}")

        # 2) Malformed input -> exit 3 (invalid request).
        (w / "bad.trf").write_text("001 garbage line too short\n",
                                   encoding="utf-8", newline="")
        res = r.run(["--dutch", "bad.trf", "-p"], w)
        r.expect("malformed-input -> exit 3", res.returncode == 3,
                 f"got {res.returncode}: {res.stderr.strip()}")

        # 3) No valid pairing -> exit 1 (two players who already met, round 2).
        (w / "met.trf").write_text(
            trf(2, [(1, 2000, 1.0, [("   2", "w", "1")]),
                    (2, 1900, 0.0, [("   1", "b", "0")])]),
            encoding="utf-8", newline="")
        res = r.run(["--dutch", "met.trf", "-p"], w)
        r.expect("no-valid-pairing -> exit 1", res.returncode == 1,
                 f"got {res.returncode}: {res.stderr.strip()}")

        # 4) Unrated players (rating 0) pair fine in round 1 -> exit 0.
        (w / "unrated.trf").write_text(
            trf(3, [(i, 0, 0.0, []) for i in range(1, 5)]),
            encoding="utf-8", newline="")
        res = r.run(["--dutch", "unrated.trf", "-p"], w)
        r.expect("unrated-players -> exit 0", res.returncode == 0,
                 f"got {res.returncode}: {res.stderr.strip()}")
        r.expect("unrated-players produces 2 boards",
                 res.returncode == 0 and res.stdout.split("\n")[0].strip() == "2",
                 f"output: {res.stdout!r}")

        # 5) Half-point bye in history is accepted -> exit 0, valid output.
        #    Player 1 took a half-point bye in round 1 ("0000 - H"); pair r2.
        (w / "hpb.trf").write_text(
            trf(3, [
                (1, 2000, 0.5, [("0000", "-", "H")]),
                (2, 1950, 1.0, [("   3", "w", "1")]),
                (3, 1900, 0.0, [("   2", "b", "0")]),
                (4, 1850, 1.0, [("0000", "-", "U")]),
            ]),
            encoding="utf-8", newline="")
        res = r.run(["--dutch", "hpb.trf", "-p"], w)
        r.expect("half-point-bye accepted -> exit 0", res.returncode == 0,
                 f"got {res.returncode}: {res.stderr.strip()}")

        # 6) Forfeit result codes in history are accepted -> exit 0.
        (w / "ff.trf").write_text(
            trf(3, [
                (1, 2000, 1.0, [("   2", "w", "+")]),   # forfeit win
                (2, 1950, 0.0, [("   1", "b", "-")]),   # forfeit loss
                (3, 1900, 1.0, [("   4", "w", "1")]),
                (4, 1850, 0.0, [("   3", "b", "0")]),
            ]),
            encoding="utf-8", newline="")
        res = r.run(["--dutch", "ff.trf", "-p"], w)
        r.expect("forfeit-history accepted -> exit 0", res.returncode == 0,
                 f"got {res.returncode}: {res.stderr.strip()}")

        # 7) Dutch checker mode on an engine-generated tournament -> exit 0
        #    with no discrepancies (only the Burstein checker was tested before).
        (w / "cfg.txt").write_text(
            "PlayersNumber=20\nRoundsNumber=7\nDrawPercentage=30\n",
            encoding="utf-8")
        gen = r.run(["--dutch", "-g", "cfg.txt", "-o", "gen.trf", "-s", "7"], w)
        r.expect("generator -> exit 0", gen.returncode == 0,
                 f"got {gen.returncode}: {gen.stderr.strip()}")
        chk = r.run(["--dutch", "gen.trf", "-c"], w)
        r.expect("dutch-checker self-consistent -> exit 0",
                 chk.returncode == 0, f"got {chk.returncode}: {chk.stderr.strip()}")
        # A clean checker run prints only per-round progress ("...Round #N")
        # headers; a discrepancy would add pairing-diff lines. Assert none.
        residual = [ln for ln in chk.stdout.splitlines()
                    if ln.strip() and "Round #" not in ln]
        r.expect("dutch-checker reports no discrepancy",
                 chk.returncode == 0 and not residual,
                 f"unexpected checker lines: {residual!r}")

    print(f"\nCLI tests: {r.passed} passed, {r.failures} failed.")
    return 1 if r.failures else 0


if __name__ == "__main__":
    sys.exit(main())
