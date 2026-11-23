"""Run a source-built title under x2w_launch with the system layer (x2w_sys.dll) and check what it observes.

Usage: sys_title_check.py x2w_launch.exe x2w_sys_title.exe gdeflate_pack.exe SHIMS_DIR

tests/native/sys_title.cpp reads G:\\data\\hello.txt, G:\\data\\blob.bin and G:\\data\\blob.gds (the same bytes as
one GDeflate stream made by Microsoft's reference encoder, via gdeflate_pack) through the DirectStorage fallback,
and writes under T:\\ and D:\\. G:, T: and D: do not exist for Windows, so only the launcher's path rules make it work.

default   no config: exit 0x7f and the expected stdout (hashes computed here from the blob), G:/T:/D: remapped to the
          title folder and %LOCALAPPDATA%\\XPortPC\\<title>\\temp and \\scratch (LOCALAPPDATA points into the test
          folder), the identity answers still win for GetModuleFileNameW, DirectStorage requests counted in the
          shutdown summary, and the threading, topology and timing hooks off: GetSystemInfo, GetActiveProcessorCount
          and QueryPerformanceFrequency return Windows' own values and are not routed to the system layer.
--sys-config
          threads.virtual_cores 4 and timing.qpc_frequency 25000000 change those three answers (and only then are
          the imports routed to the system layer); the same config found as <title folder>\\x2w-sys.cfg works too.
control   paths.defaults off: the title reaches no G:, T: or D: file (exit 0x42: the factory status and the identity
          answer); skipped when this machine has such a drive.
errors    a missing --sys-config file exits 2.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT = 90


def run(command, env=None):
    result = subprocess.run([str(part) for part in command], capture_output=True, text=True, timeout=TIMEOUT, env=env)
    return result.returncode & 0xffffffff, result.stdout, result.stderr


def fnv(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def blob(size):
    """Half compressible, half pseudo-random, so the stream has tiles of both kinds (300001 bytes: 5 tiles)."""
    out = bytearray()
    state = 12345
    for i in range(size):
        state = (state * 1664525 + 1013904223) & 0xffffffff
        out.append((i // 7) & 0xff if i < size // 2 else state >> 24)
    return bytes(out)


def parse(stdout):
    values = {}
    for line in stdout.splitlines():
        for part in line.split():
            key, _, value = part.partition("=")
            values.setdefault(key, value)
    return values


def host_answers():
    kernel32 = ctypes.windll.kernel32

    class SystemInfo(ctypes.Structure):
        _fields_ = [("oem", ctypes.c_uint32), ("page", ctypes.c_uint32), ("min", ctypes.c_void_p),
                    ("max", ctypes.c_void_p), ("mask", ctypes.c_void_p), ("procs", ctypes.c_uint32),
                    ("type", ctypes.c_uint32), ("gran", ctypes.c_uint32), ("level", ctypes.c_uint16),
                    ("rev", ctypes.c_uint16)]

    info = SystemInfo()
    kernel32.GetSystemInfo(ctypes.byref(info))
    frequency = ctypes.c_int64()
    kernel32.QueryPerformanceFrequency(ctypes.byref(frequency))
    kernel32.GetActiveProcessorCount.restype = ctypes.c_uint32
    return info.procs, kernel32.GetActiveProcessorCount(0xffff), frequency.value


def main():
    launcher, title, pack, shims = (Path(a).resolve() for a in sys.argv[1:5])
    size = 300001
    data = blob(size)
    expected_hash = f"{fnv(data):x}"
    procs, active, qpf = host_answers()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        package = root / "pkg"
        (package / "data").mkdir(parents=True)
        exe = package / "x2w_sys_title.exe"
        shutil.copy(title, exe)
        (package / "data" / "hello.txt").write_bytes(b"hello from G:\n")
        (package / "data" / "blob.bin").write_bytes(data)
        code, out, err = run([pack, package / "data" / "blob.bin", package / "data" / "blob.gds", "9"])
        if code != 0:
            raise AssertionError(f"gdeflate_pack exit {code}: {out} {err}")
        stored = (package / "data" / "blob.gds").stat().st_size
        print(f"fixture: {size} bytes -> GDeflate stream {stored} bytes ({out.strip()})")
        if not 1000 < stored < size:
            raise AssertionError(f"unexpected stream size {stored}")
        local = root / "lad"
        local.mkdir()
        env = dict(os.environ, LOCALAPPDATA=str(local))
        env.pop("X2W_SYS_CONFIG", None)

        # ---- default: no config
        code, out, err = run([launcher, "--shims", shims, exe], env)
        print(f"default: exit {code:#x}\n{out}", end="")
        if code != 0x7f:
            raise AssertionError(f"default exit {code:#x} != 0x7f\n{err}")
        expected = (f"files=14\nfactory=0\nraw={size} fnv={expected_hash}\n"
                    f"gdeflate={size} fnv={expected_hash} same=1\ntemp=1 scratch=1\nname=1\n"
                    f"procs={procs} active={active} qpf={qpf}\n")
        if out != expected:
            raise AssertionError(f"stdout {out!r} != {expected!r}\n{err}")
        lines = err.splitlines()
        for symbol in ("CreateFileW", "GetFileAttributesExW", "GetFileAttributesW", "CreateDirectoryW"):
            line = f"[x2w] import kernel32.dll!{symbol} -> windows (x2w sys hook)"
            if line not in lines:
                raise AssertionError(f"missing report line: {line}\n{err}")
        if "[x2w] import kernel32.dll!GetModuleFileNameW -> windows (title identity)" not in lines:
            raise AssertionError(f"identity route lost:\n{err}")
        for symbol in ("GetSystemInfo", "GetActiveProcessorCount", "QueryPerformanceFrequency"):
            if f"[x2w] import kernel32.dll!{symbol} -> windows" not in lines:
                raise AssertionError(f"{symbol} is not a plain windows import by default:\n{err}")
        for needle in ("[x2w] import x2w_sys.dll!X2wDStorageFallbackRead -> shim", "[x2w] paths: rule G: -> ",
                       "[x2w] paths: rule T: -> ", "[x2w] paths: rule D: -> ", "[x2w] sys: threading, topology and timing hooks are off",
                       "[x2w] directstorage: fallback 2 requests"):
            if not any(line.startswith(needle) for line in lines):
                raise AssertionError(f"missing stderr line {needle!r}\n{err}")
        for line in lines:
            if line.startswith("[x2w] threads:") or line.startswith("[x2w] timing:"):
                raise AssertionError(f"threading or timing output without config: {line}")
        if "-> stub" in err:
            raise AssertionError(f"an import fell back to a stub:\n{err}")
        xport = local / "XPortPC" / "x2w_sys_title"
        if (xport / "temp" / "sys" / "temp.txt").read_bytes() != b"round-trip":
            raise AssertionError("T: write did not land under XPortPC\\<title>\\temp")
        if (xport / "scratch" / "sys" / "scratch.txt").read_bytes() != b"round-trip":
            raise AssertionError("D: write did not land under XPortPC\\<title>\\scratch")
        print("native_launch_sys default: G:/T:/D: remapped, GDeflate read equals the plain read, hooks off")

        # ---- --sys-config
        cfg = root / "sys.cfg"
        cfg.write_text("threads.virtual_cores 4\ntiming.qpc_frequency 25000000\n")
        code, out, err = run([launcher, "--shims", shims, "--sys-config", cfg, exe], env)
        values = parse(out)
        print(f"--sys-config: exit {code:#x} procs={values.get('procs')} active={values.get('active')} qpf={values.get('qpf')}")
        if code != 0x7f or (values.get("procs"), values.get("active"), values.get("qpf")) != ("4", "4", "25000000"):
            raise AssertionError(f"--sys-config: exit {code:#x}\n{out}\n{err}")
        for symbol in ("GetSystemInfo", "GetActiveProcessorCount", "QueryPerformanceFrequency"):
            if f"[x2w] import kernel32.dll!{symbol} -> windows (x2w sys hook)" not in err.splitlines():
                raise AssertionError(f"{symbol} not routed to the system layer:\n{err}")
        if "[x2w] threads: reporting 4 cores" not in err:
            raise AssertionError(f"no threads line:\n{err}")
        # The same config as <title folder>\x2w-sys.cfg.
        (package / "x2w-sys.cfg").write_text("threads.virtual_cores 6\n")
        code, out, err = run([launcher, "--shims", shims, exe], env)
        values = parse(out)
        if code != 0x7f or values.get("procs") != "6" or values.get("qpf") != str(qpf):
            raise AssertionError(f"x2w-sys.cfg beside the title: exit {code:#x}\n{out}\n{err}")
        (package / "x2w-sys.cfg").unlink()
        print("native_launch_sys config: --sys-config and x2w-sys.cfg switch the topology and timing hooks on")

        # ---- control: no path rules
        if any(os.path.exists(f"{letter}:\\") for letter in "GTD"):
            print("control skipped: this machine has a G:, T: or D: drive")
        else:
            cfg.write_text("paths.defaults off\n")
            code, out, err = run([launcher, "--shims", shims, "--sys-config", cfg, exe], env)
            print(f"control (no path rules): exit {code:#x}")
            if code != 0x42:
                raise AssertionError(f"control exit {code:#x} != 0x42 (the title reached G:/T:/D: files without a rule)\n{out}\n{err}")
            if "windows (x2w sys hook)" in err and "!CreateFileW -> windows (x2w sys hook)" in err:
                raise AssertionError(f"path hooks are on with no rules:\n{err}")

        # ---- errors
        code, _, err = run([launcher, "--shims", shims, "--sys-config", root / "missing.cfg", exe], env)
        if code != 2 or "--sys-config: cannot read" not in err:
            raise AssertionError(f"missing config: exit {code}\n{err}")
        print("native_launch_sys: a missing --sys-config file is refused")


main()
