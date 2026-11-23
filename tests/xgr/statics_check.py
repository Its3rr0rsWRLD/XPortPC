"""Magic statics in a /MD title and in the same title built with /GL + /LTCG, each run directly and under
x2w_launch --log: every run must return 0x5a (tests/xgr/statics_title.cpp). The LTCG build reaches its
implicit TLS through slot 0 without _tls_index, so its run log must show x2w_launch's slot-0 alias.

Usage: statics_check.py x2w_launch.exe statics_title.exe statics_ltcg_title.exe
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    return result.returncode & 0xFFFFFFFF, result.stdout.strip()


def main(launcher, *titles):
    failures = []
    for title in titles:
        code, out = run([title])
        print(f"{Path(title).name} windows: {code:#x} {out}")
        if code != 0x5A:
            failures.append(f"{title} under Windows: {code:#x}")
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "run.log"
            code, out = run([launcher, "--log", str(log), "--timeout", "30", title])
            text = log.read_text(encoding="utf-8")
        print(f"{Path(title).name} x2w_launch: {code:#x} {out}")
        slot0 = re.search(r"^tls-slot0 index (\d+) threads (\d+)$", text, re.M)
        print(f"  {slot0.group(0) if slot0 else 'no tls-slot0 line'}")
        if code != 0x5A:
            failures.append(f"{title} under x2w_launch: {code:#x}\n{text}")
        if not slot0 or int(slot0.group(1)) == 0:
            failures.append(f"{title}: the run log has no tls-slot0 alias line")
    if failures:
        raise SystemExit("\n".join(failures))
    print("xgr_launch_statics: magic statics hold under x2w_launch, with and without LTCG")


if __name__ == "__main__":
    main(*sys.argv[1:])
