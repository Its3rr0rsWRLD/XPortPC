"""Draw family `pxcb`: pixel_aot_check.py draw --family pxcb.

Two parts of the binding description (tools/pixel_aot_ops/bindings.py PixelBindings, docs/design/pixel-bindings.md)
that corpus shaders (tools/corpus_translate.py) needed:

- constant windows (constant_sizes): a constant-buffer V# that s_buffer_load reads past its first 256 bytes is bound
  over a larger window, params<k>[] is declared up to the highest uint4 read (the whole window for a run-time offset),
  and a run-time offset past the window reads 0, as AMD's range check returns past num_records. The case binds each
  buffer through the 'X2WK' section of --check-pixel-case (tests/pixel_aot_render.cpp), larger than its window, so a
  translation that read past the window would see words that are not 0.
- input VGPRs (ps_input_ena, ps_input_addr): the inputs of SPI_PS_INPUT_ENA take VGPRs from v0 in bit order of
  SPI_PS_INPUT_ADDR; pos_x..pos_w come from SV_Position (pixel centre, depth, clip w), front_face from
  SV_IsFrontFace and pos_fixed_pt is the integer pixel coordinate (x in bits 0..15, y in 16..31). The harness's
  full-screen triangle has depth 0 and w 1 at every pixel and is front-facing, so z and w are told apart but 1/w is
  not from w, and only the front face is drawn.

Every draw exports raw words to the R32G32B32A32_UINT readback target and is compared word for word with a Python
reference; each wrong reference (a window that wraps at 256 bytes, a missing window, the slots swapped, an offset one
uint4 off, a run-time read past the window that is not 0 or one checked against 256 bytes, the pixel corner for its
centre, x and y swapped, z and w swapped, a back face, the halves of the fixed-point coordinate swapped, the VGPRs that
ADDR reserves read in place of the loaded ones) changes some texel and must be a mismatch."""
import struct
import subprocess

from pixel_aot_ops import bindings as binding_names
from pixel_aot_ops.bindings import PixelBindings

from .common import FLOAT_MODE_MAGIC, DrawBatch, lower

WINDOWS_MAGIC = 0x4B573258  # 'X2WK'


def word(slot, index):
    """Word `index` of the case's constant buffer `slot`: every slot and index differs, and none is 0."""
    return ((index + 1) * 0x01000193 ^ (slot + 1) * 0x9e3779b9) & 0xffffffff | 1


def buffer_words(slot, count):
    return [word(slot, i) for i in range(count)]


def case_bytes(rows, buffers, pixels=False):
    """A --check-pixel-case case on the integer target: the 64 words of params (slot 0's first 64, or zeros), 64 uint4
    rows (row-major), then the 'X2WK' section with {slot: words} (each at least 64 words, a multiple of 4). Without
    `pixels` the 'X2WF' section before it selects the R32G32B32A32_UINT target and each row covers an 8x8 block of the
    64x64 target; with `pixels` the case trailer after it does (flags: integer target, viewport) with an 8x8 viewport
    at the origin, so each row is one target pixel, as the input-VGPR draws need (SV_Position is per pixel)."""
    rows = [rows] * 64 if len(rows) == 4 and isinstance(rows[0], int) else list(rows)
    assert len(rows) == 64
    head = buffers.get(0, [0] * 64)[:64]
    data = bytearray(struct.pack("<64I", *head))
    for row in rows:
        data += struct.pack("<4I", *(w & 0xffffffff for w in row))
    if not pixels:
        data += struct.pack("<II", FLOAT_MODE_MAGIC, 1) + bytes(64)
    if buffers:
        data += struct.pack("<4I", WINDOWS_MAGIC, len(buffers), 0, 0)
        for slot, words in sorted(buffers.items()):
            assert len(words) >= 64 and len(words) % 4 == 0
            data += struct.pack("<II", slot, len(words)) + struct.pack(f"<{len(words)}I", *words)
    if pixels:
        data += struct.pack("<B4I", 3, 0, 0, 8, 8)
    return bytes(data)


def f32_bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


EXPORT = ["exp mrt0 v12, v13, v14, v15 done vm", "s_endpgm"]

# --- constant windows ---------------------------------------------------------------------------------------------

# One descriptor set at s2 (completed with s_movk_i32 0x8000, as RADV does): the V# of constant slot 0 (params) at
# 0x00 and of slot 1 (params1) at 0x20. Slot 0 is read at 0x110 and 0x3f8 (a window of 0x400 bytes), slot 1 at 0x7c0
# by a sixteen-word load (0x800 bytes).
SET = ["s_mov_b32 s20, s2",
       "s_movk_i32 s21, 0x8000",
       "s_load_dwordx4 s[24:27], s[20:21], null",
       "s_load_dwordx4 s[28:31], s[20:21], 0x20",
       "s_waitcnt lgkmcnt(0)"]
SET0 = [line for line in SET if "0x20" not in line]  # the V# of slot 0 alone
WINDOWS = [*SET,
           "s_buffer_load_dword s40, s[24:27], 0x110",
           "s_buffer_load_dwordx2 s[42:43], s[24:27], 0x3f8",
           "s_buffer_load_dwordx16 s[48:63], s[28:31], 0x7c0",
           "s_waitcnt lgkmcnt(0)",
           "v_mov_b32_e32 v12, s40",
           "v_mov_b32_e32 v13, s43",
           "v_mov_b32_e32 v14, s48",
           "v_mov_b32_e32 v15, s63",
           *EXPORT]
WINDOWS_BINDINGS = PixelBindings(sgprs={"s2": "descriptors"}, constant_buffers={0x00: 0, 0x20: 1},
                                 constant_sizes={0: 0x400, 1: 0x800})
# The buffers bound are larger than their windows: words past a window are there, and not 0.
WINDOW_BUFFERS = {0: buffer_words(0, 0x140), 1: buffer_words(1, 0x240)}


def windows_reference(flaw=None):
    def read(slot, byte):
        if flaw == "slots_swapped":
            slot = 1 - slot
        if flaw == "wrapped":
            byte %= 256
        if flaw == "uint4_off":
            byte -= 16
        if flaw == "unbound" and byte >= 256:
            return 0
        return word(slot, byte // 4)
    return (read(0, 0x110), read(0, 0x3fc), read(1, 0x7c0), read(1, 0x7fc))


WINDOWS_FLAWS = ("wrapped", "unbound", "slots_swapped", "uint4_off")

# A run-time offset into the grown window of slot 0: the push word in s3 is a byte offset (its two low bits are
# ignored; the push words are params1, b2); a dword that is not wholly inside the 0x400-byte window reads 0. The load
# at 0x3f8 gives the window. Only the V# of slot 0 is loaded.
DYNAMIC = [*SET0,
           "s_buffer_load_dword s40, s[24:27], 0x3f8",
           "s_buffer_load_dword s41, s[24:27], s3",
           "s_buffer_load_dwordx2 s[44:45], s[24:27], s3",
           "s_waitcnt lgkmcnt(0)",
           "v_mov_b32_e32 v12, s40",
           "v_mov_b32_e32 v13, s41",
           "v_mov_b32_e32 v14, s44",
           "v_mov_b32_e32 v15, s45",
           *EXPORT]
DYNAMIC_BINDINGS = PixelBindings(sgprs={"s2": "descriptors", "s3": "push:0"}, constant_buffers={0x00: 0},
                                 push_constants=1, constant_sizes={0: 0x400})
DYNAMIC_OFFSETS = (0x10, 0x112, 0x3f8, 0x3fc, 0x400, 0x4f0)


def dynamic_reference(offset, flaw=None):
    """The words of DYNAMIC at push word `offset`. Flaws: the range check left out (the bound buffer's word is read past
    the window), and the default 256-byte window checked in place of the grown one."""
    window = {"unchecked": 0x10000, "default_window": 0x100}.get(flaw, 0x400)

    def read(byte):
        return word(0, byte // 4) if byte + 4 <= window and byte < 4 * 0x140 else 0
    base = offset & ~3
    return (word(0, 0x3f8 // 4), read(base), read(base), read(base + 4))


DYNAMIC_FLAWS = ("unchecked", "default_window")

# --- input VGPRs --------------------------------------------------------------------------------------------------

PERSP_CENTER = binding_names.PERSP_CENTER
BIT = binding_names.PS_INPUT_BITS


def ena(*names):
    return PERSP_CENTER | sum(1 << BIT[name] for name in names)


# pos_x..pos_w as v2..v5, exported as their words.
POSITION = ["v_mov_b32_e32 v12, v2", "v_mov_b32_e32 v13, v3", "v_mov_b32_e32 v14, v4", "v_mov_b32_e32 v15, v5",
            *EXPORT]
POSITION_ENA = ena("pos_x", "pos_y", "pos_z", "pos_w")

# front_face as v2 and pos_fixed_pt as v3: the face tested as ACO tests gl_FrontFacing (0 < v) and selecting words,
# the coordinate word moved whole (the readback takes moves and selects, not integer ALU results).
FACE_PIXEL = ["v_cmp_lt_f32_e32 vcc_lo, 0, v2",
              "v_cndmask_b32_e64 v12, 0, 1, vcc_lo",
              "v_mov_b32_e32 v13, v3",
              "v_cndmask_b32_e64 v14, 0, v3, vcc_lo",
              "v_cndmask_b32_e64 v15, 7, 0, vcc_lo",
              *EXPORT]
FACE_PIXEL_ENA = ena("front_face", "pos_fixed_pt")

# Arithmetic on the pixel centre, as the corpus does with gl_FragCoord (2 z - 1, x - 0.5 s): pos_x, pos_y as v2, v3.
CENTRE_MATH = ["v_sub_f32_e32 v12, v2, v3",
               "v_mad_f32 v13, 2.0, v2, -1.0",
               "v_mul_f32_e32 v14, v2, v3",
               "v_mad_f32 v15, v3, neg(0.5), v2",
               *EXPORT]
CENTRE_MATH_ENA = ena("pos_x", "pos_y")

# SPI_PS_INPUT_ADDR wider than ENA: pos_x and pos_y take v2 and v3 but are not loaded, so pos_z and pos_w are v4, v5.
GAP = ["v_mov_b32_e32 v12, v4", "v_mov_b32_e32 v13, v5", "v_mad_f32 v14, 2.0, v4, -1.0", "v_add_f32_e32 v15, v5, v5",
       *EXPORT]
GAP_ENA, GAP_ADDR = ena("pos_z", "pos_w"), ena("pos_x", "pos_y", "pos_z", "pos_w")

PIXELS = [(x, y) for y in range(8) for x in range(8)]  # the 8x8 target of a `pixels` case
DEPTH, CLIP_W = 0.0, 1.0  # tests/pixel_aot_vs.hlsl: z 0 and w 1 at every vertex


def position_reference(flaw=None):
    rows = []
    for x, y in PIXELS:
        cx, cy = (x, y) if flaw == "corner" else (x + 0.5, y + 0.5)
        if flaw == "swapped":
            cx, cy = cy, cx
        z, w = (CLIP_W, DEPTH) if flaw == "z_w_swapped" else (DEPTH, CLIP_W)
        rows.append((f32_bits(cx), f32_bits(cy), f32_bits(z), f32_bits(w)))
    return rows


def face_pixel_reference(flaw=None):
    rows = []
    for x, y in PIXELS:
        px, py = (y, x) if flaw == "halves_swapped" else (x, y)
        front = flaw != "back_face"
        rows.append((int(front), px | py << 16, px | py << 16 if front else 0, 0 if front else 7))
    return rows


def centre_math_reference(flaw=None):
    rows = []
    for x, y in PIXELS:
        cx, cy = (x, y) if flaw == "corner" else (x + 0.5, y + 0.5)
        if flaw == "swapped":
            cx, cy = cy, cx
        rows.append((f32_bits(f32(cx - cy)), f32_bits(f32(2 * cx - 1)), f32_bits(f32(cx * cy)),
                     f32_bits(f32(cx - 0.5 * cy))))
    return rows


def gap_reference(flaw=None):
    rows = []
    for x, y in PIXELS:
        z, w = (CLIP_W, DEPTH) if flaw == "z_w_swapped" else (DEPTH, CLIP_W)
        if flaw == "addr_slots":  # v4, v5 taken as the inputs ADDR places first (pos_x, pos_y)
            z, w = x + 0.5, y + 0.5
        rows.append((f32_bits(z), f32_bits(w), f32_bits(f32(2 * z - 1)), f32_bits(f32(w + w))))
    return rows


INPUT_DRAWS = (
    ("position", POSITION, PixelBindings(sgprs={}, ps_input_ena=POSITION_ENA), position_reference,
     ("corner", "swapped", "z_w_swapped")),
    ("face_pixel", FACE_PIXEL, PixelBindings(sgprs={}, ps_input_ena=FACE_PIXEL_ENA), face_pixel_reference,
     ("back_face", "halves_swapped")),
    ("centre_math", CENTRE_MATH, PixelBindings(sgprs={}, ps_input_ena=CENTRE_MATH_ENA), centre_math_reference,
     ("corner", "swapped")),
    ("gap", GAP, PixelBindings(sgprs={}, ps_input_ena=GAP_ENA, ps_input_addr=GAP_ADDR), gap_reference,
     ("z_w_swapped", "addr_slots")),
)


def translate(program, description):
    return lower(program, bindings=description, integer_export=True)


def compile_draw(directory, compiler, name, program, description):
    source, shader = directory / f"pxcb_{name}.hlsl", directory / f"pxcb_{name}.cso"
    source.write_text(translate(program, description), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    return shader


def add_with_flaws(batch, name, reference, flaws, buffers, pixels=False):
    right = reference()
    batch.add(case_bytes(right, buffers, pixels), "pass", f"pxcb {name}: the reference does not match")
    for flaw in flaws:
        wrong = reference(flaw)
        assert wrong != right, (name, flaw)
        batch.add(case_bytes(wrong, buffers, pixels), "mismatch",
                  f"pxcb {name}: the {flaw} reference escaped detection")


def draw(directory, compiler, renderer, backend):
    shader = compile_draw(directory, compiler, "windows", WINDOWS, WINDOWS_BINDINGS)
    with DrawBatch(directory, renderer, backend, shader, "pxcb_windows") as batch:
        add_with_flaws(batch, "windows", windows_reference, WINDOWS_FLAWS, WINDOW_BUFFERS)
    shader = compile_draw(directory, compiler, "dynamic", DYNAMIC, DYNAMIC_BINDINGS)
    with DrawBatch(directory, renderer, backend, shader, "pxcb_dynamic") as batch:
        for offset in DYNAMIC_OFFSETS:
            push = [offset] + [0] * 63
            buffers = {0: buffer_words(0, 0x140), 1: push}
            right = dynamic_reference(offset)
            batch.add(case_bytes(right, buffers), "pass", f"pxcb dynamic at {offset:#x}: the reference does not match")
            for flaw in DYNAMIC_FLAWS:
                wrong = dynamic_reference(offset, flaw)
                if wrong != right:
                    batch.add(case_bytes(wrong, buffers), "mismatch",
                              f"pxcb dynamic at {offset:#x}: the {flaw} reference escaped detection")
    for flaw in DYNAMIC_FLAWS:  # every flaw is told apart at some offset
        assert any(dynamic_reference(o, flaw) != dynamic_reference(o) for o in DYNAMIC_OFFSETS), flaw
    for name, program, description, reference, flaws in INPUT_DRAWS:
        shader = compile_draw(directory, compiler, name, program, description)
        with DrawBatch(directory, renderer, backend, shader, f"pxcb_{name}") as batch:
            add_with_flaws(batch, name, reference, flaws, {}, pixels=True)


# --- controls -----------------------------------------------------------------------------------------------------

def refuses(reason, program, description):
    try:
        translate(program, description)
    except ValueError as error:
        if not str(error).startswith(reason):
            raise AssertionError(f"Expected refusal {reason!r}, got {error!r}") from error
        return
    raise AssertionError(f"Accepted, expected refusal {reason!r}")


def with_fields(base, **changes):
    names = ("sgprs", "textures", "samplers", "constant_buffers", "push_constants", "buffers", "storage_images",
             "descriptor_high", "dimensions", "constant_sizes", "ps_input_ena", "ps_input_addr")
    return PixelBindings(**{**{name: getattr(base, name) for name in names}, **changes})


def check_window_controls():
    import corpus_translate

    # The corpus derivation reads the same descriptions off the programs (the windows from the immediate offsets).
    assert corpus_translate.derive_bindings(WINDOWS) == WINDOWS_BINDINGS, corpus_translate.derive_bindings(WINDOWS)
    assert corpus_translate.derive_bindings(DYNAMIC) == DYNAMIC_BINDINGS, corpus_translate.derive_bindings(DYNAMIC)
    source = translate(WINDOWS, WINDOWS_BINDINGS)
    # The arrays are declared up to the highest uint4 read, not the whole window: params to word 0xff (uint4 63),
    # params1 to word 0x1ff (uint4 127).
    for text in ("cbuffer Constants : register(b0) { uint4 params[64]; };",
                 "cbuffer Constants1 : register(b2) { uint4 params1[128]; };",
                 "params[17].x", "params[63].w", "params1[124].x", "params1[127].w"):
        assert text in source, (text, source)
    # A run-time offset declares the whole window, and checks it.
    source = translate(DYNAMIC, DYNAMIC_BINDINGS)
    assert "uint4 params[64];" in source, source
    # Without a window, or with one that stops short, the read past 256 bytes is refused; a window of 256 bytes is the
    # default and changes nothing.
    refuses("Constant read exceeds binding", WINDOWS, with_fields(WINDOWS_BINDINGS, constant_sizes={1: 0x800}))
    refuses("Constant read exceeds binding", WINDOWS, with_fields(WINDOWS_BINDINGS, constant_sizes={0: 0x3f0, 1: 0x800}))
    refuses("Constant read exceeds binding", WINDOWS, with_fields(WINDOWS_BINDINGS, constant_sizes={0: 0x400, 1: 0x7f0}))
    small = [*SET0, "s_buffer_load_dword s40, s[24:27], 0xfc", "s_waitcnt lgkmcnt(0)", "v_mov_b32_e32 v12, s40",
             "v_mov_b32_e32 v13, s40", "v_mov_b32_e32 v14, s40", "v_mov_b32_e32 v15, s40", *EXPORT]
    plain = PixelBindings(sgprs={"s2": "descriptors"}, constant_buffers={0x00: 0})
    assert translate(small, plain) == translate(small, with_fields(plain, constant_sizes={0: 0x100}))
    assert translate(small, with_fields(plain, constant_sizes={0: 0x400})) == translate(small, plain)
    # Malformed windows: not a constant-buffer slot, not a multiple of 16, below 256 or past 65536 bytes.
    for sizes in ({2: 0x400}, {0: 0x408}, {0: 0xf0}, {0: 0x10010}, {0: "0x400"}):
        refuses("A constant window needs", WINDOWS, with_fields(WINDOWS_BINDINGS, constant_sizes=sizes))
    # The derivation caps the window at 65536 bytes; a read past that is refused.
    far = [*SET0, "s_buffer_load_dword s40, s[24:27], 0xfffc", "s_waitcnt lgkmcnt(0)", *small[-6:]]
    assert corpus_translate.derive_bindings(far).constant_sizes == {0: 0x10000}
    translate(far, corpus_translate.derive_bindings(far))
    beyond = [*SET0, "s_buffer_load_dword s40, s[24:27], 0x10000", "s_waitcnt lgkmcnt(0)", *small[-6:]]
    refuses("Constant read exceeds binding", beyond, corpus_translate.derive_bindings(beyond))


def check_input_controls():
    import corpus_translate

    for name, program, description, *_ in INPUT_DRAWS:
        source = translate(program, description)
        main = source.split("main(", 1)[1].split("\n", 1)[0]
        assert "SV_Position" in main, main
        assert ("SV_IsFrontFace" in main) == (name == "face_pixel"), main
    # The layout (bindings.input_vgprs): ADDR gives the VGPRs, ENA says which are loaded.
    layout, enabled = binding_names.input_vgprs(GAP_ENA, GAP_ADDR)
    assert layout == {"v0": ("persp_center", 0), "v1": ("persp_center", 1), "v2": ("pos_x", 0), "v3": ("pos_y", 0),
                      "v4": ("pos_z", 0), "v5": ("pos_w", 0)}, layout
    assert enabled == {"v0", "v1", "v4", "v5"}, enabled
    layout, enabled = binding_names.input_vgprs(0x7f | ena("pos_fixed_pt"))
    assert len(layout) == 16 and layout["v15"] == ("pos_fixed_pt", 0) and layout["v8"] == ("persp_pull_model", 2)
    # An input that is not lowered or not loaded is refused with its name; the default is persp_center alone, so v2 is
    # unset.
    # (an arithmetic read: a move of an unset register is refused at the export that reads it)
    refuses("Read of input VGPR v2 (pos_x)", ["v_add_f32_e32 v12, v2, v2", *GAP[1:]],
            PixelBindings(sgprs={}, ps_input_ena=GAP_ENA, ps_input_addr=GAP_ADDR))
    refuses("Read of input VGPR v2 (ancillary)", ["v_add_f32_e32 v12, v2, v2", *POSITION[1:]],
            PixelBindings(sgprs={}, ps_input_ena=ena("ancillary")))
    # persp_sample before persp_center moves every later input up two VGPRs: v2 is then a barycentric, and v0 an input
    # that is not lowered.
    sample_first = 0x1 | CENTRE_MATH_ENA
    refuses("Expected a numeric register", CENTRE_MATH, PixelBindings(sgprs={}, ps_input_ena=sample_first))
    refuses("Read of input VGPR v0 (persp_sample.0)", ["v_add_f32_e32 v12, v0, v0", *CENTRE_MATH[1:]],
            PixelBindings(sgprs={}, ps_input_ena=sample_first))
    assert binding_names.input_vgprs(sample_first)[0]["v4"] == ("pos_x", 0)
    refuses("Read of unset vector register v2", CENTRE_MATH, PixelBindings(sgprs={}))
    refuses("Read of unset vector register v6", ["v_add_f32_e32 v12, v6, v6", *POSITION[1:]],
            PixelBindings(sgprs={}, ps_input_ena=POSITION_ENA))
    # Malformed: no barycentric input, ENA not inside ADDR, more than 16 bits.
    for ena_word, addr in ((1 << BIT["pos_x"], None), (POSITION_ENA, PERSP_CENTER), (0x10002, None), ("0x2", None)):
        refuses("SPI_PS_INPUT_ENA needs", POSITION, PixelBindings(sgprs={}, ps_input_ena=ena_word, ps_input_addr=addr))
    # tests/corpus/ps-inputs.tsv: each row's enabled inputs are its ENA bits in VGPR order, and each shader exists.
    rows = [line.split("\t") for line in corpus_translate.PS_INPUTS.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")]
    assert rows and corpus_translate.ps_inputs() == {name: int(word, 16) for name, word, *_ in rows}
    for name, word, inputs, _ in rows:
        assert (corpus_translate.ISA / name).is_file(), name
        named = [n for n, _ in binding_names.PS_INPUTS if int(word, 16) >> BIT[n] & 1]
        assert named == inputs.split(), (name, named, inputs)


def controls(directory):
    check_window_controls()
    check_input_controls()
    for flaw in DYNAMIC_FLAWS:
        assert any(dynamic_reference(o, flaw) != dynamic_reference(o) for o in DYNAMIC_OFFSETS), flaw


def binary_fixtures():
    return [(WINDOWS, lambda program: translate(program, WINDOWS_BINDINGS)),
            (DYNAMIC, lambda program: translate(program, DYNAMIC_BINDINGS)),
            *((program, lambda p, d=description: translate(p, d)) for _, program, description, *_ in INPUT_DRAWS)]
