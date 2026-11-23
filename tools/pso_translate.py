"""Translate one gfx1013 shader for the graphics shim at pipeline-creation time (docs/design/runtime.md, section 3).

d3d12_xs.dll runs this out of process on a cache miss:

    python -B tools/pso_translate.py --stage vertex|pixel|compute --code CODE.bin --roles ROLES.json --dxc DXC
                                     --output OUT.dxil --bindings OUT.bind [--llvm LIBLLVM] [--hlsl OUT.hlsl]

CODE.bin is the raw code of one program (the shim cut it out of the console bytecode container). It is disassembled
with libLLVM when --llvm is given, otherwise with tools/gfx_text.py. ROLES.json is the entry contract the shim derived
from the container and the pipeline:
    vertex: {"user_sgprs": {"2": {"role": "inline", "word": 0}, "4": {"role": "base_vertex"},
                            "5": {"role": "start_instance"}, "6": {"role": "descriptors", "set": 0}, ...}}
    pixel:  {"sgprs": {"s2": "interp", "s3": "descriptors", "s4": "descriptors.1", "s5": "push:2"}}
    compute: {"sgprs": {"s2": "user:0", "s7": "group_id.x"}, "numthreads": [4, 1, 1], "wave": 32, "local_ids": 1}
            (rung R5: tools/compute_aot.py's entry-SGPR roles; user:N is push word N)
A descriptor-table SGPR (rung R4) holds the low word of the table's address; the program completes the pair with a
constant high word. Which descriptors the program reads from each table, and as what, is read off the program
(corpus_translate.derive_bindings: a T# where an image instruction names it, an S# where it is the sampler, a
constant-buffer V# where s_buffer_load reads through it); nothing is inferred about the table itself. Push words
("inline" in the vertex stage, "push:W" in the pixel stage) are one numbering shared by both stages of a pipeline.

The translated HLSL may declare only the bindings the shim fills at draw time, all in the runtime's register spaces
(src/d3d12_xs_pipeline.h, ConverterParam):
    both stages  b1 title_range_count, t2 title_ranges, t0..t7 space1 title_memory (-> spaces 1000/1001), b3 push
                 words (b3 space1000), and u0 space1000, the TitleLookup miss counter this script adds
    vertex       b0 the constant buffer of a descriptor table (b0 space1000), b2 base vertex and start instance
    (b1, b2 and the push words end up in one constant buffer, the frame words at b3 space1000: frame_words)
    pixel        textures t0, t1, t3..t8 (-> space1002, one table), samplers s0..s3 (-> space1002), constant slots 0
                 and 1 (-> b0, b1 space1003), the push-word slot (-> b3 space1000, the vertex stage's push words)
    compute      u0..u7 space1 title_memory, read-write (-> space1001, the UAV half of the title-memory table); its
                 constant words (params, b0) are the 64 frame words (-> b3 space1000), and a program that reads a
                 word past them is refused; from descriptor tables (R6) buffer V#s (frame words), T#s (t0, t1 ->
                 space1002) and one S# (s0 -> space1002)
Any other declaration (the vertex b4 descriptor words, pixel constant slots 2 and 3, storage images, title-memory
stores) is refused with the register it needs.

--bindings receives the descriptor-table reads the shim resolves at draw time, one per line after the header line
"x2w-bindings 1": "<texture|sampler|constants|buffer> <slot> <set> <byte offset>" (a compute buffer V#'s slot is
its first frame word), or "inline_sampler <slot> <w0> <w1> <w2> <w3>" for a sampler whose S# words the program
sets with s_mov (the shim decodes them). The shim caches it beside the DXIL.

Exit status: 0 translated (one JSON line on stdout), 1 refused (the reason on stderr, one line starting "refused:"),
2 a tool failure (disassembler library, DXC).

This command is the shim's fallback path. The shim's usual path is the long-lived service tools/pso_service.py, and
tools/precompile_cache.py translates ahead of time. Both call translate() and compile it with the same arguments
(dxc_arguments) through DXC's library (DxcLibrary), so all three write byte-identical DXIL and bindings for one input.
--text FILE gives the program as instruction text (one instruction per line, as the disassembler returns it) in place
of --code; the shim never uses it, the throughput checks of tests/runtime/xl_bench.py do.
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
TEXTURE_SPACE = 1002
PIXEL_CONSTANT_SPACE = 1003
PIXEL_CONSTANT_SLOTS = 2  # params (b0) and params1 (b1) in space 1003
PUSH_WORDS = 32
# The frame words: one 512-byte slice per draw or dispatch of the shim's upload ring, bound as the root CBV
# b3 space1000 (src/d3d12_xs_pipeline.h, FrameWords): 64 words (the push words; the compute stage's params, buffer
# V#s copied from descriptor tables at the top), then the title range count, the base vertex and the start instance.
FRAME_WORDS = 64
FRAME_CBUFFER = re.compile(r"cbuffer (\w+) : register\(b3, space1000\) \{ uint4 (\w+)\[(\d+)\]; \};\n?")
RANGE_COUNT_CBUFFER = re.compile(r"cbuffer \w+ : register\(b1, space1000\) \{ uint title_range_count; \};\n?")
VERTEX_ROOT_CBUFFER = re.compile(
    r"cbuffer \w+ : register\(b2, space1000\) \{ uint base_vertex; uint start_instance; \};\n?")
# The bindings both stages may declare, as (register, converter space).
BOUND = {("b1", 0), ("t2", 0), ("t0", 1), ("b3", 0)}
VERTEX_BOUND = BOUND | {("b0", 0), ("b2", 0)}
COMPUTE_BOUND = BOUND | {("u0", 1)}
REGISTER = re.compile(r"register\(\s*([btsu])(\d+)\s*(?:,\s*space(\d+)\s*)?\)")
CBUFFER = re.compile(r"cbuffer (\w+) : register\(b(\d+)\) \{ uint4 (\w+)\[(\d+)\]; \};")
LOOKUP_CALL = "TitleLookup(title_ranges, title_range_count,"
MISS_COUNTER = """RWByteAddressBuffer x2w_lookup_misses : register(u0, space1000);
// A TitleLookup miss (an address in no title range) reads zero, as before, and is counted for the shim
// (X2WGfxCounters::title_lookup_misses).
bool CountedTitleLookup(StructuredBuffer<TitleRange> ranges, uint count, uint2 address, uint bytes, out uint slot,
                        out uint offset)
{
    if (TitleLookup(ranges, count, address, bytes, slot, offset)) return true;
    uint previous;
    x2w_lookup_misses.InterlockedAdd(0, 1u, previous);
    return false;
}
"""


def disassemble(code, llvm):
    import pixel_aot
    if llvm:
        return pixel_aot.name_branch_targets(pixel_aot.disassemble(code, llvm, offsets=True), len(code))
    import gfx_text
    return pixel_aot.name_branch_targets(gfx_text.decode(code), len(code))


def _table_sets(roles):
    """{entry SGPR name: set} of the descriptor-table roles of either stage's role map."""
    from pixel_aot_ops.bindings import pointer_role
    out = {}
    for reg, role in roles.items():
        if isinstance(role, dict) and role.get("role") == "descriptors":
            out[f"s{reg}"] = role.get("set")
        elif isinstance(role, str) and pointer_role(role):
            out[reg] = 0 if role == "descriptors" else int(role.split(".")[1])
    return out


def derived_tables(program, tables):
    """corpus_translate.derive_bindings on the program, with each derived descriptor set renumbered to the set the
    shim gave its entry SGPR. Returns (derived description, {derived key: shim key})."""
    from corpus_translate import derive_bindings
    from pixel_aot_ops.bindings import SET_STRIDE
    derived = derive_bindings(program)
    renumber = {}
    for reg, role in derived.sgprs.items():
        if not (role == "descriptors" or role.startswith("descriptors.")):
            continue
        if reg not in tables:
            raise ValueError(f"the program loads descriptors through {reg}, which the container does not bind as a "
                             "descriptor table")
        renumber[0 if role == "descriptors" else int(role.split(".")[1])] = tables[reg]
    keys = {}
    for key in [*derived.textures, *derived.constant_buffers, *derived.buffers, *derived.storage_images,
                *(k for k in derived.samplers.values() if isinstance(k, int))]:
        keys[key] = renumber[key // SET_STRIDE] * SET_STRIDE + key % SET_STRIDE
    return derived, keys


def lower_compute(instructions, roles):
    """Rung R5: tools/compute_aot.py's lowering, without its offline root signature, its constant words moved onto
    the frame words. Descriptor tables (rung R6): buffer V#s the program loads from a table become frame words the
    shim copies from the table's memory at dispatch time (compute_aot's buffer_descriptors), the T#s it reads
    become texture slots 0 and 1 and its S# sampler slot 0 of the shim's texture and sampler tables."""
    import compute_aot
    from pixel_aot_ops.bindings import SET_STRIDE
    numthreads = roles.get("numthreads")
    if not isinstance(numthreads, list) or len(numthreads) != 3:
        raise ValueError("the compute entry contract has no workgroup size")
    sgprs = dict(roles.get("sgprs", {}))
    tables = _table_sets(sgprs)
    options, refs = {}, []
    if tables:
        derived, keys = derived_tables(instructions, tables)
        if derived.constant_buffers:
            raise ValueError("a constant-buffer V# (s_buffer_load) read from a descriptor table in a compute program "
                             "is not bound by the runtime yet (its words would be the frame words)")
        if derived.storage_images:
            raise ValueError("a storage image read from a descriptor table in a compute program is not bound by the "
                             "runtime yet")
        if any(not isinstance(source, int) for source in derived.samplers.values()):
            raise ValueError("an inline sampler in a compute program is not bound by the runtime yet")
        if len(derived.samplers) > 1 or len(derived.textures) > 2:
            raise ValueError("more than two T#s or one S# in a compute program (compute_aot binds tex, tex1 and samp)")
        options["buffer_descriptors"] = {keys[k]: word for k, word in derived.buffers.items()}
        options["textures"] = {keys[k]: slot for k, slot in derived.textures.items()}
        if derived.samplers:
            options["sampler"] = keys[next(iter(derived.samplers.values()))]
        options["descriptor_high"] = derived.descriptor_high
        for key, word in sorted(options["buffer_descriptors"].items()):
            refs.append(("buffer", word, key // SET_STRIDE, key % SET_STRIDE))
        for key, slot in sorted(options["textures"].items()):
            refs.append(("texture", slot, key // SET_STRIDE, key % SET_STRIDE))
        if "sampler" in options:
            refs.append(("sampler", 0, options["sampler"] // SET_STRIDE, options["sampler"] % SET_STRIDE))
    source = compute_aot.lower_compute(instructions, numthreads=tuple(numthreads), wave=roles.get("wave"),
                                       sgprs=sgprs, local_ids=roles.get("local_ids", 3), **options)
    source, embedded = re.subn(r'^\[RootSignature\("[^"]*"\)\]\n', "", source, flags=re.M)
    constants = "cbuffer Constants : register(b0) { uint4 params[16]; };"
    if embedded != 1 or source.count(constants) != 1:
        raise ValueError("compute_aot output without its root signature or constant window")
    reads = re.findall(r"\bparams\[([^\]]*)\]", source.replace(constants, ""))
    if any(not re.fullmatch(r"\d+", index) or int(index) >= FRAME_WORDS // 4 for index in reads):
        raise ValueError(f"the program reads a constant word past the {FRAME_WORDS} frame words or at a run-time "
                         "index (a constant-buffer window is not bound by the runtime yet)")
    source = source.replace(constants, f"cbuffer PushWords : register(b3) {{ uint4 params[{FRAME_WORDS // 4}]; }};")
    return source, {"numthreads": numthreads}, refs


def lower(stage, instructions, roles):
    """(HLSL in converter registers, layout, descriptor-table reads [(kind, slot, set, offset)])."""
    from pixel_aot_ops.bindings import SET_STRIDE
    lines = [line for line in instructions]
    if stage == "compute":
        return lower_compute(lines, roles)
    if stage == "vertex":
        import vertex_aot
        user = dict(roles.get("user_sgprs", {}))
        tables = _table_sets(user)
        refs = []
        if tables:
            derived, keys = derived_tables(lines, tables)
            if derived.textures or derived.samplers:
                raise ValueError("a vertex program that samples a texture is not lowered (image operations in the "
                                 "vertex stage)")
            if derived.buffers or derived.storage_images:
                raise ValueError("a buffer V# read from a descriptor table (the vertex b4 descriptor words) is not "
                                 "bound by the runtime yet")
            entries = {reg: {} for reg in tables}
            for key in derived.constant_buffers:
                shim = keys[key]
                reg = next(r for r, s in tables.items() if s == shim // SET_STRIDE)
                entries[reg][str(shim % SET_STRIDE)] = "constants"
                refs.append(("constants", 0, shim // SET_STRIDE, shim % SET_STRIDE))
            for reg in tables:
                if entries[reg]:
                    user[reg[1:]] = {"role": "descriptors", "high": derived.descriptor_high, "entries": entries[reg]}
                else:
                    del user[reg[1:]]  # a table the program never reads through
        source, layout = vertex_aot.lower_with_layout(lines, vertex_aot.parse_role_map(user))
        return source, {"params": layout["params"], "instance_id": layout["instance_id"]}, refs
    from pixel_aot_ops.bindings import PixelBindings, CONSTANT_SLOTS
    from pixel_aot_ops.lowering import lower as lower_pixel
    sgprs = dict(roles.get("sgprs", {}))
    tables = _table_sets(sgprs)
    textures, samplers, constants, high = {}, {}, {}, None
    if tables:
        derived, keys = derived_tables(lines, tables)
        if derived.buffers or derived.storage_images:
            raise ValueError("buffer V#s and storage images read from a descriptor table are not bound by the runtime "
                             "yet")
        textures = {keys[k]: slot for k, slot in derived.textures.items()}
        # An inline (immutable) sampler keeps its four S# words; the shim decodes them at pipeline creation.
        samplers = {slot: keys[k] if isinstance(k, int) else k for slot, k in derived.samplers.items()}
        constants = {keys[k]: slot for k, slot in derived.constant_buffers.items()}
        high = derived.descriptor_high
    if any(slot >= PIXEL_CONSTANT_SLOTS for slot in constants.values()):
        raise ValueError(f"more than {PIXEL_CONSTANT_SLOTS} constant-buffer V#s in a pixel program; the runtime binds "
                         f"constant slots 0 to {PIXEL_CONSTANT_SLOTS - 1}")
    push = None
    pushed = [int(role[5:]) for role in sgprs.values() if isinstance(role, str) and role.startswith("push:")]
    if pushed:
        if max(pushed) >= PUSH_WORDS:
            raise ValueError(f"a pixel push word past the {PUSH_WORDS} the runtime passes")
        push = next(n for n in range(CONSTANT_SLOTS) if n not in constants.values())
    description = PixelBindings(sgprs=sgprs, textures=textures, samplers=samplers, constant_buffers=constants,
                                push_constants=push, **({"descriptor_high": high} if high is not None else {}))
    description.check()
    refs = [("texture", slot, key // SET_STRIDE, key % SET_STRIDE) for key, slot in sorted(textures.items())]
    refs += [("sampler", slot, key // SET_STRIDE, key % SET_STRIDE)
             for slot, key in sorted(samplers.items()) if isinstance(key, int)]
    refs += [("inline_sampler", slot, *key) for slot, key in sorted(samplers.items()) if not isinstance(key, int)]
    refs += [("constants", slot, key // SET_STRIDE, key % SET_STRIDE) for key, slot in sorted(constants.items())]
    source = lower_pixel(lines, bindings=description)
    return source, {"push_slot": push}, refs


def place_in_runtime_spaces(source, stage="vertex", layout=None):
    """Move every register the translation declares into the runtime's spaces, refusing the unbound ones, and count
    TitleLookup misses."""
    push_slot = (layout or {}).get("push_slot")

    def constant_slot(array):
        return 0 if array == "params" else int(array[6:]) if re.fullmatch(r"params[1-3]", array) else None

    def move_cbuffer(m):
        name, register, array, size = m[1], int(m[2]), m[3], int(m[4])
        if stage == "pixel":
            slot = constant_slot(array)
            if slot is None:
                raise ValueError(f"the translation declares the constant buffer {array} (b{register}), which the "
                                 "runtime does not fill")
            if slot == push_slot:
                return f"cbuffer {name} : register(b3, space1000) {{ uint4 {array}[{PUSH_WORDS // 4}]; }};"
            if slot >= PIXEL_CONSTANT_SLOTS:
                raise ValueError(f"the translation declares constant slot {slot} (b{register}), a binding the "
                                 "runtime does not fill yet")
            return f"cbuffer {name} : register(b{slot}, space{PIXEL_CONSTANT_SPACE}) {{ uint4 {array}[{size}]; }};"
        if (f"b{register}", 0) not in VERTEX_BOUND:
            raise ValueError(f"the translation declares b{register} ({array}), a binding the runtime does not fill "
                             "yet" + (" (the vertex b4 descriptor words)" if register == 4 else ""))
        return f"cbuffer {name} : register(b{register}, space1000) {{ uint4 {array}[{size}]; }};"

    source = CBUFFER.sub(move_cbuffer, source)

    def move(m):
        kind, number, space = m[1], int(m[2]), int(m[3] or 0)
        if space >= 1000:
            return m[0]  # already placed (a cbuffer above, the miss counter)
        if stage in ("pixel", "compute") and space == 0 and (kind == "t" and number != 2 or kind == "s"):
            return f"register({kind}{number}, space{TEXTURE_SPACE})"
        allowed = {"vertex": VERTEX_BOUND, "compute": COMPUTE_BOUND}.get(stage, BOUND)
        if (f"{kind}{number}", space) not in allowed:
            raise ValueError(f"the translation declares {kind}{number}" + (f", space{space}" if space else "")
                             + ", a binding the runtime does not fill yet")
        return f"register({kind}{number}, space{RUNTIME_SPACES[space]})"
    source = REGISTER.sub(move, source)
    if LOOKUP_CALL in source:
        end = source.index("#endif", source.index("#define TITLE_VA_LOOKUP_HLSLI")) + len("#endif")
        source = source[:end] + "\n" + MISS_COUNTER + source[end:].replace(LOOKUP_CALL, "Counted" + LOOKUP_CALL)
    return frame_words(source)


def frame_words(source):
    """The push words, the title range count and the base vertex and start instance as one constant buffer, the
    frame words the shim writes into its upload ring per draw or dispatch (b3 space1000, FRAME_WORDS)."""
    members = []
    push = FRAME_CBUFFER.search(source)
    if push and int(push[3]) > FRAME_WORDS // 4:
        raise ValueError(f"the translation declares more than {FRAME_WORDS} frame words")
    members.append(f"uint4 {push[2] if push else 'x2w_frame_words'}[{FRAME_WORDS // 4}] : packoffset(c0);")
    count = RANGE_COUNT_CBUFFER.search(source)
    if count:
        members.append(f"uint title_range_count : packoffset(c{FRAME_WORDS // 4}.x);")
    bases = VERTEX_ROOT_CBUFFER.search(source)
    if bases:
        members.append(f"uint base_vertex : packoffset(c{FRAME_WORDS // 4}.y);")
        members.append(f"uint start_instance : packoffset(c{FRAME_WORDS // 4}.z);")
    if not (push or count or bases):
        return source
    for pattern in (FRAME_CBUFFER, RANGE_COUNT_CBUFFER, VERTEX_ROOT_CBUFFER):
        source = pattern.sub("", source, count=1)
    for register in ("b1", "b2", "b3"):
        if f"register({register}, space1000)" in source:
            raise ValueError(f"the translation declares {register} space1000 in a form the frame words do not hold")
    return "cbuffer X2WFrame : register(b3, space1000) { " + " ".join(members) + " };\n" + source


def bindings_text(refs):
    return "x2w-bindings 1\n" + "".join(" ".join(str(v) for v in ref) + "\n" for ref in refs)


def translate(stage, code, roles, llvm=None, instructions=None):
    """The HLSL of one program in the runtime's spaces, its layout, the bindings sidecar text (bindings_text) and the
    instruction count. Raises ValueError or KeyError for a refusal. `instructions` (text lines) replaces the
    disassembly of `code`."""
    if instructions is None:
        instructions = disassemble(code, llvm)
    source, layout, refs = lower(stage, instructions, roles)
    source = place_in_runtime_spaces(source, stage, layout)
    return source, {"bindings": len(refs), **layout}, bindings_text(refs), len(instructions)


def dxc_arguments(stage):
    """DXC's arguments before the source file. The compile flags of the draw checks: IEEE strictness, and for the
    pixel stage binary32 denormals preserved at ps_6_2 (tests/pixel_aot_draws/common.py), which also covers
    GetAttributeAtVertex (shader model 6.1)."""
    # The compute stage compiles as tests/compute_aot_check.py's draws do (cs_6_0).
    profile = {"vertex": ["-T", "vs_6_0"], "compute": ["-T", "cs_6_0"]}.get(stage,
                                                                         ["-denorm", "preserve", "-T", "ps_6_2"])
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
    parser.add_argument("--stage", choices=("vertex", "pixel", "compute"), required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--code", type=Path)
    inputs.add_argument("--text", type=Path, help="Instruction text, one per line, in place of --code")
    parser.add_argument("--roles", type=Path, required=True)
    parser.add_argument("--dxc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--llvm")
    parser.add_argument("--hlsl", type=Path, help="Also keep the HLSL here (local debugging only)")
    args = parser.parse_args()
    try:
        if args.text:
            roles = json.loads(args.roles.read_text(encoding="utf-8"))
            instructions = args.text.read_text(encoding="utf-8").splitlines()
            source, layout, bindings, count = translate(args.stage, None, roles, instructions=instructions)
        else:
            code = args.code.read_bytes()
            roles = json.loads(args.roles.read_text(encoding="utf-8"))
            source, layout, bindings, count = translate(args.stage, code, roles, args.llvm)
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
    # The sidecar first: a DXIL file in the cache always has its bindings.
    args.bindings.write_text(bindings, encoding="ascii", newline="\n")
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_bytes(dxil)
    os.replace(temporary, args.output)
    print(json.dumps({"stage": args.stage, "instructions": count, **layout}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
