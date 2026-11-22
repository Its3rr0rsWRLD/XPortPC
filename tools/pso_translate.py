"""Translate one gfx1013 shader for the graphics shim at pipeline-creation time (docs/design/runtime.md, section 3).

d3d12_xs.dll runs this out of process on a cache miss:

    python -B tools/pso_translate.py --stage vertex|pixel --code CODE.bin --roles ROLES.json --dxc DXC
                                     --output OUT.dxil [--llvm LIBLLVM] [--hlsl OUT.hlsl]

CODE.bin is the raw code of one program (the shim cut it out of the console bytecode container). It is disassembled
with libLLVM when --llvm is given, otherwise with tools/gfx_text.py. ROLES.json is the entry contract the shim derived
from the container and the pipeline:
    vertex: {"user_sgprs": {"2": {"role": "inline", "word": 0}, ...}}    (tools/vertex_aot.py's user-SGPR map)
    pixel:  {"sgprs": {"s2": "interp"}}                                   (bindings.PixelBindings.sgprs)

The translated HLSL may declare only the bindings the shim fills at draw time, all in the runtime's register spaces
(RUNTIME_SPACES below; the title's own root parameters keep spaces 0 and 1 for its own registers):
    b1 title_range_count, t2 title_ranges, t0..t7 space1 title_memory, b3 push_words  (converter space 0 -> 1000,
    converter space 1 -> 1001)
Any other declaration (a texture, a sampler, the b0 constant window, the b4 descriptor words, ...) is refused with the
register it needs; those bindings come with later rungs.

Exit status: 0 translated (one JSON line on stdout), 1 refused (the reason on stderr, one line starting "refused:"),
2 a tool failure (disassembler library, DXC).

This command is the shim's fallback path. The shim's usual path is the long-lived service tools/pso_service.py, and
tools/precompile_cache.py translates ahead of time. Both call translate() and compile it with the same arguments
(dxc_arguments) through DXC's library (DxcLibrary), so all three write byte-identical DXIL for one input. --text FILE
gives the program as instruction text (one instruction per line, as the disassembler returns it) in place of --code;
the shim never uses it, the throughput checks of tests/runtime/xl_bench.py do.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

# Converter register space -> the runtime's space in the desktop root signature (src/d3d12_xs_pipeline.cpp).
RUNTIME_SPACES = {0: 1000, 1: 1001}
# The bindings the shim fills at draw time, as (register, converter space).
BOUND = {("b1", 0), ("t2", 0), ("t0", 1), ("b3", 0)}
REGISTER = re.compile(r"register\(\s*([btsu])(\d+)\s*(?:,\s*space(\d+)\s*)?\)")


def disassemble(code, llvm):
    if llvm:
        import pixel_aot
        return pixel_aot.name_branch_targets(pixel_aot.disassemble(code, llvm, offsets=True), len(code))
    import gfx_text
    import pixel_aot
    return pixel_aot.name_branch_targets(gfx_text.decode(code), len(code))


def lower(stage, instructions, roles):
    if stage == "vertex":
        import vertex_aot
        source, layout = vertex_aot.lower_with_layout(instructions,
                                                      vertex_aot.parse_role_map(roles.get("user_sgprs", {})))
        return source, {"params": layout["params"], "instance_id": layout["instance_id"]}
    from pixel_aot_ops.bindings import PixelBindings
    from pixel_aot_ops.lowering import lower as lower_pixel
    sgprs = roles.get("sgprs", {})
    if any(role != "interp" for role in sgprs.values()):
        raise ValueError("pixel entry SGPR roles other than interp (descriptor sets, push words) are not bound by the "
                         "runtime yet")
    return lower_pixel(instructions, bindings=PixelBindings(sgprs=dict(sgprs))), {}


def place_in_runtime_spaces(source):
    """Move every register the translation declares into the runtime's spaces, refusing the unbound ones."""
    def move(m):
        kind, number, space = m[1], int(m[2]), int(m[3] or 0)
        if (f"{kind}{number}", space) not in BOUND:
            raise ValueError(f"the translation declares {kind}{number}" + (f", space{space}" if space else "")
                             + ", a binding the runtime does not fill yet")
        return f"register({kind}{number}, space{RUNTIME_SPACES[space]})"
    return REGISTER.sub(move, source)


def translate(stage, code, roles, llvm=None, instructions=None):
    """The HLSL of one program in the runtime's spaces, the layout the shim reads, and the instruction count.
    Raises ValueError or KeyError for a refusal. `instructions` (text lines) replaces the disassembly of `code`."""
    if instructions is None:
        instructions = disassemble(code, llvm)
    source, layout = lower(stage, instructions, roles)
    return place_in_runtime_spaces(source), layout, len(instructions)


def dxc_arguments(stage):
    """DXC's arguments before the source file. The compile flags of the draw checks: IEEE strictness, and for the
    pixel stage binary32 denormals preserved at ps_6_2 (tests/pixel_aot_draws/common.py), which also covers
    GetAttributeAtVertex (shader model 6.1)."""
    profile = ["-T", "vs_6_0"] if stage == "vertex" else ["-denorm", "preserve", "-T", "ps_6_2"]
    return ["-Gis", *profile, "-E", "main"]


def source_bytes(source):
    """The bytes DXC reads: the HLSL as Path.write_text(encoding="utf-8") writes it on this platform."""
    return source.replace("\n", os.linesep).encode("utf-8")


class ToolFailure(Exception):
    """DXC or its library failed (exit status 2)."""


def compile_with_process(dxc, stage, source, directory):
    """DXIL of `source` from one dxc.exe process, with its files in a temporary directory under `directory`."""
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        hlsl = Path(tmp) / "shader.hlsl"
        hlsl.write_text(source, encoding="utf-8")
        dxil = Path(tmp) / "shader.dxil"
        result = subprocess.run([dxc, *dxc_arguments(stage), "-Fo", str(dxil), str(hlsl)], capture_output=True,
                                text=True)
        if result.returncode or not dxil.exists():
            raise ToolFailure(f"DXC exit {result.returncode}: {result.stderr.strip()[-2000:]}")
        return dxil.read_bytes()


class DxcLibrary:
    """DXC's compiler (IDxcCompiler3) in this process, from the dxcompiler.dll beside `dxc`. Compiles with the
    arguments dxc.exe gets (dxc_arguments), so the DXIL is dxc.exe's byte for byte (tests/runtime/xl_check.py dxc).
    dxil.dll from the same directory, which validates and signs the container, is loaded first, so dxcompiler.dll
    uses the one dxc.exe would. One instance per thread."""
    CLSID_COMPILER = "73e22d93-e6ce-47f3-b5bf-f0664f39c1b0"
    IID_COMPILER3 = "228b4687-5a6a-4730-900c-9702b2203f54"
    IID_RESULT = "58346cda-dde7-4497-9461-6f87af5e0659"
    IID_BLOB = "8ba5fb08-5195-40e2-ac58-0d989c3a0102"
    OUT_OBJECT, OUT_ERRORS = 1, 2

    def __init__(self, dxc):
        import ctypes
        import uuid
        self._ctypes = ctypes
        located = shutil.which(dxc) or dxc
        directory = Path(located).resolve().parent
        library = directory / "dxcompiler.dll"
        if not library.exists():
            raise ToolFailure(f"no dxcompiler.dll beside {located}")
        if (directory / "dxil.dll").exists():
            self._dxil = ctypes.WinDLL(str(directory / "dxil.dll"))
        self._dll = ctypes.WinDLL(str(library))

        class Guid(ctypes.Structure):
            _fields_ = [("bytes", ctypes.c_ubyte * 16)]

        class Buffer(ctypes.Structure):
            _fields_ = [("ptr", ctypes.c_void_p), ("size", ctypes.c_size_t), ("encoding", ctypes.c_uint32)]

        self._Buffer = Buffer
        self._guids = {name: Guid((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le))
                       for name, text in (("clsid", self.CLSID_COMPILER), ("compiler3", self.IID_COMPILER3),
                                          ("result", self.IID_RESULT), ("blob", self.IID_BLOB))}
        create = self._dll.DxcCreateInstance
        create.restype = ctypes.c_long
        create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self._compiler = ctypes.c_void_p()
        hr = create(ctypes.byref(self._guids["clsid"]), ctypes.byref(self._guids["compiler3"]),
                    ctypes.byref(self._compiler))
        if hr < 0 or not self._compiler:
            raise ToolFailure(f"DxcCreateInstance(IDxcCompiler3) -> {hr & 0xffffffff:#010x}")

    def _method(self, obj, index, *argtypes):
        ctypes = self._ctypes
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])

    def _release(self, obj):
        if obj:
            self._method(obj, 2)(obj)

    def _blob(self, result, kind):
        ctypes = self._ctypes
        blob = ctypes.c_void_p()
        get_output = self._method(result, 7, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.c_void_p)
        if get_output(result, kind, ctypes.byref(self._guids["blob"]), ctypes.byref(blob), None) < 0 or not blob:
            return None
        try:
            table = ctypes.cast(blob, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
            pointer = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(table[3])(blob)
            size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(table[4])(blob)
            return ctypes.string_at(pointer, size) if size else b""
        finally:
            self._release(blob)

    def compile(self, stage, source):
        ctypes = self._ctypes
        data = source_bytes(source)
        text = ctypes.create_string_buffer(data, len(data))
        buffer = self._Buffer(ctypes.cast(text, ctypes.c_void_p), len(data), 0)
        arguments = [*dxc_arguments(stage), "shader.hlsl"]
        argv = (ctypes.c_wchar_p * len(arguments))(*arguments)
        result = ctypes.c_void_p()
        compile_ = self._method(self._compiler, 3, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        hr = compile_(self._compiler, ctypes.byref(buffer), argv, len(arguments), None,
                      ctypes.byref(self._guids["result"]), ctypes.byref(result))
        if hr < 0 or not result:
            raise ToolFailure(f"IDxcCompiler3::Compile -> {hr & 0xffffffff:#010x}")
        try:
            status = ctypes.c_long()
            self._method(result, 3, ctypes.POINTER(ctypes.c_long))(result, ctypes.byref(status))
            dxil = self._blob(result, self.OUT_OBJECT) if status.value >= 0 else None
            if not dxil:
                errors = (self._blob(result, self.OUT_ERRORS) or b"").decode("utf-8", "replace").strip()
                raise ToolFailure(f"DXC status {status.value & 0xffffffff:#010x}: {errors[-2000:]}")
            return dxil
        finally:
            self._release(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=("vertex", "pixel"), required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--code", type=Path)
    inputs.add_argument("--text", type=Path, help="Instruction text, one per line, in place of --code")
    parser.add_argument("--roles", type=Path, required=True)
    parser.add_argument("--dxc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--llvm")
    parser.add_argument("--hlsl", type=Path, help="Also keep the HLSL here (local debugging only)")
    args = parser.parse_args()
    try:
        roles = json.loads(args.roles.read_text(encoding="utf-8"))
        if args.text:
            instructions = args.text.read_text(encoding="utf-8").splitlines()
            source, layout, count = translate(args.stage, None, roles, instructions=instructions)
        else:
            source, layout, count = translate(args.stage, args.code.read_bytes(), roles, args.llvm)
    except (ValueError, KeyError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"tool failure: {error}", file=sys.stderr)
        return 2
    if args.hlsl:
        args.hlsl.write_text(source, encoding="utf-8")
    try:
        dxil = compile_with_process(args.dxc, args.stage, source, args.output.parent)
    except ToolFailure as error:
        print(f"tool failure: {error}", file=sys.stderr)
        return 2
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_bytes(dxil)
    os.replace(temporary, args.output)
    print(json.dumps({"stage": args.stage, "instructions": count, **layout}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
