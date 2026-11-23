"""Run the rung 1 title through x2w_launch --log and check the run log.

Usage: run_log_check.py x2w_launch.exe x2w_rung1_title.exe SHIM_DIR

The title (tests/native/rung1_title.cpp) must start and exit cleanly with 0x5f, and the log must show each
startup milestone in order, each first stub call once with its class, and no crash. With
X2W_RUNG1_CRASH=1 the same title writes through a null pointer after its last stub call; the log must then
name the access violation at an RVA inside the title's .text, the address written and the last stub called.
Every line of both logs must match the log's grammar, which admits names, numbers and module+RVA addresses
only, and no 8-byte window of the title's section bytes may appear in either log.
"""
import ctypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import pefile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_check import allowed_names  # noqa: E402

NAME = r"[A-Za-z0-9_.\-]+"
SYMBOL = r"[A-Za-z0-9_.\-]+![A-Za-z0-9_#@?$]+"
WHERE = r"(?:[a-z0-9_.\-]+\+0x[0-9a-f]+|0x[0-9a-f]+)"
EXCEPTION = (rf"exception 0x[0-9a-f]{{8}} at {WHERE} thread (?:program|watchdog)"
             rf"(?: (?:reading|writing|executing|accessing) {WHERE})?")
LAST = rf"(?:{SYMBOL}|none)"
FEATURES = r"(?:none|[a-z0-9.\-]+(?:,[a-z0-9.\-]+)*)"
MNEMONIC = r"[a-z0-9\-]+"
GRAMMAR = [r"x2w-run-log 1", rf"program {NAME}", r"mapped size 0x[0-9a-f]+",
           r"imports shim=\d+ package=\d+ windows=\d+ stub=\d+ missing=\d+",
           rf"package-map-failed {NAME} status \d+ .*",
           rf"milestone tls-callback \d+ at {WHERE}", r"milestone tls-callbacks-done \d+",
           rf"milestone entry-reached {WHERE}", rf"milestone first-thread start {WHERE}",
           rf"milestone first-program-thread start {WHERE}",
           rf"milestone first-d3d12-call {SYMBOL} \((?:bound|stub|missing)\)",
           rf"first-call (?:stub|missing) {SYMBOL}",
           rf"first-chance {EXCEPTION} last-stub {LAST}", rf"crash {EXCEPTION} last-stub {LAST}",
           r"exit code 0x[0-9a-f]+ \(\d+\); stubs \d+ \(missing \d+\), stub calls \d+",
           r"timeout still running after \d+ s",
           rf"cpu-host-missing emulated={FEATURES} unhandled={FEATURES} silent={FEATURES}",
           rf"cpu-trap first {MNEMONIC} at {WHERE}", rf"cpu-unhandled {MNEMONIC} at {WHERE}",
           rf"cpu-traps total=\d+(?: {MNEMONIC}=\d+)*", r"cpu-trap-forced sites \d+",
           rf"summary (?:exit|crash|timeout): tls-callbacks=(?:done|not-done) entry=(?:reached|not-reached) "
           rf"first-thread=(?:yes|no) d3d12-call=(?:yes|no) crash=(?:yes|no) last-stub={LAST}"]


def run(launcher, title, shims, crash):
    with tempfile.TemporaryDirectory() as scratch:
        log = Path(scratch) / "run.log"
        env = dict(os.environ)
        env.pop("X2W_RUNG1_CRASH", None)
        if crash:
            env["X2W_RUNG1_CRASH"] = "1"
        result = subprocess.run([launcher, "--shims", shims, "--log", str(log), "--timeout", "60", title],
                                capture_output=True, text=True, timeout=120, env=env)
        text = log.read_text(encoding="utf-8")
    print(f"--- run.log ({'crash control' if crash else 'clean start'}), exit {result.returncode & 0xffffffff:#x}")
    print(text, end="")
    return result, text.splitlines()


def check_grammar(lines, title):
    for line in lines:
        assert any(re.fullmatch(rule, line) for rule in GRAMMAR), f"log line outside the grammar: {line!r}"
    _, sections = allowed_names(Path(title))
    blob = "\n".join(lines).encode()
    for raw in sections:
        for offset in range(max(0, len(raw) - 7)):
            window = raw[offset:offset + 8]
            if len(set(window)) >= 4 and not all(0x20 <= b < 0x7F for b in window):
                assert window not in blob, f"log holds raw section bytes at {offset:#x}"


def index_of(lines, pattern):
    for i, line in enumerate(lines):
        if re.fullmatch(pattern, line):
            return i
    raise AssertionError(f"no log line matches {pattern!r}")


def text_range(title):
    pe = pefile.PE(title, fast_load=True)
    try:
        entry = pe.OPTIONAL_HEADER.AddressOfEntryPoint
        text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
        return entry, text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
    finally:
        pe.close()


def main():
    launcher, title, shims = sys.argv[1:4]
    name = Path(title).name.lower()
    entry, text_start, text_end = text_range(title)
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)

    result, lines = run(launcher, title, shims, crash=False)
    check_grammar(lines, title)
    assert result.returncode == 0x5F, f"exit {result.returncode:#x}, expected 0x5f"
    assert lines[:2] == ["x2w-run-log 1", f"program {name}"], lines[:2]
    imports = next(line for line in lines if line.startswith("imports "))
    assert re.fullmatch(r"imports shim=4 package=0 windows=\d+ stub=1 missing=3", imports), imports
    order = [index_of(lines, rf"milestone tls-callback 0 at {re.escape(name)}\+0x[0-9a-f]+"),
             index_of(lines, r"milestone tls-callbacks-done 1"),
             index_of(lines, rf"milestone entry-reached {re.escape(name)}\+0x{entry:x}"),
             index_of(lines, rf"milestone first-program-thread start {re.escape(name)}\+0x[0-9a-f]+"),
             index_of(lines, r"milestone first-d3d12-call d3d12_xs\.dll!D3D12SerializeVersionedRootSignature \(bound\)"),
             index_of(lines, r"first-call stub xmem\.dll!X2wNotInShim"),
             index_of(lines, r"first-call missing x2w_missing\.dll!X2wMissingFirst"),
             index_of(lines, r"first-call missing x2w_missing\.dll!X2wMissingSecond"),
             index_of(lines, r"first-call missing x2w_missing\.dll!#7"),
             index_of(lines, r"exit code 0x5f \(95\); stubs 4 \(missing 3\), stub calls 5"),
             index_of(lines, r"summary exit: tls-callbacks=done entry=reached first-thread=yes d3d12-call=yes "
                             r"crash=no last-stub=x2w_missing\.dll!#7")]
    assert order == sorted(order), order
    index_of(lines, r"milestone first-thread start .*")
    thread = re.fullmatch(rf"milestone first-program-thread start {re.escape(name)}\+0x([0-9a-f]+)",
                          lines[order[3]])
    assert text_start <= int(thread[1], 16) < text_end, lines[order[3]]
    # X2wMissingFirst is called twice and logged once.
    assert sum("X2wMissingFirst" in line for line in lines) == 1, lines
    assert not any(line.startswith(("crash", "timeout")) for line in lines), lines
    # A Windows DLL may raise and handle an exception of its own; the title itself must raise none.
    assert not any(line.startswith("first-chance exception 0x") and f" at {name}+" in line for line in lines), lines

    result, lines = run(launcher, title, shims, crash=True)
    check_grammar(lines, title)
    assert result.returncode & 0xFFFFFFFF == 0xC0000005, f"exit {result.returncode & 0xffffffff:#x}"
    crash = index_of(lines, rf"crash exception 0xc0000005 at {re.escape(name)}\+0x([0-9a-f]+) thread program "
                            r"writing 0x0 last-stub x2w_missing\.dll!#7")
    rva = int(re.search(r"\+0x([0-9a-f]+)", lines[crash])[1], 16)
    assert text_start <= rva < text_end, lines[crash]
    # The first error exception is the title's write unless a Windows DLL raised (and handled) one before it.
    first = index_of(lines, r"first-chance exception .*")
    if f" at {name}+" in lines[first]:
        assert re.fullmatch(rf"first-chance exception 0xc0000005 at {re.escape(name)}\+0x{rva:x} thread program "
                            r"writing 0x0 last-stub x2w_missing\.dll!#7", lines[first]), lines[first]
    summary = index_of(lines, r"summary crash: tls-callbacks=done entry=reached first-thread=yes d3d12-call=yes "
                              r"crash=yes last-stub=x2w_missing\.dll!#7")
    assert first < crash < summary, (first, crash, summary)
    assert not any(line.startswith("exit code") for line in lines), lines
    print("native_run_log_rung1: clean start and crash control logged as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
