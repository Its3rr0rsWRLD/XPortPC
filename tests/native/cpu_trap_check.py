"""Run the #UD handler fixture (tests/native/cpu_trap_title.cpp) under x2w_launch and check results and counts.

Usage: cpu_trap_check.py x2w_launch.exe x2w_cpu_trap_title.exe

Four runs:
  natural  the instructions run as they are: the host performs the ones it has, the handler the rest. Every
           case must pass, and an instruction whose feature the log's cpu-host-missing line lists as emulated
           must be counted as often as the program ran it.
  forced   --force-cpu-traps turns every listed site into UD2, so the handler performs all 17 instructions on
           any CPU. Every case must pass and each count must equal the program's count exactly.
  wrong    forced, with every expected value altered (X2W_CPUTRAP_WRONG=1): every case must fail.
  ud2      forced, ending in a UD2 that is not a site (X2W_CPUTRAP_UD2=1): the log must name it as
           "cpu-unhandled ud2" at an RVA inside .text, and the run must crash there with 0xc000001d.
Every log line must match run_log_check.py's grammar, which admits no program bytes.
"""
import ctypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_log_check import assert_hidden, check_grammar, text_range  # noqa: E402

MNEMONICS = ["sha1rnds4", "sha1nexte", "sha1msg1", "sha1msg2", "sha256rnds2", "sha256msg1", "sha256msg2",
             "clzero", "rdpid", "monitorx", "mwaitx", "extrq", "insertq", "movntsd", "movntss", "rdpru", "clwb"]
FEATURE = {"clzero": "clzero", "rdpid": "rdpid", "monitorx": "mwaitx", "mwaitx": "mwaitx", "rdpru": "rdpru",
           "clwb": "clwb", **{m: "sha" for m in MNEMONICS if m.startswith("sha")},
           **{m: "sse4a" for m in ("extrq", "insertq", "movntsd", "movntss")}}
SITES = 30


def run(launcher, title, label, force, **env_flags):
    with tempfile.TemporaryDirectory() as scratch:
        log = Path(scratch) / "run.log"
        env = {k: v for k, v in os.environ.items() if not k.startswith("X2W_CPUTRAP_")}
        env.update(env_flags)
        command = [launcher, "--log", str(log), "--timeout", "60"] + (["--force-cpu-traps"] if force else []) + [title]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, env=env)
        text = log.read_text(encoding="utf-8")
    code = result.returncode & 0xFFFFFFFF
    print(f"--- {label}: exit {code:#x}")
    print(result.stdout, end="")
    print("--- run.log")
    print(text, end="")
    lines = text.splitlines()
    check_grammar(lines, title)
    assert_hidden(Path(title).name, text, result.stderr)
    cases = dict(re.findall(r"^case (\S+) (ok|FAIL)$", result.stdout, re.M))
    counts = {m: int(n) for m, n in re.findall(r"^count (\S+) (\d+)$", result.stdout, re.M)}
    return code, cases, counts, lines


def traps(lines):
    line = next(l for l in lines if l.startswith("cpu-traps "))
    found = dict(re.findall(r" ([a-z0-9\-]+)=(\d+)", line))
    total = int(found.pop("total"))
    found = {k: int(v) for k, v in found.items()}
    assert total == sum(found.values()), line
    return found


def missing(lines):
    line = next(l for l in lines if l.startswith("cpu-host-missing "))
    lists = dict(re.findall(r"(emulated|unhandled|silent)=(\S+)", line))
    return {k: set() if v == "none" else set(v.split(",")) for k, v in lists.items()}


def main():
    launcher, title = sys.argv[1:3]
    name = "title.exe"  # the launcher's default name for the program
    _, text_start, text_end = text_range(title)
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    failures = []

    def expect(condition, message):
        if not condition:
            failures.append(message)
            print(f"FAIL: {message}")

    # Forced: the handler performs everything.
    code, cases, counts, lines = run(launcher, title, "forced", True)
    expect(code == 0x5F, f"forced exit {code:#x}, expected 0x5f")
    expect(len(cases) >= 30 and all(v == "ok" for v in cases.values()),
           f"forced cases failed: {[k for k, v in cases.items() if v != 'ok']}")
    expect(f"cpu-trap-forced sites {SITES}" in lines, "forced: no 'cpu-trap-forced sites 30' line")
    found = traps(lines)
    expect(set(counts) == set(MNEMONICS), f"program counts {sorted(counts)}")
    for mnemonic in MNEMONICS:
        expect(counts.get(mnemonic, 0) > 0 and found.get(mnemonic, 0) == counts.get(mnemonic),
               f"forced {mnemonic}: trapped {found.get(mnemonic, 0)}, ran {counts.get(mnemonic)}")
        first = [l for l in lines if l.startswith(f"cpu-trap first {mnemonic} at ")]
        where = re.fullmatch(rf"cpu-trap first {mnemonic} at {re.escape(name)}\+0x([0-9a-f]+)", first[0]) \
            if len(first) == 1 else None
        expect(where and text_start <= int(where[1], 16) < text_end, f"forced {mnemonic}: first-trap line {first}")
    expect(not any(l.startswith(("cpu-unhandled", "first-chance", "crash")) for l in lines),
           "forced: unexpected unhandled, first-chance or crash line")
    forced_counts = counts

    # Natural: the host's own instructions plus the handler for what it lacks.
    code, cases, counts, lines = run(launcher, title, "natural", False)
    host = missing(lines)
    print(f"host lacks: emulated={sorted(host['emulated'])} unhandled={sorted(host['unhandled'])} "
          f"silent={sorted(host['silent'])}")
    expect(code == 0x5F, f"natural exit {code:#x}, expected 0x5f")
    expect(cases and all(v == "ok" for v in cases.values()),
           f"natural cases failed: {[k for k, v in cases.items() if v != 'ok']}")
    expect(counts == forced_counts, "natural and forced runs ran different instruction counts")
    found = traps(lines)
    for mnemonic in MNEMONICS:
        ran, trapped = counts.get(mnemonic, 0), found.get(mnemonic, 0)
        if FEATURE[mnemonic] in host["emulated"]:
            expect(trapped == ran, f"natural {mnemonic}: host lacks {FEATURE[mnemonic]}, trapped {trapped} of {ran}")
        else:
            # The host has it, though an OS may still disable one (RDPRU) so that it faults.
            expect(trapped in (0, ran), f"natural {mnemonic}: trapped {trapped} of {ran}")
        print(f"natural {mnemonic}: ran {ran}, trapped {trapped}")

    # Wrong references must fail.
    code, cases, _, _ = run(launcher, title, "wrong-reference control", True, X2W_CPUTRAP_WRONG="1")
    expect(code == 0x10, f"wrong control exit {code:#x}, expected 0x10")
    expect(len(cases) >= 30 and all(v == "FAIL" for v in cases.values()),
           f"wrong control: cases still passing {[k for k, v in cases.items() if v != 'FAIL']}")

    # An instruction the handler does not know is named and crashes.
    code, _, _, lines = run(launcher, title, "unhandled control", True, X2W_CPUTRAP_UD2="1")
    expect(code == 0xC000001D, f"ud2 control exit {code:#x}, expected 0xc000001d")
    unhandled = [re.fullmatch(rf"cpu-unhandled ud2 at {re.escape(name)}\+0x([0-9a-f]+)", l) for l in lines]
    unhandled = [m for m in unhandled if m]
    expect(len(unhandled) == 1 and text_start <= int(unhandled[0][1], 16) < text_end,
           "ud2 control: no single cpu-unhandled ud2 line inside .text")
    crash = [l for l in lines if l.startswith("crash exception 0xc000001d at ")]
    expect(unhandled and crash and f"{name}+0x{unhandled[0][1]} " in crash[0] + " ",
           f"ud2 control: crash line {crash} does not name the same address")
    summary = [i for i, l in enumerate(lines) if l.startswith("summary crash:")]
    expect(summary and lines[summary[0] - 1].startswith("cpu-traps total="),
           "ud2 control: no cpu-traps line before the crash summary")

    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("cpu trap checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
