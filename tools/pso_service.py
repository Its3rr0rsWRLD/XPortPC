"""The graphics shim's translator service (docs/design/runtime.md, section 3): one long-lived process that keeps the
converter imported and DXC loaded (pso_cache.Translator) and translates one shader per request.

    python -B tools/pso_service.py --dxc DXC [--llvm LIBLLVM] [--compiler library|process] [--scratch DIR]

d3d12_xs.dll starts a few of these (src/d3d12_xs_translator.cpp) and talks to each over its stdin and stdout. Every
message is a frame: u32 payload length, then the payload. Integers are little-endian u32, strings are a u32 length and
UTF-8 bytes.
    ready (service -> shim, once, after start-up):  "X2WT", version 2, compiler (0 library, 1 dxc.exe), why (string)
    request (shim -> service):   stage (0 vertex, 1 pixel, 2 compute), flags (1: return the HLSL), roles (string), code (string;
                                 with flag 2, instruction text, one per line, in place of code: checks only)
    response (service -> shim):  status (0 translated, 1 refused, 2 tool failure), instruction count, message (string;
                                 the refusal reason or the failure), DXIL (string), HLSL (string, empty unless asked),
                                 bindings (string: the sidecar text of pso_translate.py --bindings)
The service exits when stdin closes. Nothing but frames is written to stdout: anything the converter prints goes to
stderr. The translation, the DXIL and the bindings are those of tools/pso_translate.py for the same input, byte for byte.
"""
import argparse
import os
from pathlib import Path
import struct
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))

MAGIC = b"X2WT"
VERSION = 2
FLAG_HLSL, FLAG_TEXT = 1, 2
STAGE_NAMES = ("vertex", "pixel", "compute")


def read_exact(stream, count):
    data = b""
    while len(data) < count:
        chunk = stream.read(count - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def read_frame(stream):
    head = read_exact(stream, 4)
    if head is None:
        return None
    size, = struct.unpack("<I", head)
    return read_exact(stream, size) if size else b""


def write_frame(stream, parts):
    payload = b"".join(parts)
    stream.write(struct.pack("<I", len(payload)) + payload)
    stream.flush()


def u32(value):
    return struct.pack("<I", value)


def string(data):
    data = data.encode("utf-8", "replace") if isinstance(data, str) else data
    return u32(len(data)) + data


class Reader:
    def __init__(self, data):
        self.data, self.at = data, 0

    def u32(self):
        value, = struct.unpack_from("<I", self.data, self.at)
        self.at += 4
        return value

    def bytes(self):
        size = self.u32()
        value = self.data[self.at:self.at + size]
        if len(value) != size:
            raise ValueError("truncated request")
        self.at += size
        return value


def serve(translator, inp, out):
    from pso_translate import source_bytes  # the HLSL as pso_translate.py --hlsl writes it
    while (frame := read_frame(inp)) is not None:
        request = Reader(frame)
        stage, flags = request.u32(), request.u32()
        roles = request.bytes().decode("utf-8")
        code = request.bytes()
        instructions = code.decode("utf-8").splitlines() if flags & FLAG_TEXT else None
        try:
            status, message, dxil, hlsl, count, bindings = translator.translate(STAGE_NAMES[stage], None if instructions is not None else code,
                                                                      roles, instructions)
        except Exception:  # noqa: BLE001 - an unexpected converter error refuses this shader, as a crash of
            # pso_translate.py does (exit status 1, the reason its output's tail); the service goes on.
            status, message, dxil, hlsl, count, bindings = 1, traceback.format_exc()[-400:].strip(), b"", "", 0, ""
        write_frame(out, [u32(status), u32(count), string(message), string(dxil),
                          string(source_bytes(hlsl) if flags & FLAG_HLSL else b""), string(bindings.encode("ascii"))])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dxc", required=True)
    parser.add_argument("--llvm")
    parser.add_argument("--compiler", choices=("library", "process"), default="library")
    parser.add_argument("--scratch", help="Directory for dxc.exe's files when the library is not used")
    args = parser.parse_args()
    # Frames go to the original stdout; print() and anything else written to fd 1 go to stderr.
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    inp = os.fdopen(os.dup(0), "rb", buffering=0)
    import pso_cache
    translator = pso_cache.Translator(args.dxc, args.llvm, args.compiler, args.scratch)
    write_frame(out, [MAGIC, u32(VERSION), u32(0 if translator.library else 1), string(translator.why_process or "")])
    serve(translator, inp, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
