"""Run the source-built fake title through x2w_launch and check every import route.

Usage: launch_check.py x2w_launch.exe x2w_fake_title.exe SHIM_DIR

The fake title imports xmem.dll (served by the desktop shim in SHIM_DIR), kernel32.dll (Windows) and
x2w_missing.dll, which nothing provides. Under x2w_launch it must exit with 0x47 and the report must
name each route. As a control, the Windows loader cannot start it, because x2w_missing.dll is missing.
"""
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    launcher, title, shims = sys.argv[1:4]
    run = subprocess.run([launcher, "--shims", shims, title], capture_output=True, text=True, timeout=30)
    report = run.stderr
    print(report, end="")
    expected = [
        "[x2w] import xmem.dll!XMemAlloc -> shim",
        "[x2w] import xmem.dll!XMemFree -> shim",
        "[x2w] import kernel32.dll!GetCurrentThreadId -> windows",
        "[x2w] import x2w_missing.dll!X2wMissingFirst -> stub",
        "[x2w] import x2w_missing.dll!X2wMissingSecond -> stub",
        "[x2w] exit code 71; 2 stubs, 3 stub calls",
    ]
    for line in expected:
        assert line in report.splitlines(), f"missing report line: {line}"
    # Each stub reports its first call only, although X2wMissingFirst is called twice.
    assert report.count("[x2w] call stub x2w_missing.dll!X2wMissingFirst") == 1, report
    assert report.count("[x2w] call stub x2w_missing.dll!X2wMissingSecond") == 1, report
    assert run.returncode == 0x47, run.returncode
    # The program is title.exe in stderr and the run log; --show-program-name gives the real file name back.
    real = Path(title).name.lower()
    assert real not in report.lower(), report
    with tempfile.TemporaryDirectory() as scratch:
        for flags in ((), ("--show-program-name",)):
            log = Path(scratch) / "run.log"
            run2 = subprocess.run([launcher, "--shims", shims, "--log", str(log), *flags, title],
                                  capture_output=True, text=True, timeout=30)
            text = log.read_text(encoding="utf-8")
            if flags:
                assert f"program {real}" in text.splitlines(), text
            else:
                assert "program title.exe" in text.splitlines(), text
                assert real not in (text + run2.stderr).lower(), text + run2.stderr
    # Control: the normal Windows loader refuses the title (STATUS_DLL_NOT_FOUND). The error mode, which the
    # child inherits, suppresses the loader's dialog so the refusal returns instead of waiting for a click.
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    native = subprocess.run([title], capture_output=True, timeout=30)
    assert native.returncode in (0xC0000135, -1073741515), native.returncode
    # Control: without the shim directory, an import that resolves nowhere is still a stub.
    bare = subprocess.run([launcher, title], capture_output=True, text=True, timeout=30)
    assert "[x2w] import x2w_missing.dll!X2wMissingFirst -> stub" in bare.stderr.splitlines(), bare.stderr
    # --xmem configures the xmem.dll title memory layer through its environment; the layer logs what it applied.
    configured = subprocess.run([launcher, "--shims", shims, "--xmem", "layout=standalone", "--xmem",
                                 "windows=off", title], capture_output=True, text=True, timeout=30)
    lines = configured.stderr.splitlines()
    assert "[x2w] xmem setting X2W_XMEM_LAYOUT=standalone" in lines, configured.stderr
    assert any(l.startswith("[x2w] xmem config layout=standalone windows=off") for l in lines), configured.stderr
    assert configured.returncode == 0x47, configured.returncode
    # Control: without --xmem the defaults apply (arena layout, preferred windows).
    assert any(l.startswith("[x2w] xmem config layout=arena windows=prefer") for l in report.splitlines()), report
    # Control: a setting without '=' is a usage error.
    bad = subprocess.run([launcher, "--shims", shims, "--xmem", "layout", title], capture_output=True, text=True,
                         timeout=30)
    assert bad.returncode == 2, bad.returncode
    print("native_launch_fake_title: all routes behaved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
