"""Draw family `stores`: pixel_aot_check.py draw --family stores.

Pixel shaders write title memory: buffer_store_*, buffer_store_format_*, tbuffer_store_format_* and global_store_*.
The harness binds the memory slots as UAVs when a case carries expected contents (the 'X2WE' part of the memory section,
tests/pixel_aot_render.cpp) and compares every slot byte for byte after the draw. The draw is 64x64 pixels; each pixel
derives its key k = 64 * y + x (0..4095) from the interpolated coordinate (uv * 64, truncated) and owns the 64-byte
record at k * 64 of slot 0, so every plain store has one writer and the final memory is exact. Slot 0 starts 0x20000
bytes below 4 GiB, so the records of keys 2048 and up need the carry into the high address word. The data words are
d0 = k * C1, d1 = d0 ^ C2, d2 = d0 + d1 and d3 = d1 ^ k (C1, C2 in constant words 3 and 4). The references below
apply each pixel's stores, in program order, to the initial memory on Python integers; a "flaw" switches one rule off
to make a plausible wrong reference, which the controls require to differ from the right one and the draw must reject.
The color export is the constant (0.5, 1, 0, 1)."""
import functools
import struct
import subprocess

import pixel_memory_check as titlemem

from .common import M32, lower, must_reject, with_constants

C1, C2 = 0x9E3779B1, 0x5BD1E995
KEYS = 4096
R0, RSIZE = 0x1_0000_0000 - 0x20000, 0x40000  # slot 0: records, 64 bytes per key
A0, ASIZE = 0x3_0000_1000, 0x80100  # slot 1: atomics, 128 bytes per key, then the shared words at A0 + 0x80000
SHARED = A0 + 0x80000
RANGES = ((R0, R0 + RSIZE, 0), (A0, A0 + ASIZE, 1))
COLOR = [0.5, 1.0, 0.0, 1.0]
VSHARP_OFFSETS = {0x80: 8, 0x90: 12, 0xa0: 16}  # as tests/pixel_aot_draws/load.py: s[52:55], s[56:59], s[60:63]
UINT, SINT = 20, 21


def translate(instructions):
    return lower(instructions, 20, 24, [1, 2, 3, 4], constant_descriptor=64, buffer_descriptors=VSHARP_OFFSETS)


def noise(offset, seed):
    x = (offset * 0x2545F491 + seed * 0x9E3779B9) & M32
    x ^= x >> 15
    x = (x * 0x2C1B3C6D) & M32
    return x ^ (x >> 12)


@functools.lru_cache(maxsize=None)
def initial_bytes(size, seed):
    return b"".join(struct.pack("<I", noise(o, seed)) for o in range(0, size, 4))


def initial_slot(size, seed):
    return bytearray(initial_bytes(size, seed))


def data(k):
    d0 = (k * C1) & M32
    d1 = d0 ^ C2
    return d0, d1, (d0 + d1) & M32, d1 ^ k


def vsharp(base, stride, records, select, fmt=0):
    return (base & M32, (base >> 32) | stride << 16, records, select << 28 | fmt << 12 | 0xfac)


def program(*body):
    """with_constants around body; the key is computed into v22 and the data words into v30 to v33. The two scalings of
    the coordinate run in whole-quad mode, where the interpolated coordinate may be read."""
    lines = with_constants([
        "v_cvt_u32_f32_e32 v20, v20", "v_cvt_u32_f32_e32 v21, v21", "v_lshl_or_b32 v22, v21, 6, v20",
        "v_mul_lo_u32 v30, v22, s44", "v_xor_b32_e32 v31, s45, v30", "v_add_nc_u32_e32 v32, v30, v31",
        "v_xor_b32_e32 v33, v22, v31",
        "s_load_dwordx4 s[52:55], s[20:21], 0x80", "s_load_dwordx4 s[56:59], s[20:21], 0x90",
        "s_load_dwordx4 s[60:63], s[20:21], 0xa0", "s_waitcnt lgkmcnt(0)",
        *body,
        "v_mov_b32_e32 v12, 0.5", "v_mov_b32_e32 v13, 1.0", "v_mov_b32_e32 v14, 0", "v_mov_b32_e32 v15, 1.0"])
    pos = lines.index("s_and_b64 exec, exec, s[50:51]")
    lines[pos:pos] = ["v_mul_legacy_f32_e32 v20, 0x42800000, v8", "v_mul_legacy_f32_e32 v21, 0x42800000, v9"]
    return lines


class Memory:
    """Slots 0 and 1 as bytearrays, addressed through RANGES like title_va_lookup.hlsli."""

    def __init__(self):
        self.slots = [initial_slot(RSIZE, 3), initial_slot(ASIZE, 11)]

    def locate(self, address):
        for begin, end, slot in RANGES:
            if begin <= address and address + 4 <= end and address % 4 == 0:
                return slot, address - begin
        return None

    def load(self, address):
        hit = self.locate(address % (1 << 64))
        return None if hit is None else int.from_bytes(self.slots[hit[0]][hit[1]:hit[1] + 4], "little")

    def store(self, address, value):
        if hit := self.locate(address % (1 << 64)):
            self.slots[hit[0]][hit[1]:hit[1] + 4] = (value & M32).to_bytes(4, "little")

    def store8(self, address, value):
        address %= 1 << 64
        if hit := self.locate(address & ~3):
            self.slots[hit[0]][hit[1] + (address & 3)] = value & 0xff

    def section(self, initial):
        expected = struct.pack("<2I", 0x45573258, len(self.slots))
        expected += b"".join(struct.pack("<I", len(blob)) + bytes(blob) for blob in self.slots)
        return titlemem.section(RANGES, [bytes(blob) for blob in initial.slots], trailing=expected)


def add(terms, flaws):
    if "nocarry" in flaws:
        return (sum(t >> 32 for t in terms) << 32 | sum(t & M32 for t in terms) & M32) % (1 << 64)
    return sum(terms) % (1 << 64)


def buffer_address(vs, soffset, voffset, inst, index, dword, flaws):
    """The address of one dword of a buffer access, or None when the V# puts it out of range (hlsl.MEMORY_HELPERS)."""
    base, stride, records, select = vs[0] | (vs[1] & 0xffff) << 32, (vs[1] >> 16) & 0x3fff, vs[2], (vs[3] >> 28) & 3
    inst = 0 if "noinst" in flaws else inst
    soffset = 0 if "nosoffset" in flaws else soffset
    offset = voffset + inst + 4 * dword
    in_range = (index < records and offset < stride, index < records, records != 0, offset < records)[select]
    if offset >= 1 << 32 or not (in_range or "nocheck" in flaws):
        return None
    return add([base, soffset, stride * index, offset], flaws)


def sub_store(memory, address, size, word, half, flaws):
    value = word >> 16 if half and "lo_half" not in flaws else word & 0xffff
    if "sub_dword" in flaws:  # the whole zero-extended dword at the aligned address
        memory.store(address & ~3, value & (0xff if size == 1 else 0xffff))
        return
    for n in range(size):
        memory.store8(address + n, value >> (8 * n))


# Constant words 8 to 19: V# A (records with an index check, format 32_UINT), B (raw offsets, 3000 records' worth,
# format 32_SINT) and C (index and offset, OOB_SELECT 0 against the 64-byte stride, format 0, which no typed store writes).
VS_A = vsharp(R0, 64, 4000, 1, UINT)
VS_B = vsharp(R0, 0, 3000 * 64 + 28, 3, SINT)
VS_C = vsharp(R0, 64, KEYS, 0, 0)

BUFFER_BODY = [
    "v_lshlrev_b32_e32 v24, 6, v22", "s_mov_b32 s48, 16", "v_mov_b32_e32 v23, 56",
    "buffer_store_dwordx4 v[30:33], v22, s[52:55], 0 idxen",
    "buffer_store_format_xyzw v[30:33], v22, s[52:55], 0 idxen offset:16",
    "buffer_store_dwordx2 v[31:32], v22, s[52:55], s48 idxen offset:4",
    "buffer_store_dword v33, v24, s[56:59], 0 offen offset:28",
    "tbuffer_store_format_xy v[32:33], v24, s[56:59], 0 format:[BUF_FMT_32_UINT] offen offset:32",
    "buffer_store_byte v31, v24, s[56:59], 0 offen offset:36",
    "buffer_store_byte_d16_hi v31, v24, s[56:59], 0 offen offset:37",
    "buffer_store_short v32, v24, s[56:59], 0 offen offset:39",
    "buffer_store_short_d16_hi v33, v24, s[56:59], 0 offen offset:41 glc slc",
    "buffer_store_format_x v31, v24, s[56:59], 0 offen offset:44",
    "buffer_store_dwordx3 v[30:32], v[22:23], s[60:63], 0 idxen offen",
    "buffer_store_format_x v33, v[22:23], s[60:63], 0 idxen offen",
]


def buffer_reference(flaws=()):
    memory = Memory()
    for k in range(KEYS):
        d = data(k)
        voffset = k << 6

        def dwords(vs, soffset, vo, inst, index, words):
            for j, word in enumerate(words):
                if (address := buffer_address(vs, soffset, vo, inst, index, j, flaws)) is not None:
                    memory.store(address, word)

        def typed(vs, vo, inst, index, words, fmt):
            if fmt not in (UINT, SINT) and "fmt_any" not in flaws:
                return
            dwords(vs, 0, vo, inst, index, words if "fmt_all" in flaws else words[:1])

        def sub(vs, vo, inst, size, word, half):
            if (address := buffer_address(vs, 0, vo, inst, 0, 0, flaws)) is not None:
                sub_store(memory, address, size, word, half, flaws)

        dwords(VS_A, 0, 0, 0, k, d)
        typed(VS_A, 0, 16, k, d, UINT)
        dwords(VS_A, 16, 0, 4, k, d[1:3])
        dwords(VS_B, 0, voffset, 28, 0, d[3:])
        typed(VS_B, voffset, 32, 0, d[2:4], UINT)  # the instruction's format, not the V#'s
        sub(VS_B, voffset, 36, 1, d[1], False)
        sub(VS_B, voffset, 37, 1, d[1], True)
        sub(VS_B, voffset, 39, 2, d[2], False)
        sub(VS_B, voffset, 41, 2, d[3], True)
        typed(VS_B, voffset, 44, 0, d[1:2], SINT)
        dwords(VS_C, 0, 56, 0, k, d[:3])
        typed(VS_C, 56, 0, k, d[3:], 0)
    return memory


GLOBAL_BODY = [
    "v_lshlrev_b32_e32 v24, 6, v22",
    "global_store_dwordx4 v24, v[30:33], s[46:47]",
    "global_store_dwordx3 v24, v[31:33], s[46:47] offset:16",
    "global_store_dwordx2 v24, v[30:31], s[46:47] offset:28",
    "global_store_dword v24, v32, s[46:47] offset:-4",
    "v_add_co_u32 v40, s70, s46, v24", "s_add_u32 s48, s47, 1", "v_mov_b32_e32 v42, s47", "v_mov_b32_e32 v43, s48",
    "v_cndmask_b32_e64 v41, v42, v43, s70",
    "global_store_byte v[40:41], v31, off offset:36",
    "global_store_byte_d16_hi v[40:41], v31, off offset:37",
    "global_store_short v[40:41], v32, off offset:39",
    "global_store_short_d16_hi v[40:41], v33, off offset:41",
    "global_store_dword v[40:41], v30, off offset:44 glc",
    "global_store_dword v[40:41], v33, off offset:2047",
]


def global_reference(flaws=()):
    memory = Memory()
    for k in range(KEYS):
        d = data(k)

        def at(inst, voffset=k << 6):
            inst = 0 if "no_imm" in flaws else inst & M32 if "imm_zext" in flaws else inst
            return add([R0, voffset, inst % (1 << 64)], flaws)

        def dwords(inst, words):
            for j, word in enumerate(words):
                memory.store(add([at(inst), 4 * j], flaws), word)

        dwords(0, d)
        dwords(16, d[1:])
        dwords(28, d[:2])
        dwords(-4, d[2:3])
        sub_store(memory, at(36), 1, d[1], False, flaws)
        sub_store(memory, at(37), 1, d[1], True, flaws)
        sub_store(memory, at(39), 2, d[2], False, flaws)
        sub_store(memory, at(41), 2, d[3], True, flaws)
        dwords(44, d[:1])
        address = at(2047)
        memory.store(address & ~3 if "align" in flaws else address, d[3])
    return memory


# (body, reference, flaws): every flaw must change the expected memory and be rejected by the draw.
PROGRAMS = (
    (BUFFER_BODY, buffer_reference, ["nocheck", "noinst", "nosoffset", "fmt_all", "fmt_any", "sub_dword", "lo_half",
                                     "nocarry"]),
    (GLOBAL_BODY, global_reference, ["no_imm", "imm_zext", "nocarry", "sub_dword", "lo_half", "align"]),
)
CONSTANTS = [0, 0, 0, C1, C2, R0 & M32, R0 >> 32, 0, *VS_A, *VS_B, *VS_C] + [0] * 44


def run_programs(directory, compiler, renderer, backend, family, programs, constants, initial=None):
    """Compile each program, draw it with the right expected memory, then with every wrong one. initial is the memory
    the references start from (the case's initial slots): the plain Memory() unless the family sets words up first."""
    case = directory / f"{family}.case"
    initial = Memory() if initial is None else initial
    for index, (body, reference, flaws) in enumerate(programs):
        source, shader = directory / f"{family}{index}.hlsl", directory / f"{family}{index}.cso"
        source.write_text(translate(program(*body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        case.write_bytes(titlemem.case_file(constants, COLOR, reference().section(initial)))
        subprocess.run(draw, check=True)
        for flaw in flaws:
            case.write_bytes(titlemem.case_file(constants, COLOR, reference({flaw}).section(initial)))
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "memory_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong {family} reference escaped detection in program {index}: {flaw}")


def separated(programs):
    """Every flaw of every program changes the expected memory (needs no GPU)."""
    for index, (_, reference, flaws) in enumerate(programs):
        right = reference().slots
        for flaw in flaws:
            assert reference({flaw}).slots != right, (index, flaw)


def refused_for(reason, function, *args):
    """function(*args) raises ValueError, and for the expected reason (not for an unrelated earlier refusal)."""
    try:
        function(*args)
    except ValueError as error:
        assert reason in str(error), (reason, str(error))
        return
    raise AssertionError(f"{function.__name__} accepted a program refused for {reason}")


def store_controls():
    for body, _, _ in PROGRAMS:
        source = translate(program(*body))
        assert "RWByteAddressBuffer title_memory[8] : register(u0, space1);" in source, source
        assert "ByteAddressBuffer title_memory[8] : register(t0, space1);" not in source.replace("RWByteAddressBuffer", "")
    separated(PROGRAMS)
    store = "buffer_store_dword v30, v22, s[52:55], 0 idxen"
    gstore = "global_store_dword v24, v30, s[46:47]"
    ready = ["v_lshlrev_b32_e32 v24, 6, v22"]
    # CF-2a: no store while this lane may be inactive, nor in whole-quad mode, where helper lanes would write.
    narrowed = ["v_cmp_lt_f32_e64 s[80:81], v12, v13", "s_and_b64 exec, exec, s[80:81]"]
    for bad in (store, gstore, "buffer_store_byte v30, v22, s[52:55], 0 idxen", "global_store_short v24, v30, s[46:47]"):
        translate(program(*ready, bad))
        refused_for("CF-2a", translate, program(*ready, *narrowed, bad))
    quad_store = ["v_mov_b32_e32 v26, 0", "v_mov_b32_e32 v27, 0", "global_store_dword v[26:27], v26, off"]
    for after in (False, True):
        wqm = program(*ready)
        pos = wqm.index("s_and_b64 exec, exec, s[50:51]") + after
        wqm[pos:pos] = quad_store
        translate(wqm) if after else refused_for("CF-2a", translate, wqm)
    for bad in ("buffer_store_dword v30, v22, s[52:55], 0 idxen tfe", "buffer_store_dword v30, v22, s[52:55], 0 idxen lds",
                "buffer_store_dwordx2 v30, v22, s[52:55], 0 idxen", "buffer_store_dwordx2 v[30:32], v22, s[52:55], 0 idxen",
                "buffer_store_dword v30, v22, s[52:55], 0", "buffer_store_dword v30, v22, s[53:56], 0 idxen",
                "buffer_store_dword v30, v22, s[52:55], 0 idxen offset:4096", "buffer_store_dword v29, v22, s[52:55], 0 idxen",
                "buffer_store_byte v[30:31], v22, s[52:55], 0 idxen",
                "buffer_store_format_d16_x v30, v22, s[52:55], 0 idxen",
                "tbuffer_store_format_x v30, v22, s[52:55], 0 idxen",
                "tbuffer_store_format_x v30, v22, s[52:55], 0 format:[BUF_FMT_8_UNORM] idxen",
                "tbuffer_store_format_x v30, v22, s[52:55], 0 format:22 idxen",
                "tbuffer_store_format_x v30, v22, s[52:55], 0 format:[BUF_FMT_32_UINT] format:20 idxen",
                "global_store_dword v24, v30, s[46:47] offset:2048", "global_store_dword v24, v30, s[46:47] offset:-2049",
                "global_store_dword v24, v30, off", "global_store_dword v[24:25], v30, s[46:47]",
                "global_store_dwordx2 v24, v30, s[46:47]", "global_store_byte v24, v[30:31], s[46:47]",
                "global_store_dword v24, v30, s[46:47] tfe", "global_store_dword v24, v30, s[46:47] slc lds",
                "flat_store_dword v[24:25], v30", "scratch_store_dword v24, v30, off"):
        must_reject(translate, program(*ready, bad))
    # A store reads its data registers like any VALU source: not before the load or sample that writes them completes.
    must_reject(translate, program(*ready, "buffer_load_dword v30, v22, s[52:55], 0 idxen", store))
    translate(program(*ready, "buffer_load_dword v30, v22, s[52:55], 0 idxen", "s_waitcnt vmcnt(0)", store))


def controls(directory):
    store_controls()


def binary_fixtures():
    return [(program(*body), translate) for body, _, _ in PROGRAMS]


def draw(directory, compiler, renderer, backend):
    run_programs(directory, compiler, renderer, backend, "stores", PROGRAMS, CONSTANTS)
