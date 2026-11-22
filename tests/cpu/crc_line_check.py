"""Run an independently linked console program from its PE entry to process exit."""
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import zlib

import pefile

from exe_entry_check import Observation, check, observation
from exe_process import launch
from mapped_exe_chain_check import run_mapped
from cpu_leaf_aot import export_rva
from cpu_stdio_exe_aot import STDIO, translate


HOST_RETURNED = b"mapped CRC host returned\n"


def check_worker_lifetime(native, mapped, case, env):
    label, data, output, code = case
    label = f"{native[0].name} {label}"
    result = launch(native, data, env=env)
    checks = (("process signaled", result["process_signaled"], True),
              ("stdout EOF", result["stdout"]["eof"], True),
              ("stderr EOF", result["stderr"]["eof"], True),
              ("stdout bytes", result["stdout"]["bytes"], output),
              ("stderr bytes", result["stderr"]["bytes"], b""),
              ("exit code", result["code"], code))
    for field, actual, expected in checks:
        check(f"{label} native worker {field}", actual, expected)
    result = launch([*mapped, "--observe-return"], data, env=env)
    check(f"{label} mapped host returned with worker held", observation(result),
          Observation(HOST_RETURNED, output, code))
    print(f"{label}: native process signaled, both pipes reached EOF, "
          f"stdout {output!r}, stderr empty, exit {code}, mapped host returned with worker held")


def check_read_only_stdout(sink, command, *, env=None, stderr=b""):
    with sink.open("rb") as read_only:
        child = subprocess.run(command, input=b"123456789\n", stdout=read_only,
                               stderr=subprocess.PIPE, timeout=15, env=env)
    check(f"{command[0]} write failure", (child.returncode, child.stderr, sink.read_bytes()),
          (2, stderr, b"unchanged"))


def compare(mapper, io, image, lifted, cases):
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    with pefile.PE(str(image), fast_load=True) as pe:
        check(f"{image.name} PE startup is separate from the CRC body",
              pe.OPTIONAL_HEADER.AddressOfEntryPoint == export_rva(pe, "native_entry"), False)
    with pefile.PE(str(lifted), fast_load=True) as pe:
        embedded = pe.get_string_at_rva(export_rva(pe, "aot_source_sha256"))
    check(f"{image.name} AOT input SHA-256", embedded, digest.encode("ascii"))
    print(f"{image.name} native/pe_map/AOT source SHA-256 {digest}")

    native = [image]
    mapped = [sys.executable, "-B", __file__, "--mapped", mapper, image, io]
    commands = {"native": native, "mapped": mapped, "AOT": [lifted]}
    worker_env = dict(os.environ, CPU_CRC_TEST_LIVE_WORKER="1")
    for case in cases:
        label, data, output, code = case
        expected = Observation(b"", output, code)
        for runner, command in commands.items():
            check(f"{image.name} {label} {runner}", observation(launch(command, data)), expected)
        print(f"{image.name} {label}: {output!r}, exit {code} on all three runners")
        check_worker_lifetime(native, mapped, case, worker_env)
    with TemporaryDirectory() as directory:
        sink = Path(directory) / "read-only.txt"
        sink.write_bytes(b"unchanged")
        for command in commands.values():
            check_read_only_stdout(sink, command)
        check_read_only_stdout(sink, native, env=worker_env)
        check_read_only_stdout(sink, [*mapped, "--observe-return"], env=worker_env, stderr=HOST_RETURNED)
    print(f"{image.name} read-only stdout: sink unchanged and exit 2 on all three runners, "
          "including native exit and mapped host return with the worker held")
    check(f"{image.name} SHA-256 after runs", hashlib.sha256(image.read_bytes()).hexdigest(), digest)


def test(mapper, io, native, lifted, control, lifted_control):
    long_line = b"input record " * 1000
    cases = [("check vector", b"123456789\n", b"CBF43926\r\n", 0),
             ("missing line", b"", b"", 1),
             ("empty line", b"\n", b"00000000\r\n", 0),
             ("CRLF and trailing input", b"abc\r\nignored", b"352441C2\r\n", 0),
             ("EOF after data", b"abc", b"352441C2\r\n", 0),
             ("multiple input buffers", long_line, f"{zlib.crc32(long_line):08X}\r\n".encode(), 0)]
    compare(mapper, io, native, lifted, cases)
    compare(mapper, io, control, lifted_control, [("changed polynomial", b"123456789\n", b"E3069283\r\n", 0)])

    # A familiar symbol in a different DLL must never bind to the stdio host.
    with TemporaryDirectory() as directory, pefile.PE(str(native)) as pe:
        module, = (entry for entry in pe.DIRECTORY_ENTRY_IMPORT
                   if entry.dll.decode("ascii").lower() == STDIO)
        offset = pe.get_offset_from_rva(module.struct.Name)
        data = bytearray(native.read_bytes())
        data[offset] = ord("x")
        changed = Path(directory) / native.name
        changed.write_bytes(data)
        try:
            translate(changed, entry_export="native_entry")
        except ValueError as exc:
            if "unbound console import xpi-ms-win-crt-stdio" not in str(exc):
                raise
        else:
            raise AssertionError("wrong provider accepted")


if __name__ == "__main__":
    if sys.argv[1] == "--mapped":
        import msvcrt

        mapper, image, io = map(Path, sys.argv[2:5])
        # Python sets binary mode on its pipes; the native console EXE starts in UCRT text mode.
        msvcrt.setmode(0, os.O_TEXT)
        msvcrt.setmode(1, os.O_TEXT)
        code = run_mapped(mapper, image, {STDIO: ctypes.CDLL(STDIO), io.name.lower(): ctypes.CDLL(str(io))})
        if sys.argv[5:] == ["--observe-return"]:
            sys.stderr.buffer.write(HOST_RETURNED)
        sys.exit(code)
    test(*map(Path, sys.argv[1:]))
