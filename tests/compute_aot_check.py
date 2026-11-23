"""Exercise tools/compute_aot.py, card C-1 of docs/design/compute-stage.md, with independently written programs.

Modes, as tests/pixel_aot_check.py has them:
    compute_aot_check.py --list-families
    compute_aot_check.py controls
    compute_aot_check.py binary <llvm-mc> <llvm-objcopy> <libLLVM>
    compute_aot_check.py draw <dxc> <offscreen_check> warp|hardware [--family NAME]...

A draw family translates its programs, compiles them with DXC (cs_6_0), dispatches each case with
`offscreen_check <adapter> --check-compute-case <cso> <case>` (tests/compute_aot_render.cpp) and compares every word of
title memory after the dispatch with a Python reference written on integers and exact fractions. Each family also has
wrong references (a plausible lowering mistake each) that must make the same dispatch report compute_mismatch, and the
controls check, without a GPU, that every wrong reference differs from the right one somewhere and that the lowering
refuses what C-1 does not cover. CTest runs one test per family and adapter (compute_aot_<family>_<adapter>); the
accepted programs are recorded for tools/form_coverage.py as the pixel checks record theirs.
"""
from fractions import Fraction
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE))
import compute_aot  # noqa: E402
from pixel_aot import disassemble  # noqa: E402
from pixel_aot_draws import common  # noqa: E402
from pixel_aot_draws.common import must_reject  # noqa: E402
import pixel_memory_check as titlemem  # noqa: E402

M32 = 0xffffffff
M64 = (1 << 64) - 1


def lower(program, contract):
    """compute_aot.lower_compute, recording the accepted program for the form-coverage record (as the pixel checks'
    lower() does) and asserting that no instruction matches the forms of two families."""
    source = compute_aot.lower_compute(program, **contract)
    common.ACCEPTED.update(line.split()[0] for line in program if line.strip() and not line.endswith(":"))
    for line in program:
        if len(families := common.claimants(line)) > 1:
            raise AssertionError(f"Forms of more than one family match {line!r}: {', '.join(families)}")
    return source


# Title memory as tests/compute_aot_render.cpp and src/title_va_lookup.hlsli see it: a 4-byte access hits when it is
# aligned and lies inside one range; a store that misses is dropped and a load that misses reads 0.
class Memory:
    def __init__(self, ranges, slots):
        self.ranges = list(ranges)
        self.slots = [bytearray(s) for s in slots]

    def locate(self, address):
        if address % 4:
            return None
        for begin, end, slot in self.ranges:
            if begin <= address and address + 4 <= end:
                return slot, address - begin
        return None

    def load(self, address):
        hit = self.locate(address)
        return 0 if hit is None else int.from_bytes(self.slots[hit[0]][hit[1]:hit[1] + 4], "little")

    def store(self, address, value):
        if (hit := self.locate(address)) is not None:
            self.slots[hit[0]][hit[1]:hit[1] + 4] = (value & M32).to_bytes(4, "little")


def case_bytes(groups, constants, ranges, before, after, textures=(), images=()):
    """textures: (index 0|1, width, height, RGBA8 bytes); images: (slot, format 1|4|8, width, height, bytes before,
    bytes expected after), as tests/compute_aot_render.cpp reads them."""
    assert len(constants) == 64 and len(before) == len(after)
    out = struct.pack("<5I", 0x43573258, *groups, 0) + struct.pack("<64I", *constants)
    out += titlemem.section(ranges, before)
    out += struct.pack("<2I", 0x45573258, len(after))
    for blob, old in zip(after, before):
        assert len(blob) == len(old)  # the renderer checks the sizes too
        out += struct.pack("<I", len(blob)) + bytes(blob)
    if textures:
        out += struct.pack("<2I", 0x54573258, len(textures))
        for index, width, height, texels in textures:
            assert len(texels) == 4 * width * height
            out += struct.pack("<3I", index, width, height) + bytes(texels)
    if images:
        out += struct.pack("<2I", 0x49573258, len(images))
        for slot, fmt, width, height, initial, expected in images:
            assert len(initial) == len(expected) == (16 if fmt == 4 else 4) * width * height
            out += struct.pack("<4I", slot, fmt, width, height) + bytes(initial) + bytes(expected)
    return out


def outcome(result):
    """What a dispatch is compared on: title memory after it and every storage image after it."""
    return result[4], tuple(image[5] for image in (result[6] if len(result) > 6 else ()))


def case_of(result, wrong=None):
    groups, constants, ranges, before, after, *extra = result
    textures, images = extra if extra else ((), ())
    if wrong is not None:
        after = wrong[4]
        images = [(*image[:5], other[5]) for image, other in zip(images, wrong[6] if len(wrong) > 6 else ())]
    return case_bytes(groups, constants, ranges, before, after, textures, images)


def vsharp(base, stride, records, select, swizzle=False, add_tid=False):
    assert base >> 48 == 0 and stride < 1 << 14
    noise = (1 << 24) | (0x14 << 12) | 0xfac  # fields a raw store ignores: RESOURCE_LEVEL, FORMAT, DST_SEL
    return (base & M32, (base >> 32) | stride << 16 | swizzle << 31, records, noise | select << 28 | add_tid << 23)


def effective(terms, flaws):
    if "nocarry" in flaws:  # each 32-bit half summed on its own
        return (sum(t >> 32 for t in terms) << 32 | sum(t & M32 for t in terms) & M32) & M64
    return sum(terms) & M64


def buffer_store(memory, vs, soffset, voffset, inst, index, values, flaws=()):
    """A MUBUF store of len(values) dwords under the gfx10 rules of Mesa's ac_set_buf_desc_word3, as
    pixel_aot_draws/load.py's buffer_load reads them: each dword is checked on its own and dropped when out of range."""
    base, stride, records, select = vs[0] | (vs[1] & 0xffff) << 32, (vs[1] >> 16) & 0x3fff, vs[2], (vs[3] >> 28) & 3
    inst, soffset, index = (0 if "noinst" in flaws else inst), (0 if "nosoffset" in flaws else soffset), \
        (0 if "noindex" in flaws else index)
    values = list(values)[::-1] if "swap_dwords" in flaws else list(values)
    writes, dropped = [], False
    for j, value in enumerate(values):
        offset = voffset + inst + 4 * j
        index_out = index > records if "index_gt" in flaws else index >= records
        in_range = (not index_out and not (offset > stride if "isa_offset" in flaws else offset >= stride),
                    not index_out and not ("offset_in_mode1" in flaws and offset >= stride),
                    records != 0 and not ("index_check_mode2" in flaws and index >= records),
                    offset <= records if "le_records" in flaws else offset < records)[select]
        if offset >= 1 << 32 or vs[1] >> 31 or (vs[3] >> 23) & 1 or not (in_range or "nocheck" in flaws):
            dropped = True
            continue
        product = 0 if "nostride" in flaws else stride * index
        product &= M32 if "mul32" in flaws else M64
        writes.append((effective([base, soffset, product, offset], flaws), value))
    if "all_or_nothing" in flaws and dropped:
        return
    for address, value in writes:
        memory.store(address, value)


# Binary32 on exact fractions: round to nearest even with gradual underflow and overflow to infinity, finite only.
def f32_value(bits):
    sign = -1 if bits >> 31 else 1
    exponent, mantissa = (bits >> 23) & 0xff, bits & 0x7fffff
    assert exponent != 0xff
    if exponent == 0:
        return sign * Fraction(mantissa, 1 << 149)
    return sign * Fraction(mantissa | 1 << 23, 1) * Fraction(2) ** (exponent - 150)


def f32_bits(value, zero_sign=0):
    if value == 0:
        return zero_sign << 31
    sign = 1 if value < 0 else 0
    q = abs(value)
    exponent = q.numerator.bit_length() - q.denominator.bit_length()
    if Fraction(2) ** exponent > q:
        exponent -= 1
    exponent = max(exponent, -126)  # below 2^-126 the quantum stays 2^-149
    scaled = q / Fraction(2) ** (exponent - 23)
    n, rest = divmod(scaled.numerator, scaled.denominator)
    if 2 * rest > scaled.denominator or (2 * rest == scaled.denominator and n & 1):
        n += 1
    if n == 1 << 24:
        n, exponent = 1 << 23, exponent + 1
    if exponent > 127:
        return sign << 31 | 0x7f800000
    if n < 1 << 23:  # subnormal
        return sign << 31 | n
    return sign << 31 | (exponent + 127) << 23 | (n - (1 << 23))


def ftz(bits):
    return bits & 0x80000000 if (bits >> 23) & 0xff == 0 else bits


def mul(a, b):
    return f32_bits(f32_value(a) * f32_value(b), (a ^ b) >> 31)


def add(a, b):
    return f32_bits(f32_value(a) + f32_value(b), (a & b) >> 31)


def mac(a, b, c, flaws=()):
    """v_mac_f32 / v_mad_f32: c + a * b with the product rounded first and binary32 denormals flushed (inputs, product
    and result), the rule of hlsl.mad32. 'fused' rounds once; 'noflush' keeps denormals."""
    flush = (lambda x: x) if "noflush" in flaws else ftz
    a, b, c = flush(a), flush(b), flush(c)
    if "fused" in flaws:
        return flush(f32_bits(f32_value(a) * f32_value(b) + f32_value(c), (a ^ b) >> 31 & c >> 31))
    return flush(add(flush(mul(a, b)), c))


def move(register, source):
    """A raw word into a VGPR without a float conversion (as pixel_aot_draws/common.move)."""
    return f"v_or_b32_e64 v{register}, 0, {source}"


def run_family(directory, compiler, renderer, backend, name, programs):
    """Translate, compile and dispatch every program of a family: each case must match, and each wrong reference
    that differs from the right one must be reported as compute_mismatch."""
    for index, (program, contract, cases, reference, flaws) in enumerate(programs):
        source, shader, case = (directory / f"{name}{index}.{ext}" for ext in ("hlsl", "cso", "case"))
        source.write_text(lower(program, contract), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "cs_6_0", "-E", "main", "-Fo", shader, source], check=True)
        dispatch = [renderer, backend, "--check-compute-case", shader, case]
        separated = [False] * len(flaws)
        if name in BATCHED:
            with common.DrawBatch(directory, renderer, backend, shader, f"{name}{index}",
                                  operation="--check-compute-batch") as batch:
                for number, inputs in enumerate(cases):
                    right = reference(inputs, ())
                    batch.add(case_of(right), "pass", f"{name} program {index} case {number} differs from the reference")
                    for k, flaw in enumerate(flaws):
                        wrong = reference(inputs, flaw)
                        if outcome(wrong) == outcome(right):
                            continue
                        separated[k] = True
                        batch.add(case_of(right, wrong), "mismatch",
                                  f"A wrong {name} result escaped detection in program {index}, {sorted(flaw)}")
            assert all(separated), (name, index, separated)
            continue
        for inputs in cases:
            right = reference(inputs, ())
            case.write_bytes(case_of(right))
            subprocess.run(dispatch, check=True)
            for k, flaw in enumerate(flaws):
                wrong = reference(inputs, flaw)
                if outcome(wrong) == outcome(right):
                    continue
                separated[k] = True
                case.write_bytes(case_of(right, wrong))
                result = subprocess.run(dispatch, capture_output=True, text=True)
                if result.returncode != 1 or "compute_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong {name} result escaped detection in program {index}, {sorted(flaw)}")
        assert all(separated), (name, index, separated)
    return 0


def check_separation(name, programs):
    """Without a GPU: every program lowers and every wrong reference differs from the right one in some case."""
    for index, (program, contract, cases, reference, flaws) in enumerate(programs):
        lower(program, contract)
        results = [reference(inputs, ()) for inputs in cases]
        for flaw in flaws:
            assert any(outcome(reference(inputs, flaw)) != outcome(right) for inputs, right in zip(cases, results)), \
                (name, index, sorted(flaw))
        for right in results:
            images = right[6] if len(right) > 6 else ()
            assert right[4] != right[3] or any(image[4] != image[5] for image in images), \
                (name, index, "a case that stores nothing checks nothing")
            case_of(right)  # well formed


# Family `ids`: SV_GroupID and SV_GroupThreadID in the roles of the workgroup-id SGPRs (s3, s4, s5 here, after the
# descriptor-list pointer in s2, as RADV lays them out) and the local-id VGPRs v0, v1, v2. Every thread stores its
# packed group id, packed local id, its flattened index and a constant at 16 * index through one raw V# whose base
# lies 0x600 bytes below 4 GiB, so the stores cross it.
IDS_SIZE, IDS_GROUPS = (4, 2, 2), (3, 2, 2)
IDS_BASE = (1 << 32) - 0x600
IDS_BYTES = 16 * 16 * 12
IDS_PROGRAM = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "v_lshlrev_b32_e32 v3, 8, v1",
    "v_lshl_or_b32 v3, v2, 16, v3",
    "v_or_b32_e32 v9, v0, v3",
    "s_lshl_b32 s1, s4, 8",
    "s_lshl_b32 s6, s5, 16",
    "s_or_b32 s1, s1, s6",
    "s_or_b32 s1, s1, s0",
    "s_lshl_b32 s6, s5, 1",
    "s_add_u32 s6, s6, s4",
    "s_mul_i32 s6, s6, 3",
    "s_add_u32 s6, s6, s0",
    "s_lshl_b32 s6, s6, 4",
    "v_lshl_add_u32 v4, v2, 1, v1",
    "v_lshl_add_u32 v4, v4, 2, v0",
    "v_add_nc_u32_e32 v10, s6, v4",
    "v_mov_b32_e32 v8, s1",
    "v_mov_b32_e32 v11, 0x5eed1d5",
    "v_lshlrev_b32_e32 v12, 4, v10",
    "s_waitcnt lgkmcnt(0)",
    "buffer_store_dwordx4 v[8:11], v12, s[8:11], 0 offen",
    "s_endpgm",
]
IDS_CONTRACT = {"numthreads": IDS_SIZE, "wave": 64, "local_ids": 3,
                "sgprs": {"s2": "descriptors", "s3": "group_id.x", "s4": "group_id.y", "s5": "group_id.z"},
                "buffer_descriptors": {0: 8}}


def ids_reference(inputs, flaws):
    (fill,) = inputs
    before = bytes((fill + 5 * i + (i >> 7)) & 0xff for i in range(IDS_BYTES + 0x40))
    memory = Memory([(IDS_BASE, IDS_BASE + len(before), 0)], [before])
    constants = [0] * 64
    constants[8:12] = vsharp(IDS_BASE, 0, IDS_BYTES, 3)
    rx, ry, rz = IDS_SIZE
    for gz in range(IDS_GROUPS[2]):
        for gy in range(IDS_GROUPS[1]):
            for gx in range(IDS_GROUPS[0]):
                for lz in range(rz):
                    for ly in range(ry):
                        for lx in range(rx):
                            g, l = [gx, gy, gz], [lx, ly, lz]
                            if "no_group" in flaws:
                                g = [0, 0, 0]
                            if "group_xy" in flaws:
                                g = [g[1], g[0], g[2]]
                            if "local_xy" in flaws:
                                l = [l[1], l[0], l[2]]
                            if "no_local_z" in flaws:
                                l[2] = 0
                            if "dispatch_id" in flaws:  # SV_DispatchThreadID where SV_GroupThreadID belongs
                                l = [g[0] * rx + l[0], g[1] * ry + l[1], g[2] * rz + l[2]]
                            flat = ((g[2] * 2 + g[1]) * 3 + g[0]) * 16 + ((l[2] * 2 + l[1]) * 4 + l[0])
                            words = [g[0] | g[1] << 8 | g[2] << 16, (l[0] | l[1] << 8 | l[2] << 16) & M32, flat & M32,
                                     0x5eed1d5]
                            buffer_store(memory, constants[8:12], 0, (16 * flat) & M32, 0, 0, words)
    return IDS_GROUPS, constants, memory.ranges, [before], [bytes(memory.slots[0])]


IDS_PROGRAMS = [(IDS_PROGRAM, IDS_CONTRACT, [(3,), (0x81,)], ids_reference,
                 [{"no_group"}, {"group_xy"}, {"local_xy"}, {"no_local_z"}, {"dispatch_id"}])]


# Family `store`: the V# rules of the four store widths, one thread, every input a runtime word. Entry s16 to s19 are
# the user words 0 to 3 (offsets and indices) and s20 to s27 the user words 16 to 23 (data); the V#s at descriptor-table
# offsets 0 and 0x10 are words 8 to 11 and 12 to 15. Memory is pixel_memory_check's: slot 0 at 0xffffff00 (0x200 bytes,
# across 4 GiB) and slot 1 at 0x200000400 (0x100 bytes), and every store that the rules drop would land inside it, so a
# missing check shows. The references and flaws are pixel_aot_draws/load.py's buffer_load, turned into stores.
STORE_RANGES = ((titlemem.BASE0, titlemem.BASE0 + titlemem.SIZE0, 0), (titlemem.BASE1, titlemem.BASE1 + titlemem.SIZE1, 1))
STORE_CONTRACT = {"numthreads": (1, 1, 1), "wave": 64, "local_ids": 1,
                  "sgprs": {"s2": "descriptors", **{f"s{16 + n}": f"user:{n}" for n in range(4)},
                            **{f"s{20 + n}": f"user:{16 + n}" for n in range(8)}},
                  "buffer_descriptors": {0: 8, 0x10: 12}}
DATA = [0xd0c0b0a0 + 0x01010101 * n for n in range(8)]
ZERO = (0, 0, 0, 0)


def store_program(*lines):
    return ["s_movk_i32 s3, 0x8000", "s_load_dwordx4 s[8:11], s[2:3], null", "s_load_dwordx4 s[12:15], s[2:3], 0x10",
            *(move(24 + n, f"s{20 + n}") for n in range(8)), "s_waitcnt lgkmcnt(0)", *lines, "s_endpgm"]


def store_case(stores):
    """A reference from stores(memory, w, v, flaws): w the four offset words, v the two V#s."""
    def reference(inputs, flaws):
        w, v = inputs
        memory = Memory(STORE_RANGES, titlemem.SLOTS)
        constants = [0] * 64
        constants[0:4] = w
        constants[8:16] = [*v[0], *v[1]]
        constants[16:24] = DATA
        stores(memory, w, v, flaws)
        return (1, 1, 1), constants, memory.ranges, list(titlemem.SLOTS), [bytes(s) for s in memory.slots]
    return reference


def st_addressing(m, w, v, f):
    buffer_store(m, v[0], w[2], w[0], 8, 0, DATA[0:1], f)
    buffer_store(m, v[0], 0, 0, 4, w[1], DATA[1:2], f)
    buffer_store(m, v[0], w[2], w[3], 12, w[1], DATA[2:3], f)
    buffer_store(m, v[0], w[2], 0, 16, 0, DATA[3:4], f)


def st_modes01(m, w, v, f):
    buffer_store(m, v[0], 0, 0, 28, w[0], DATA[0:1], f)
    buffer_store(m, v[0], 0, w[1], 0, 0, DATA[1:2], f)
    buffer_store(m, v[1], 0, 0, 0, w[2], DATA[2:3], f)
    buffer_store(m, v[1], 0, w[3], 0, 0, DATA[3:4], f)


def st_modes23(m, w, v, f):
    buffer_store(m, v[0], 0, w[0], 0, 0, DATA[0:1], f)
    buffer_store(m, v[0], 0, 0, 0, w[1], DATA[1:2], f)
    buffer_store(m, v[1], w[3], w[2], 0, 0, DATA[2:3], f)
    buffer_store(m, v[1], w[3], w[2], 4, 0, DATA[3:4], f)


def st_widths(m, w, v, f):
    order = [(w[0], DATA[0:4]), (w[1], DATA[4:6]), (w[2], DATA[5:8]), (w[3], DATA[4:5])]
    for voffset, values in (order[::-1] if "reverse_order" in f else order):
        buffer_store(m, v[0], 0, voffset, 0, 0, values, f)


def st_carry(m, w, v, f):
    buffer_store(m, v[0], w[0], w[1], 0, 0, DATA[0:4], f)


def st_stride(m, w, v, f):
    buffer_store(m, v[0], 0, 0, 16, w[0], DATA[0:1], f)
    buffer_store(m, v[0], 0, w[1], 4, w[0], DATA[1:2], f)
    buffer_store(m, v[0], w[2], 0, 0, w[0], DATA[2:3], f)


STRIDE_INDEX = 0x50000
STRIDE_BASE = titlemem.BASE1 + 0x80 - 0x3ffc * STRIDE_INDEX  # base + stride * index lands in slot 1 only with all 64 bits
assert 0 < STRIDE_BASE < 1 << 48 and 0x3ffc * STRIDE_INDEX >> 32
BASE0, BASE1 = titlemem.BASE0, titlemem.BASE1

STORE_PROGRAMS = [
    # Structured V# (OOB_SELECT 0, stride 0x20): offen, idxen, both (index first) and neither, soffset (s18) and
    # the instruction offset.
    (store_program(move(18, "s16"), move(19, "s17"), move(22, "s17"), move(23, "s19"),
                   "buffer_store_dword v24, v18, s[8:11], s18 offen offset:8",
                   "buffer_store_dword v25, v19, s[8:11], 0 idxen offset:4",
                   "buffer_store_dword v26, v[22:23], s[8:11], s18 idxen offen offset:12",
                   "buffer_store_dword v27, off, s[8:11], s18 offset:16"),
     STORE_CONTRACT,
     [((4, 3, 0x40, 8), (vsharp(BASE1, 0x20, 8, 0), ZERO)), ((0x10, 5, 0x20, 0), (vsharp(BASE1, 0x20, 8, 0), ZERO))],
     store_case(st_addressing), [{"nosoffset"}, {"nostride"}, {"noinst"}, {"noindex"}]),
    # OOB_SELECT 0 (index < records and offset < stride) and 1 (index < records only): the first case stores the last
    # dword inside each limit, the second the first dword outside it, which must be dropped.
    (store_program(move(18, "s16"), move(19, "s17"), move(20, "s18"), "v_and_b32_e64 v21, 0, s16", move(22, "s19"),
                   "buffer_store_dword v24, v18, s[8:11], 0 idxen offset:28",
                   "buffer_store_dword v25, v19, s[8:11], 0 offen",
                   "buffer_store_dword v26, v20, s[12:15], 0 idxen",
                   "buffer_store_dword v27, v[21:22], s[12:15], 0 idxen offen"),
     STORE_CONTRACT,
     [((3, 0x1c, 5, 0x24), (vsharp(BASE1, 0x20, 4, 0), vsharp(BASE1 + 0x10, 0x10, 6, 1))),
      ((4, 0x20, 6, 0x24), (vsharp(BASE1, 0x20, 4, 0), vsharp(BASE1 + 0x10, 0x10, 6, 1)))],
     store_case(st_modes01), [{"nocheck"}, {"index_gt"}, {"isa_offset"}, {"offset_in_mode1"}]),
    # OOB_SELECT 2 (only num_records == 0 drops; stride 0 ignores the index) and 3 (offset < num_records, soffset
    # outside the check).
    (store_program(move(18, "s16"), move(19, "s17"), move(20, "s18"),
                   "buffer_store_dword v24, v18, s[8:11], 0 offen",
                   "buffer_store_dword v25, v19, s[8:11], 0 idxen",
                   "buffer_store_dword v26, v20, s[12:15], s19 offen",
                   "buffer_store_dword v27, v20, s[12:15], s19 offen offset:4"),
     STORE_CONTRACT,
     [((0x10, 1000, 0x1c, 0x20), (vsharp(BASE0 + 0x40, 0, 1, 2), vsharp(BASE0 + 0x80, 0, 0x20, 3))),
      ((0x10, 1000, 0x18, 0x40), (vsharp(BASE0 + 0x40, 0, 0, 2), vsharp(BASE0 + 0x80, 0, 0x20, 3)))],
     store_case(st_modes23), [{"nocheck"}, {"index_check_mode2"}, {"nosoffset"}, {"le_records"}]),
    # x4, x2 and x3, then one dword over a word the x4 wrote (program order: the later store wins). Each dword is
    # checked on its own: in the second case the windows cross num_records (0x30) and only their first dwords land.
    (store_program(move(18, "s16"), move(19, "s17"), move(20, "s18"), move(21, "s19"),
                   "buffer_store_dwordx4 v[24:27], v18, s[8:11], 0 offen glc slc dlc",
                   "buffer_store_dwordx2 v[28:29], v19, s[8:11], 0 offen",
                   "buffer_store_dwordx3 v[29:31], v20, s[8:11], 0 offen",
                   "buffer_store_dword v28, v21, s[8:11], 0 offen"),
     STORE_CONTRACT,
     [((0x08, 0x18, 0x24, 0x0c), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO)),
      ((0x28, 0x2c, 0x00, 0x2c), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO))],
     store_case(st_widths), [{"swap_dwords"}, {"nocheck"}, {"all_or_nothing"}, {"reverse_order"}]),
    # Address carries: base 0xfffffff0 plus soffset 0x20 crosses 4 GiB, and base plus voffset 8 plus 4 * dword does too.
    (store_program(move(18, "s17"), "buffer_store_dwordx4 v[24:27], v18, s[8:11], s16 offen"),
     STORE_CONTRACT,
     [((0x20, 0, 0, 0), (vsharp(0xfffffff0, 0, 0x100, 3), ZERO)), ((0, 8, 0, 0), (vsharp(0xfffffff0, 0, 0x100, 3), ZERO))],
     store_case(st_carry), [{"nocarry"}]),
    # base + stride * index needs more than 32 bits: 0x3ffc * 0x50000 is above 4 GiB; the base puts the sum in slot 1.
    (store_program(move(18, "s16"), move(22, "s16"), move(23, "s17"),
                   "buffer_store_dword v24, v18, s[8:11], 0 idxen offset:16",
                   "buffer_store_dword v25, v[22:23], s[8:11], 0 idxen offen offset:4",
                   "buffer_store_dword v26, v18, s[8:11], s18 idxen"),
     STORE_CONTRACT,
     [((STRIDE_INDEX, 0x14, 0x20, 0), (vsharp(STRIDE_BASE, 0x3ffc, 0x60000, 0), ZERO))],
     store_case(st_stride), [{"mul32"}, {"nostride"}, {"nosoffset"}]),
]


# Family `integrate`: the two shapes of the corpus's particle-integration shaders (pos += vel * dt over 32-byte
# particles), written here from scratch. Shape A has 64 threads a group, the particle index group * 64 + local x and
# a voffset; shape B has one thread a group (wave32), the index in soffset and dt scaled by a literal first. The
# storage-buffer V# is descriptor 0 (words 8 to 11) and the constant buffer descriptor 0x10 (dt is constant word 0).
PARTICLE_BASE = 0x3_0000_0000
PARTICLES = 256
INTEGRATE_A = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx8 s[8:15], s[2:3], null",
    "v_lshl_add_u32 v0, s0, 6, v0",
    "v_lshlrev_b32_e32 v0, 5, v0",
    "s_waitcnt lgkmcnt(0)",
    "s_clause 0x1",
    "buffer_load_dwordx4 v[4:7], v0, s[8:11], 0 offen",
    "buffer_load_dwordx4 v[8:11], v0, s[8:11], 0 offen offset:16",
    "s_buffer_load_dword s1, s[12:15], null",
    "s_waitcnt vmcnt(0) lgkmcnt(0)",
    "v_mac_f32_e32 v4, s1, v8",
    "v_mac_f32_e32 v5, s1, v9",
    "v_mac_f32_e32 v6, s1, v10",
    "v_mac_f32_e32 v7, s1, v11",
    "buffer_store_dwordx4 v[4:7], v0, s[8:11], 0 offen",
    "s_endpgm",
]
INTEGRATE_B = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx8 s[8:15], s[2:3], null",
    "s_lshl_b32 s0, s0, 5",
    "s_waitcnt lgkmcnt(0)",
    "s_clause 0x1",
    "buffer_load_dwordx4 v[0:3], off, s[8:11], s0",
    "buffer_load_dwordx4 v[4:7], off, s[8:11], s0 offset:16",
    "s_buffer_load_dword s1, s[12:15], null",
    "s_waitcnt lgkmcnt(0)",
    "v_mul_f32_e64 v8, s1, 0x3d4ccccd",
    "s_waitcnt vmcnt(0)",
    "v_mac_f32_e32 v0, v4, v8",
    "v_mac_f32_e32 v1, v5, v8",
    "v_mac_f32_e32 v2, v6, v8",
    "v_mac_f32_e32 v3, v7, v8",
    "buffer_store_dwordx4 v[0:3], off, s[8:11], s0",
    "s_endpgm",
]
INTEGRATE_CONTRACT = {"sgprs": {"s2": "descriptors", "s3": "group_id.x"}, "local_ids": 1, "constant_descriptor": 0x10,
                      "buffer_descriptors": {0: 8}}


def particle_words(seed):
    """Positions in (-8, 8) and velocities in (-4, 4) as binary32 bits, plus particle 5 with position 0 and a denormal
    x velocity (which the unfused multiply-add flushes) and particle 9 with an infinite-free large value."""
    state, out = seed, []
    for n in range(PARTICLES):
        words = []
        for k in range(8):
            state = (state * 1103515245 + 12345) & 0x7fffffff
            exponent = (127 + 2 - (state >> 20) % 6) if k < 4 else (127 + 1 - (state >> 20) % 6)
            words.append((state & 1) << 31 | exponent << 23 | (state * 2654435761 >> 7) & 0x7fffff)
        if n == 5:
            words[0], words[4] = 0, 0x00400000
        out.append(words)
    return out


def integrate_reference(shape):
    def reference(inputs, flaws):
        seed, dt = inputs
        particles = particle_words(seed)
        before = b"".join(struct.pack("<8I", *p) for p in particles)
        memory = Memory([(PARTICLE_BASE, PARTICLE_BASE + len(before), 0)], [before])
        constants = [0] * 64
        constants[0], constants[1] = dt, 0x3f800000
        constants[8:12] = vsharp(PARTICLE_BASE, 0, len(before), 3)
        scale = constants[1] if "dt_word1" in flaws else constants[0]
        if shape == "B":
            scale = mul(scale, 0x3d4ccccd)
        threads = 64 if shape == "A" else 1
        for group in range(PARTICLES // threads):
            for local in range(threads):
                index = (0 if "no_group" in flaws else group) * threads + (0 if "no_local" in flaws else local)
                pos, vel = particles[index][:4], particles[index][4:]
                if "no_offset" in flaws:
                    vel = pos
                values = [mac(scale, v, p, flaws) if shape == "A" else mac(v, scale, p, flaws) for p, v in zip(pos, vel)]
                buffer_store(memory, constants[8:12], 0 if shape == "A" else 32 * index, 32 * index if shape == "A" else 0,
                             0, 0, values)
        return (PARTICLES // threads, 1, 1), constants, memory.ranges, [before], [bytes(memory.slots[0])]
    return reference


INTEGRATE_FLAWS = [{"fused"}, {"noflush"}, {"no_group"}, {"dt_word1"}, {"no_offset"}]
INTEGRATE_PROGRAMS = [
    (INTEGRATE_A, {**INTEGRATE_CONTRACT, "numthreads": (64, 1, 1), "wave": 64}, [(7, 0x3c888889), (1234, 0x3e2aaaab)],
     integrate_reference("A"), [*INTEGRATE_FLAWS, {"no_local"}]),
    (INTEGRATE_B, {**INTEGRATE_CONTRACT, "numthreads": (1, 1, 1), "wave": 32}, [(7, 0x3c888889), (99, 0x3f000001)],
     integrate_reference("B"), INTEGRATE_FLAWS),
]

# Cards C-2 to C-4 (docs/design/compute-stage.md): images, control flow and stage-neutral forms in the compute stage.
def sub(a, b):
    return add(a, b ^ 0x80000000)


def fmax(a, b):
    """v_max_f32 of two finite values (no NaN in these draws); +0 and -0 do not meet."""
    return a if f32_value(a) >= f32_value(b) else b


def unorm8_bits(k):
    """The binary32 a read of the RGBA8_UNORM byte k returns: k / 255 rounded to nearest."""
    return f32_bits(Fraction(k, 255))


def unorm8(bits, flaws=()):
    """The typed store of a binary32 value to an 8-bit UNORM channel: clamp to [0, 1], times 255, rounded to nearest. The
    draws keep the scaled value away from a half, where D3D allows the conversion a tolerance."""
    value = f32_value(bits)
    if "abs" in flaws:
        value = abs(value)
    value = min(max(value, Fraction(0)), Fraction(1)) * 255
    n, rest = divmod(value, 1)
    assert abs(rest - Fraction(1, 2)) > Fraction(1, 10), "a UNORM store near a half is not checked"
    return int(n) + (rest > Fraction(1, 2))


def rgba8_texels(seed, width, height):
    state, out = seed, bytearray()
    for _ in range(width * height * 4):
        state = (state * 1103515245 + 12345) & 0x7fffffff
        out.append((state >> 16) & 0xff)
    return bytes(out)


def texel(texels, width, height, x, y):
    if not (0 <= x < width and 0 <= y < height):
        return None
    at = 4 * (y * width + x)
    return texels[at:at + 4]


def image_put(image, width, x, y, channels):
    at = 4 * (y * width + x)
    image[at:at + 4] = bytes(channels)


# Family `image` (C-2): program A (the corpus's neighbourhood-filter shape) reads a read-only RGBA8 image with image_load,
# once through a non-sequential address at (x - 1, y) and once at (x, y), and stores r = t.r + n.r, g = t.g - n.g and
# b = max(t.b, n.b) with dmask 0x7 to an RGBA8_UNORM storage image, whose alpha the store writes as 0. Both T#s come from
# one s_load_dwordx16. Reads outside the 20x16 image return 0; the 26x17 storage image has texels no thread writes.
# Program B (the corpus's threshold shape) tests the thread against two bounds, skips the rest under s_cbranch_execz and,
# in the skipped region, samples at ((x + 0.5) * sx, (y + 0.5) * sy) with image_sample_lz through the S# at 0x50 (the
# harness's point sampler with clamp addressing) and stores (r, g, 1 - b, 1) under the narrowed EXEC.
IMAGE_A = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx16 s[16:31], s[2:3], null",
    "v_lshl_add_u32 v3, s4, 3, v1",
    "v_lshl_add_u32 v2, s0, 3, v0",
    "v_add_nc_u32_e32 v4, -1, v2",
    "s_waitcnt lgkmcnt(0)",
    "s_clause 0x1",
    "image_load v[6:8], [v4, v3], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D unorm",
    "image_load v[9:12], v[2:3], s[16:23] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
    "s_waitcnt vmcnt(0)",
    "v_add_f32_e32 v14, v9, v6",
    "v_sub_f32_e32 v15, v10, v7",
    "v_max_f32_e32 v16, v11, v8",
    "image_store v[14:16], v[2:3], s[24:31] dmask:0x7 dim:SQ_RSRC_IMG_2D unorm",
    "s_endpgm",
]
IMAGE_A_CONTRACT = {"numthreads": (8, 8, 1), "wave": 64, "local_ids": 2,
                    "sgprs": {"s2": "descriptors", "s3": "group_id.x", "s4": "group_id.y"},
                    "textures": {0: 0}, "storage_images": {0x20: (0, "r8g8b8a8_unorm")}}
TEX_A, OUT_A, GROUPS_A = (20, 16), (26, 17), (3, 2, 1)


def image_a_reference(inputs, flaws):
    seed, = inputs
    tex = rgba8_texels(seed, *TEX_A)
    before = rgba8_texels(seed + 7, *OUT_A)
    out = bytearray(before)
    for y in range(8 * GROUPS_A[1]):
        for x in range(8 * GROUPS_A[0]):
            def load(at_x):
                if "oob_edge" in flaws:
                    at_x = min(max(at_x, 0), TEX_A[0] - 1)
                found = texel(tex, *TEX_A, at_x, y if "oob_edge" not in flaws else min(y, TEX_A[1] - 1))
                return [0] * 4 if found is None else [unorm8_bits(k) for k in found]
            t = load(x)
            n = t if "same_texel" in flaws else load(x - 1)
            channels = [unorm8(add(t[0], n[0])), unorm8(sub(t[1], n[1]), flaws), unorm8(fmax(t[2], n[2])),
                        255 if "alpha_one" in flaws else 0]
            sx, sy = (y, x) if "swap_xy" in flaws else (x, y)
            if sx < OUT_A[0] and sy < OUT_A[1]:
                image_put(out, OUT_A[0], sx, sy, channels)
    return (GROUPS_A, [0] * 64, [], [], [], [(0, *TEX_A, tex)], [(0, 8, *OUT_A, before, bytes(out))])


IMAGE_B = [
    "v_lshl_add_u32 v2, s7, 3, v0",
    "v_lshl_add_u32 v3, s8, 3, v1",
    "v_cmp_gt_u32_e32 vcc, s3, v2",
    "v_cmp_gt_u32_e64 s[0:1], s4, v3",
    "s_and_b64 exec, s[0:1], vcc",
    "s_cbranch_execz BB1",
    "s_movk_i32 s3, 0x8000",
    "s_clause 0x2",
    "s_load_dwordx8 s[8:15], s[2:3], null",
    "s_load_dwordx4 s[16:19], s[2:3], 0x50",
    "s_load_dwordx8 s[24:31], s[2:3], 0x60",
    "v_cvt_f32_u32_e32 v0, v2",
    "v_cvt_f32_u32_e32 v1, v3",
    "v_add_f32_e32 v0, 0.5, v0",
    "v_add_f32_e32 v1, 0.5, v1",
    "v_mul_f32_e32 v0, s5, v0",
    "v_mul_f32_e32 v1, s6, v1",
    "s_waitcnt lgkmcnt(0)",
    "image_sample_lz v[4:6], v[0:1], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D",
    "v_mov_b32_e32 v7, 1.0",
    "s_waitcnt vmcnt(0)",
    "v_sub_f32_e32 v6, 1.0, v6",
    "image_store v[4:7], v[2:3], s[24:31] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
    "BB1:",
    "s_endpgm",
]
IMAGE_B_CONTRACT = {"numthreads": (8, 8, 1), "wave": 64, "local_ids": 2,
                    "sgprs": {"s2": "descriptors", **{f"s{3 + n}": f"user:{n}" for n in range(4)},
                              "s7": "group_id.x", "s8": "group_id.y"},
                    "textures": {0: 0}, "sampler": 0x50, "storage_images": {0x60: (1, "r8g8b8a8_unorm")}}
TEX_B, OUT_B, GROUPS_B = (16, 16), (24, 24), (3, 3, 1)


def image_b_reference(inputs, flaws):
    seed, bound_x, bound_y, scale_y = inputs
    tex = rgba8_texels(seed, *TEX_B)
    before = rgba8_texels(seed + 3, *OUT_B)
    out = bytearray(before)
    constants = [0] * 64
    constants[0:4] = [bound_x, bound_y, 0x3d800000, scale_y]  # sx = 1/16
    for y in range(8 * GROUPS_B[1]):
        for x in range(8 * GROUPS_B[0]):
            inside = x < bound_x and (y < bound_y or "mask_x_only" in flaws)
            if not (inside or "no_mask" in flaws):
                continue
            # Point sampling of a texel-centred coordinate: texel floor(u * 16), clamped to the edge.
            u = f32_value(mul(0x3d800000, add(f32_bits(Fraction(x)), 0x3f000000))) * 16
            v = f32_value(mul(0x3d800000 if "row_scale_x" in flaws else scale_y, add(f32_bits(Fraction(y)), 0x3f000000))) * 16
            tx, ty = int(u), int(v)
            if "wrap" in flaws:
                tx, ty = tx % 16, ty % 16
            found = texel(tex, *TEX_B, min(tx, 15), min(ty, 15))
            r, g, b = (unorm8_bits(k) for k in found[:3])
            channels = [unorm8(r), unorm8(g), unorm8(b if "no_flip" in flaws else sub(0x3f800000, b)), 255]
            image_put(out, OUT_B[0], x, y, channels)
    return (GROUPS_B, constants, [], [], [], [(0, *TEX_B, tex)], [(1, 8, *OUT_B, before, bytes(out))])


# Program C (the corpus's game-of-life update shape): the T# words 1 to 3 read as data (descriptor_data puts the T#'s
# eight words in constant words 16 to 23) give the image size as imageSize does: WIDTH - 1 from word 1 bits 30-31 and
# word 2 bits 0-13, HEIGHT - 1 from word 2 bits 14-29, both shifted right by BASE_LEVEL (word 3 bits 12-15) and at
# least 1, the width 0 for a null descriptor (word 1 zero). Each thread loads the texel mirrored at (w - 1 - x,
# h - 1 - y), then an if/else in whole-wave form (s_mov_b64 exec, vcc; s_cbranch_execz; s_andn2_b64 exec, -1, exec;
# s_mov_b64 exec, -1, which the full 8x8 wave64 workgroup allows): where r > 0.5, (1 - g, g, a); else (2 b, 0, b);
# stored with dmask 0x7 at (x, y).
IMAGE_C = [
    "s_movk_i32 s3, 0x8000",
    "v_lshl_add_u32 v2, s4, 3, v0",
    "v_lshl_add_u32 v3, s5, 3, v1",
    "s_clause 0x1",
    "s_load_dwordx8 s[8:15], s[2:3], null",
    "s_load_dwordx8 s[16:23], s[2:3], 0x20",
    "s_waitcnt lgkmcnt(0)",
    "s_bfe_u32 s0, s9, 0x2001e",
    "s_and_b32 s1, s10, 0x3fff",
    "s_lshl2_add_u32 s1, s1, s0",
    "s_bfe_u32 s6, s10, 0x10000e",
    "s_bfe_u32 s7, s11, 0x4000c",
    "s_add_u32 s1, s1, 1",
    "s_add_u32 s6, s6, 1",
    "s_lshr_b32 s1, s1, s7",
    "s_lshr_b32 s6, s6, s7",
    "s_max_u32 s1, s1, 1",
    "s_max_u32 s6, s6, 1",
    "s_cmp_eq_i32 s9, 0",
    "s_cselect_b32 s1, 0, s1",
    "v_sub_nc_u32_e32 v4, s1, v2",
    "v_add_nc_u32_e32 v4, -1, v4",
    "v_sub_nc_u32_e32 v5, s6, v3",
    "v_add_nc_u32_e32 v5, -1, v5",
    "image_load v[6:9], v[4:5], s[8:15] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
    "s_waitcnt vmcnt(0)",
    "v_cmp_lt_f32_e32 vcc, 0.5, v6",
    "s_mov_b64 exec, vcc",
    "s_cbranch_execz BB4",
    "v_sub_f32_e32 v6, 1.0, v7",
    "v_mov_b32_e32 v8, v9",
    "BB4:",
    "s_andn2_b64 exec, -1, exec",
    "v_mul_f32_e32 v6, 2.0, v8",
    "v_mov_b32_e32 v7, 0",
    "s_mov_b64 exec, -1",
    "image_store v[6:8], v[2:3], s[16:23] dmask:0x7 dim:SQ_RSRC_IMG_2D unorm",
    "s_endpgm",
]
IMAGE_C_CONTRACT = {"numthreads": (8, 8, 1), "wave": 64, "local_ids": 2,
                    "sgprs": {"s2": "descriptors", "s4": "group_id.x", "s5": "group_id.y"},
                    "textures": {0: 0}, "storage_images": {0x20: (0, "r8g8b8a8_unorm")}, "descriptor_data": {0: 16}}
OUT_C = (16, 16)


def tsharp_words(width, height, base_level, null=False):
    """A 2D RGBA8 T# (gfx10 layout, as Mesa's gfx10_make_texture_descriptor writes it) of a width x height image whose
    view starts at base_level; the address and the fields the program does not read are arbitrary."""
    w, h = width - 1, height - 1
    word1 = 0 if null else (w & 3) << 30 | 0x38 << 20 | 0x12
    return [0x2345_6700, word1, w >> 2 | h << 14 | 1 << 31, 0xfac | base_level << 12 | 3 << 16 | 9 << 28,
            0x0007_0000, 0x5a5a_0001, 0, 0x0100_0000]


def image_c_reference(inputs, flaws):
    seed, full, base_level, null = inputs
    width, height = full
    tex_size = (max(width >> base_level, 1), max(height >> base_level, 1))
    tex = rgba8_texels(seed, *tex_size)
    before = rgba8_texels(seed + 5, *OUT_C)
    out = bytearray(before)
    constants = [0] * 64
    constants[16:24] = tsharp_words(width, height, base_level, null)
    shift = 0 if "no_shift" in flaws else base_level
    w = (width - 1 & (3 if "no_word2" in flaws else 0xffff)) + 1
    h = (width if "height_from_width" in flaws else height - 1 + 1)
    w, h = max(w >> shift, 1), max(h >> shift, 1)
    if null:
        w = 0
    for y in range(OUT_C[1]):
        for x in range(OUT_C[0]):
            found = texel(tex, *tex_size, w - 1 - x, h - 1 - y)
            r, g, b, a = [0] * 4 if found is None else [unorm8_bits(k) for k in found]
            then = f32_value(r) > Fraction(1, 2)
            channels = [r, g, b]
            if then:
                channels = [sub(0x3f800000, g), g, a]
            if not then or "else_not_inverted" in flaws:
                channels = [mul(0x40000000, channels[2]), 0, channels[2]]
            if then and "no_restore" in flaws:
                continue
            image_put(out, OUT_C[0], x, y, [unorm8(k) for k in channels] + [0])
    return ((2, 2, 1), constants, [], [], [], [(0, *tex_size, tex)], [(0, 8, *OUT_C, before, bytes(out))])


IMAGE_PROGRAMS = [
    (IMAGE_A, IMAGE_A_CONTRACT, [(5,), (77,)], image_a_reference,
     [{"same_texel"}, {"swap_xy"}, {"alpha_one"}, {"abs"}, {"oob_edge"}]),
    (IMAGE_B, IMAGE_B_CONTRACT, [(9, 21, 19, 0x3d800000), (31, 24, 13, 0x3d000000)], image_b_reference,
     [{"no_mask"}, {"mask_x_only"}, {"wrap"}, {"no_flip"}, {"row_scale_x"}]),
    (IMAGE_C, IMAGE_C_CONTRACT, [(4, (13, 11), 0, False), (8, (27, 20), 1, False), (15, (12, 9), 0, True)],
     image_c_reference, [{"no_word2"}, {"no_shift"}, {"height_from_width"}, {"else_not_inverted"}, {"no_restore"}]),
]


# Family `cf` (C-3): program A (the corpus's particle shape) narrows EXEC with v_cmpx to the threads below a count and
# skips the rest with s_cbranch_execz; inside, s_and_saveexec_b64 narrows it again to the threads whose loaded word is
# even, which store word + 0x100 at offset 4, and s_mov_b64 restores it; then every thread of the outer region stores
# word ^ 0x5a5a5a5a, loads its own offset-4 word back (a load after a store, of this lane's own address) and stores it
# plus its index. Program B runs a uniform SCC loop under an EXEC that v_cmpx narrowed, with no skip branch, through
# forms that write only VGPRs (v_bfe_u32, v_min_u32, v_cvt_f32_u32): an inactive thread must keep its registers and
# store nothing. Both use the V# at descriptor 0 (constant words 8 to 11) over 256 items of 8 bytes.
CF_BASE, CF_ITEMS = 0x2_4000_0000, 256
CF_A = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "v_lshl_add_u32 v0, s0, 6, v0",
    "v_cmpx_gt_u32_e32 s4, v0",
    "s_cbranch_execz BB9",
    "v_lshlrev_b32_e32 v1, 3, v0",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dword v2, v1, s[8:11], 0 offen",
    "s_waitcnt vmcnt(0)",
    "v_and_b32_e32 v3, 1, v2",
    "v_cmp_eq_u32_e32 vcc, 0, v3",
    "s_and_saveexec_b64 s[12:13], vcc",
    "s_cbranch_execz BB3",
    "v_add_nc_u32_e32 v4, 0x100, v2",
    "buffer_store_dword v4, v1, s[8:11], 0 offen offset:4",
    "BB3:",
    "s_mov_b64 exec, s[12:13]",
    "v_xor_b32_e32 v5, 0x5a5a5a5a, v2",
    "buffer_store_dword v5, v1, s[8:11], 0 offen",
    "buffer_load_dword v6, v1, s[8:11], 0 offen offset:4",
    "s_waitcnt vmcnt(0)",
    "v_add_nc_u32_e32 v6, v6, v0",
    "buffer_store_dword v6, v1, s[8:11], 0 offen offset:4",
    "BB9:",
    "s_endpgm",
]
CF_B = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "v_lshl_add_u32 v0, s0, 6, v0",
    "v_lshlrev_b32_e32 v1, 3, v0",
    "v_mov_b32_e32 v4, 0",
    "v_cmpx_gt_u32_e32 s4, v0",
    "s_mov_b32 s6, 0",
    "BB1:",
    "v_bfe_u32 v3, v0, s6, 4",
    "v_min_u32_e32 v3, 9, v3",
    "v_add_nc_u32_e32 v4, v4, v3",
    "s_add_u32 s6, s6, 4",
    "s_cmp_lt_u32 s6, s5",
    "s_cbranch_scc1 BB1",
    "v_cvt_f32_u32_e32 v5, v4",
    "s_waitcnt lgkmcnt(0)",
    "buffer_store_dwordx2 v[4:5], v1, s[8:11], 0 offen",
    "s_endpgm",
]
CF_CONTRACT = {"numthreads": (64, 1, 1), "wave": 64, "local_ids": 1,
               "sgprs": {"s2": "descriptors", "s3": "group_id.x", "s4": "user:0", "s5": "user:1"},
               "buffer_descriptors": {0: 8}}


def cf_memory(seed):
    state, words = seed, []
    for _ in range(2 * CF_ITEMS):
        state = (state * 1103515245 + 12345) & 0x7fffffff
        words.append(((state >> 7) * 2654435761) & M32)
    return struct.pack(f"<{2 * CF_ITEMS}I", *words)


def cf_reference(program):
    def reference(inputs, flaws):
        seed, count, limit = inputs
        before = cf_memory(seed)
        memory = Memory([(CF_BASE, CF_BASE + len(before), 0)], [before])
        constants = [0] * 64
        constants[0], constants[1] = count, limit
        constants[8:12] = vsharp(CF_BASE, 0, len(before), 3)
        for idx in range(CF_ITEMS):
            if idx >= count and "no_exec" not in flaws:
                continue
            at = CF_BASE + 8 * idx
            if program == "A":
                word = memory.load(at)
                stale = memory.load(at + 4)
                if (word & 1) == (1 if "inverted" in flaws else 0) or "no_inner" in flaws:
                    memory.store(at + 4, word + 0x100)
                memory.store(at, word ^ 0x5a5a5a5a)
                back = stale if "stale_load" in flaws else memory.load(at + 4)
                memory.store(at + 4, back + (0 if "no_idx" in flaws else idx))
            else:
                total, shift = 0, 0
                while True:
                    field = (idx >> shift) & 15
                    total += field if "no_min" in flaws else min(9, field)
                    shift += 4
                    if shift >= limit or "one_iter" in flaws:
                        break
                memory.store(at, total)
                memory.store(at + 4, f32_bits(Fraction(total)))
        return (CF_ITEMS // 64, 1, 1), constants, memory.ranges, [before], [bytes(memory.slots[0])]
    return reference


CF_PROGRAMS = [
    (CF_A, CF_CONTRACT, [(3, 200, 0), (17, 77, 0)], cf_reference("A"),
     [{"no_exec"}, {"no_inner"}, {"inverted"}, {"stale_load"}, {"no_idx"}]),
    (CF_B, CF_CONTRACT, [(5, 150, 12), (8, 230, 4)], cf_reference("B"), [{"no_exec"}, {"no_min"}, {"one_iter"}]),
]


# Family `neutral` (C-4): stage-neutral VALU and SALU forms in the compute stage, one 32x2 workgroup (wave64), each
# thread on its own 32 bytes: v_pk_fmac_f16 (fused per half), v_pack_b32_f16 with a literal, v_lshrrev_b64 by the
# flattened index (0 to 63), s_mov_b32 of src_scc, v_cndmask_b32 on the uniform mask of s_cselect_b64, v_cmp_class_f32
# of neg(1) (the negative subnormal 0x80000001, class bit 4), v_fma_mixlo_f16 into the local id y register (its high
# half is kept) and s_mov_b32 null, 0. Inputs: v4 and v5 are binary16 pairs, v6 a binary16 pair (the accumulator),
# v7 a binary32 value; the user words s16..s18 are scalar data.
NEUTRAL = [
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "v_lshl_add_u32 v9, v1, 5, v0",
    "v_lshlrev_b32_e32 v10, 5, v9",
    "s_mov_b32 null, 0",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dwordx4 v[4:7], v10, s[8:11], 0 offen",
    "s_cmp_lt_u32 s16, s17",
    "s_mov_b32 s20, src_scc",
    "s_cmp_lg_u32 s18, 0",
    "s_cselect_b64 s[22:23], -1, 0",
    "s_waitcnt vmcnt(0)",
    "v_mov_b32_e32 v12, v6",
    "v_pk_fmac_f16 v12, v4, v5",
    "v_pack_b32_f16 v13, 0x3c33, v4",
    "v_lshrrev_b64 v[14:15], v9, v[4:5]",
    "v_mov_b32_e32 v16, s20",
    "v_cndmask_b32_e64 v17, v4, v5, s[22:23]",
    "v_cmp_class_f32_e64 s[24:25], neg(1), v4",
    "v_cndmask_b32_e64 v18, 0, 1, s[24:25]",
    "v_fma_mixlo_f16 v1, 1.0, v7, -0.5 op_sel_hi:[0,0,1]",
    "v_mov_b32_e32 v19, v1",
    "buffer_store_dwordx4 v[12:15], v10, s[8:11], 0 offen",
    "buffer_store_dwordx4 v[16:19], v10, s[8:11], 0 offen offset:16",
    "s_endpgm",
]
NEUTRAL_CONTRACT = {"numthreads": (32, 2, 1), "wave": 64, "local_ids": 2,
                    "sgprs": {"s2": "descriptors", **{f"s{16 + n}": f"user:{n}" for n in range(3)}},
                    "buffer_descriptors": {0: 8}}


def f16_value(h):
    sign = -1 if h >> 15 else 1
    exponent, mantissa = (h >> 10) & 0x1f, h & 0x3ff
    assert exponent != 0x1f
    if exponent == 0:
        return sign * Fraction(mantissa, 1 << 24)
    return sign * Fraction(mantissa | 1 << 10) * Fraction(2) ** (exponent - 25)


def f16_bits(value, zero_sign=0):
    """binary16 round to nearest even with gradual underflow; an overflow gives infinity."""
    if value == 0:
        return zero_sign << 15
    sign = 1 if value < 0 else 0
    q = abs(value)
    exponent = q.numerator.bit_length() - q.denominator.bit_length()
    if Fraction(2) ** exponent > q:
        exponent -= 1
    exponent = max(exponent, -14)
    scaled = q / Fraction(2) ** (exponent - 10)
    n, rest = divmod(scaled.numerator, scaled.denominator)
    if 2 * rest > scaled.denominator or (2 * rest == scaled.denominator and n & 1):
        n += 1
    if n == 1 << 11:
        n, exponent = 1 << 10, exponent + 1
    if exponent > 15:
        return sign << 15 | 0x7c00
    if n < 1 << 10:
        return sign << 15 | n
    return sign << 15 | (exponent + 15) << 10 | (n - (1 << 10))


def f16_fma(a, b, c, flaws=()):
    if "pk_unfused" in flaws:
        product = f16_value(f16_bits(f16_value(a) * f16_value(b)))
    else:
        product = f16_value(a) * f16_value(b)
    total = product + f16_value(c)
    return f16_bits(total, (a ^ b) >> 15 & c >> 15)


def neutral_half(state):
    """A normal binary16 of magnitude in [2^-4, 2^4): an fma of three of them stays normal and finite."""
    return (state & 1) << 15 | (11 + (state >> 3) % 8) << 10 | (state >> 7) & 0x3ff


def neutral_reference(inputs, flaws):
    seed, s16, s17, s18 = inputs
    base = 0x1_8000_0000
    words, state = [], seed
    for n in range(64):
        row = []
        for k in range(8):
            state = (state * 1103515245 + 12345) & 0x7fffffff
            if k < 3:
                low, high = neutral_half(state), neutral_half(state >> 9)
                row.append(high << 16 | low)
            elif k == 3:
                row.append(((state & 1) << 31) | (124 + (state >> 4) % 6) << 23 | (state * 40503 >> 5) & 0x7fffff)
            else:
                row.append((state * 2654435761) & M32)
        words.append(row)
    before = b"".join(struct.pack("<8I", *row) for row in words)
    memory = Memory([(base, base + len(before), 0)], [before])
    constants = [0] * 64
    constants[0:3] = [s16, s17, s18]
    constants[8:12] = vsharp(base, 0, len(before), 3)
    for index in range(64):
        a, b, c, d = words[index][:4]
        lanes = [f16_fma((a >> s) & 0xffff, (b >> s) & 0xffff, (c >> s) & 0xffff, flaws) for s in (0, 16)]
        packed = lanes[0] | lanes[1] << 16
        pack = (0x3c33 << 16 | (a & 0xffff)) if "pack_swap" in flaws else ((a & 0xffff) << 16 | 0x3c33)
        wide = (b << 32 | a) >> (index & (31 if "shift32" in flaws else 63))
        scc = int(s16 < s17) ^ (1 if "scc_inverted" in flaws else 0)
        chosen = b if s18 != 0 else a
        class_bit = (a >> (3 if "class_bit3" in flaws else 4)) & 1
        mix = f16_bits(f32_value(d) + Fraction(1, 2) * (1 if "mix_no_neg" in flaws else -1))
        out = [packed, pack, wide & M32, wide >> 32 & M32, scc, chosen, class_bit, mix]
        for k, word in enumerate(out):
            memory.store(base + 32 * index + 4 * k, word)
    return (1, 1, 1), constants, memory.ranges, [before], [bytes(memory.slots[0])]


NEUTRAL_PROGRAMS = [
    (NEUTRAL, NEUTRAL_CONTRACT, [(11, 3, 9, 0), (4242, 9, 3, 5)], neutral_reference,
     [{"pk_unfused"}, {"pack_swap"}, {"shift32"}, {"scc_inverted"}, {"class_bit3"}, {"mix_no_neg"}]),
]


# Family `lanes` (C-7): v_readfirstlane_b32 of a wave-uniform value. Program A (the corpus's shading-rate shape): 8x8
# workgroups (wave64) narrow EXEC to the threads inside two bounds and skip the rest with s_cbranch_execz; inside, two
# values built only from constant words are rounded (v_rndne_f32), converted and read with v_readfirstlane_b32 while
# EXEC is narrowed, so their VGPRs hold masked writes (an inactive thread keeps the value from before the region). The
# first, clamped to at least 1 by s_max_u32, is the trip count of a uniform loop; the second is stored. Program B (the
# corpus's headless shape): one-thread workgroups load a count at the group's own address, read it with
# v_readfirstlane_b32 into an SGPR and run a scalar Fibonacci loop on it (one lane per wave: the first active lane is
# the thread itself). Both use the V# at descriptor 0 (constant words 8 to 11).
LANES_A = [
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[12:15], s[2:3], null",
    "v_lshl_add_u32 v2, s8, 3, v0",
    "v_lshl_add_u32 v3, s9, 3, v1",
    "v_cvt_f32_u32_e32 v1, s6",
    "v_cvt_f32_u32_e32 v5, s4",
    "v_cmp_gt_u32_e32 vcc, s4, v2",
    "v_cmp_gt_u32_e64 s[0:1], s5, v3",
    "s_and_b64 exec, vcc, s[0:1]",
    "s_cbranch_execz BB9",
    "v_mul_f32_e32 v1, s7, v1",
    "v_mul_f32_e32 v5, 0x3e800000, v5",
    "v_rndne_f32_e32 v1, v1",
    "v_rndne_f32_e32 v5, v5",
    "v_cvt_u32_f32_e32 v1, v1",
    "v_cvt_u32_f32_e32 v5, v5",
    "v_readfirstlane_b32 s0, v1",
    "v_readfirstlane_b32 s1, v5",
    "s_max_u32 s0, 1, s0",
    "v_mov_b32_e32 v6, 0",
    "s_mov_b32 s10, 0",
    "BB2:",
    "s_cmp_ge_u32 s10, s0",
    "s_cbranch_scc1 BB4",
    "v_xor_b32_e32 v7, s10, v3",
    "v_lshl_add_u32 v6, v6, 1, v7",
    "s_add_u32 s10, s10, 1",
    "s_branch BB2",
    "BB4:",
    "v_mov_b32_e32 v7, s1",
    "v_lshl_add_u32 v8, v3, 4, v2",
    "v_lshlrev_b32_e32 v8, 3, v8",
    "s_waitcnt lgkmcnt(0)",
    "buffer_store_dwordx2 v[6:7], v8, s[12:15], 0 offen",
    "BB9:",
    "s_endpgm",
]
LANES_A_CONTRACT = {"numthreads": (8, 8, 1), "wave": 64, "local_ids": 2,
                    "sgprs": {"s2": "descriptors", **{f"s{4 + n}": f"user:{n}" for n in range(4)},
                              "s8": "group_id.x", "s9": "group_id.y"},
                    "buffer_descriptors": {0: 8}}
LANES_B = [
    "s_cmp_lt_u32 s3, 24",
    "s_cbranch_scc0 BB11",
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[4:7], s[2:3], null",
    "s_lshl_b32 s0, s0, 2",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dword v0, off, s[4:7], s0",
    "s_waitcnt vmcnt(0)",
    "v_readfirstlane_b32 s1, v0",
    "s_cmp_lt_u32 1, s1",
    "s_cbranch_scc0 BB9",
    "s_mov_b32 s2, 1",
    "s_mov_b32 s3, 1",
    "s_mov_b32 s8, 2",
    "BB3:",
    "s_cmp_ge_u32 s8, s1",
    "s_cbranch_scc1 BB7",
    "s_add_u32 s3, s2, s3",
    "s_add_u32 s8, s8, 1",
    "s_xor_b32 s3, s3, s2",
    "s_xor_b32 s2, s3, s2",
    "s_xor_b32 s3, s3, s2",
    "s_branch BB3",
    "BB7:",
    "s_mov_b32 s1, s2",
    "BB9:",
    "v_mov_b32_e32 v0, s1",
    "buffer_store_dword v0, off, s[4:7], s0",
    "BB11:",
    "s_endpgm",
]
LANES_B_CONTRACT = {"numthreads": (1, 1, 1), "wave": 64, "local_ids": 1,
                    "sgprs": {"s2": "descriptors", "s3": "group_id.x"}, "buffer_descriptors": {0: 8}}
LANES_BASE = 0x3_0000_1000


def rndne_u32(bits, flaws):
    """v_rndne_f32 then v_cvt_u32_f32 of a finite non-negative value (truncation in the wrong reference)."""
    value = f32_value(bits)
    n, rest = divmod(value.numerator, value.denominator)
    if "truncate" not in flaws and (2 * rest > value.denominator or (2 * rest == value.denominator and n & 1)):
        n += 1
    return n


def lanes_a_reference(inputs, flaws):
    seed, bound_x, bound_y, count, scale = inputs
    before = cf_memory(seed)[:8 * 256]
    memory = Memory([(LANES_BASE, LANES_BASE + len(before), 0)], [before])
    constants = [0] * 64
    constants[0:4] = [bound_x, bound_y, count, scale]
    constants[8:12] = vsharp(LANES_BASE, 0, len(before), 3)
    trips = rndne_u32(mul(scale, f32_bits(Fraction(count))), flaws)
    second = rndne_u32(mul(0x3e800000, f32_bits(Fraction(bound_x))), flaws)
    if "swap" in flaws:
        trips, second = second, trips
    if "no_max" not in flaws:
        trips = max(1, trips)
    for y in range(16):
        for x in range(16):
            if not (x < bound_x and y < bound_y) and "no_mask" not in flaws:
                continue
            total = 0
            for k in range(trips):
                total = (total << 1) + (y ^ k) & M32
            memory.store(LANES_BASE + 8 * (16 * y + x), total)
            memory.store(LANES_BASE + 8 * (16 * y + x) + 4, second)
    return (2, 2, 1), constants, memory.ranges, [before], [bytes(memory.slots[0])]


def lanes_b_reference(inputs, flaws):
    seed, = inputs
    counts = [(seed * 37 + 11 * n) % 48 for n in range(32)]
    counts[3], counts[5] = 0, 1
    before = struct.pack("<32I", *counts)
    memory = Memory([(LANES_BASE, LANES_BASE + len(before), 0)], [before])
    constants = [0] * 64
    constants[8:12] = vsharp(LANES_BASE, 0, len(before), 3)
    for group in range(32):
        if group >= 24 and "no_bound" not in flaws:
            continue
        n = 0 if "read_zero" in flaws else counts[group]
        if n > 1:
            a, b = 1, 1
            for _ in range(2, n - (1 if "one_less" in flaws else 0)):
                a, b = (a + b) & M32, a
            n = a
        memory.store(LANES_BASE + 4 * group, n)
    return (32, 1, 1), constants, memory.ranges, [before], [bytes(memory.slots[0])]


LANES_PROGRAMS = [
    (LANES_A, LANES_A_CONTRACT, [(3, 13, 9, 7, 0x3f000000), (21, 10, 16, 1, 0x3e800000)], lanes_a_reference,
     [{"no_mask"}, {"no_max"}, {"truncate"}, {"swap"}]),
    (LANES_B, LANES_B_CONTRACT, [(5,), (12,)], lanes_b_reference, [{"no_bound"}, {"read_zero"}, {"one_less"}]),
]


# Family `dynsmem`: s_buffer_load_dword* at a run-time SGPR byte offset (docs/design/compute-stage.md, dynamic scalar
# constant loads). Program A reads, per group g, the words at byte (4g | (g & 3)) + 8 and +12 (x2) and at the same
# offset (x1): the two low bits are ignored, and a dword that is not wholly inside the 64 bound words reads 0, dword by
# dword. Program B is the 16bit_arithmetic shape: an outer loop reloads the constant V# and loads two words at
# 8i + 4g, the loop's offset register changes while the load is outstanding, and the words are read only in an
# innermost loop that may run no trip (the load stays outstanding across the back edges), whose counter reuses a V#
# register.
DYNSMEM_BASE = 0x2_0000_4000
DYNSMEM_CONTRACT = {"numthreads": (1, 1, 1), "wave": 64, "local_ids": 1,
                    "sgprs": {"s2": "descriptors", "s3": "group_id.x"}, "buffer_descriptors": {0: 8},
                    "constant_descriptor": 0x10}
DYNSMEM_A = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx8 s[8:15], s[2:3], null",
    "s_lshl_b32 s1, s0, 2",
    "s_and_b32 s6, s0, 3",
    "s_or_b32 s1, s1, s6",
    "s_lshl_b32 s7, s0, 4",
    "s_waitcnt lgkmcnt(0)",
    "s_buffer_load_dwordx2 s[4:5], s[12:15], s1 offset:0x8",
    "s_buffer_load_dword s16, s[12:15], s1",
    "s_waitcnt lgkmcnt(0)",
    "v_mov_b32_e32 v0, s4",
    "v_mov_b32_e32 v1, s5",
    "v_mov_b32_e32 v2, s16",
    "buffer_store_dwordx3 v[0:2], off, s[8:11], s7",
    "s_endpgm",
]
DYNSMEM_B = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "s_mov_b32 s16, 0",
    "v_mov_b32_e32 v1, 0",
    "BB1:",
    "s_cmp_ge_u32 s16, s4",
    "s_cbranch_scc1 BB15",
    "s_waitcnt lgkmcnt(0)",
    "s_load_dwordx4 s[12:15], s[2:3], 0x10",
    "s_lshl_b32 s17, s16, 3",
    "s_lshl_b32 s6, s0, 2",
    "s_add_u32 s17, s17, s6",
    "s_waitcnt lgkmcnt(0)",
    "s_buffer_load_dwordx2 s[12:13], s[12:15], s17",
    "s_add_u32 s17, s17, 4",
    "s_mov_b32 s18, 0",
    "BB5:",
    "s_cmp_ge_u32 s18, 2",
    "s_cbranch_scc1 BB14",
    "s_mov_b32 s15, 0",
    "BB9:",
    "s_cmp_ge_u32 s15, s5",
    "s_cbranch_scc1 BB13",
    "s_waitcnt lgkmcnt(0)",
    "v_add_nc_u32_e32 v1, s12, v1",
    "v_xor_b32_e32 v1, s13, v1",
    "v_add_nc_u32_e32 v1, s17, v1",
    "v_lshl_add_u32 v1, v1, 1, s15",
    "s_add_u32 s15, s15, 1",
    "s_branch BB9",
    "BB13:",
    "s_add_u32 s18, s18, 1",
    "s_branch BB5",
    "BB14:",
    "s_add_u32 s16, s16, 1",
    "s_branch BB1",
    "BB15:",
    "s_lshl_b32 s1, s0, 2",
    "s_waitcnt lgkmcnt(0)",
    "buffer_store_dword v1, off, s[8:11], s1",
    "s_endpgm",
]
DYNSMEM_B_CONTRACT = {**DYNSMEM_CONTRACT, "sgprs": {"s2": "descriptors", "s3": "group_id.x", "s4": "user:60",
                                                    "s5": "user:61"}}


def dynsmem_constants(seed):
    return [(0x9e3779b1 * (n + 1) + seed * 0x1003f) & M32 for n in range(64)]


def dynsmem_word(constants, offset, flaws, whole=None):
    """The dword s_buffer_load reads at byte `offset` past the cleared low bits: 0 unless it lies inside the 256 bound
    bytes. whole: the bytes the load reads in all (the wrong reference that zeroes a load with any dword outside)."""
    if "nozero" in flaws:
        return constants[(offset >> 2) % 64]
    if offset + 4 > 256 or (whole is not None and whole > 256):
        return 0
    return constants[offset >> 2]


def dynsmem_a_reference(inputs, flaws):
    seed, = inputs
    groups = 72
    before = bytes((seed * 7 + 3 * i) & 0xff for i in range(16 * groups))
    memory = Memory([(DYNSMEM_BASE, DYNSMEM_BASE + len(before), 0)], [before])
    constants = dynsmem_constants(seed)
    constants[8:12] = vsharp(DYNSMEM_BASE, 0, len(before), 3)
    for g in range(groups):
        soffset = 4 * g | g & 3
        base = 0 if "ignored" in flaws else 4 * soffset if "dwords" in flaws else soffset & ~3
        if "unmasked" in flaws:
            # The low bits kept: the range check sees the byte offset as given.
            words = [0 if soffset + at + 4 > 256 else constants[(soffset + at) >> 2] for at in (8, 12, 0)]
        else:
            whole = [base + 16, base + 16, base + 4] if "whole" in flaws else [None] * 3
            words = [dynsmem_word(constants, base + at, flaws, end) for at, end in zip((8, 12, 0), whole)]
        for j, word in enumerate(words):
            memory.store(DYNSMEM_BASE + 16 * g + 4 * j, word)
    return (groups, 1, 1), constants, memory.ranges, [before], [bytes(memory.slots[0])]


def dynsmem_b_reference(inputs, flaws):
    seed, outer, inner = inputs
    groups = 8
    before = bytes((seed * 5 + 11 * i) & 0xff for i in range(4 * groups))
    memory = Memory([(DYNSMEM_BASE, DYNSMEM_BASE + len(before), 0)], [before])
    constants = dynsmem_constants(seed)
    constants[8:12] = vsharp(DYNSMEM_BASE, 0, len(before), 3)
    constants[60:62] = [outer, inner]
    for g in range(groups):
        acc = 0
        for i in range(outer):
            offset = 0 if "ignored" in flaws else 8 * (0 if "stale" in flaws else i) + 4 * g
            if "late" in flaws:
                offset += 4  # the offset register read when the words are used, after it changed
            whole = offset + 8 if "whole" in flaws else None
            w0, w1 = (dynsmem_word(constants, offset + 4 * j, flaws, whole) for j in range(2))
            after = 8 * i + 4 * g + 4
            for _ in range(2):
                for c in range(inner):
                    acc = ((((acc + w0) & M32) ^ w1) + after) & M32
                    acc = (2 * acc + c) & M32
        memory.store(DYNSMEM_BASE + 4 * g, acc)
    return (groups, 1, 1), constants, memory.ranges, [before], [bytes(memory.slots[0])]


DYNSMEM_PROGRAMS = [
    (DYNSMEM_A, DYNSMEM_CONTRACT, [(1,), (6,)], dynsmem_a_reference,
     [{"ignored"}, {"nozero"}, {"whole"}, {"dwords"}, {"unmasked"}]),
    (DYNSMEM_B, DYNSMEM_B_CONTRACT, [(2, 31, 2), (3, 6, 0), (4, 3, 1)], dynsmem_b_reference,
     [{"ignored"}, {"nozero"}, {"whole"}, {"late"}, {"stale"}]),
]


# Family `lds` (card C-6, docs/design/compute-stage.md): groupshared LDS, s_barrier and the LDS wait count. Program A,
# 256 threads (four wave64 waves; several desktop waves too): each thread writes its word to A[t] and a marker to B[t]
# through computed addresses, rewrites B[t] through the offset field after a barrier, and after a second barrier reads
# the partner t' = 255 - t's B and A words and A[t' + 1], A[t' + 64] by ds_read2_b32. Program B, 64x2 threads: private
# initial words, then nine epochs of one LDS atomic each (add, sub, min/max unsigned and signed, and, or, xor) on eight
# shared words per operation, separated by barriers, and every thread reads its own word back. Program C, one-thread
# groups (no barrier needed): every width of ds_write and ds_read, sub-dword writes and sign-extending reads,
# ds_write2/ds_read2 with b32, b64 and st64 offsets, and out-of-range dwords at run-time addresses (reads 0, writes
# dropped) up to and past the 1 KiB allocation. Program D, the Sascha Willems n-body shape: a region skipped by waves
# with no particle, a uniform loop over chunks that fills LDS (an else arm writes zeros), a barrier, a uniform inner
# loop that reads LDS at a uniform address into SGPRs with v_readfirstlane_b32 (C-7 after C-6), and a second barrier.
LDS_BASE = 0x3_0000_8000
LDS_GROUPS_CONTRACT = {"wave": 64, "sgprs": {"s2": "descriptors", "s3": "group_id.x"}, "buffer_descriptors": {0: 8}}
LDS_A = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "v_lshl_add_u32 v1, s0, 8, v0",
    "v_lshlrev_b32_e32 v2, 2, v1",
    "v_lshlrev_b32_e32 v3, 2, v0",
    "v_add_nc_u32_e32 v9, 0x400, v3",
    "v_or_b32_e32 v5, 0x5a5a0000, v0",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dword v4, v2, s[8:11], 0 offen",
    "s_waitcnt vmcnt(0)",
    "ds_write_b32 v3, v4",
    "ds_write_b32 v9, v5",
    "s_barrier",
    "v_lshl_add_u32 v6, v4, 1, v4",
    "ds_write_b32 v3, v6 offset:1024",
    "s_barrier",
    "v_xor_b32_e32 v7, 0x3fc, v3",
    "v_add_nc_u32_e32 v8, 0x400, v7",
    "ds_read_b32 v10, v8",
    "ds_read_b32 v11, v7",
    "ds_read2_b32 v[12:13], v7 offset0:1 offset1:64",
    "v_lshlrev_b32_e32 v14, 4, v1",
    "s_waitcnt lgkmcnt(0)",
    "buffer_store_dwordx4 v[10:13], v14, s[8:11], 0 offen offset:2048",
    "s_endpgm",
]
LDS_A_CONTRACT = {**LDS_GROUPS_CONTRACT, "numthreads": (256, 1, 1), "local_ids": 1, "lds_size": 4096}
LDS_B_OPS = ("add_u32", "sub_u32", "min_u32", "max_u32", "min_i32", "max_i32", "and_b32", "or_b32", "xor_b32")
LDS_B = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "v_lshl_add_u32 v2, v1, 6, v0",
    "v_lshl_add_u32 v3, s0, 7, v2",
    "v_lshlrev_b32_e32 v3, 2, v3",
    "v_lshlrev_b32_e32 v4, 2, v2",
    "v_and_b32_e32 v5, 7, v2",
    "v_lshlrev_b32_e32 v5, 2, v5",
    "v_lshl_or_b32 v7, v2, 25, v2",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dword v6, v3, s[8:11], 0 offen",
    "ds_write_b32 v4, v7",
    "s_waitcnt vmcnt(0)",
    *(line for k, op in enumerate(LDS_B_OPS) for line in
      ("s_barrier", f"ds_{op} v5, v6" + (f" offset:{32 * k}" if k else ""))),
    "s_barrier",
    "ds_read_b32 v8, v4",
    "s_waitcnt lgkmcnt(0)",
    "buffer_store_dword v8, v3, s[8:11], 0 offen offset:1024",
    "s_endpgm",
]
LDS_B_CONTRACT = {**LDS_GROUPS_CONTRACT, "numthreads": (64, 2, 1), "local_ids": 2, "lds_size": 512}
LDS_C = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "s_lshl_b32 s1, s0, 4",
    "s_lshl_b32 s4, s0, 7",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dwordx4 v[0:3], off, s[8:11], s1",
    "s_waitcnt vmcnt(0)",
    "v_lshlrev_b32_e32 v4, 4, v0",
    "ds_write_b128 v4, v[0:3]",
    "ds_write_b96 v4, v[1:3] offset:16",
    "ds_write_b64 v4, v[2:3] offset:32",
    "ds_write_b32 v4, v1 offset:40",
    "ds_write_b8 v4, v3 offset:17",
    "ds_write_b16 v4, v2 offset:26",
    "ds_write2_b32 v4, v3, v1 offset0:11 offset1:12",
    "ds_write2st64_b64 v4, v[2:3], v[0:1] offset1:1",
    "ds_read_b128 v[8:11], v4",
    "ds_read_b96 v[12:14], v4 offset:16",
    "ds_read2_b64 v[16:19], v4 offset0:4 offset1:5",
    "ds_read_u8 v20, v4 offset:17",
    "ds_read_i8 v21, v4 offset:17",
    "ds_read_u16 v22, v4 offset:26",
    "ds_read_i16 v23, v4 offset:26",
    "ds_read2st64_b32 v[24:25], v4 offset1:2",
    "ds_read2_b32 v[26:27], v4 offset0:11 offset1:12",
    "s_waitcnt lgkmcnt(0)",
    "buffer_store_dwordx4 v[8:11], off, s[8:11], s4 offset:1024",
    "buffer_store_dwordx3 v[12:14], off, s[8:11], s4 offset:1040",
    "buffer_store_dwordx4 v[16:19], off, s[8:11], s4 offset:1052",
    "buffer_store_dwordx4 v[20:23], off, s[8:11], s4 offset:1068",
    "buffer_store_dwordx4 v[24:27], off, s[8:11], s4 offset:1084",
    "s_endpgm",
]
LDS_C_CONTRACT = {**LDS_GROUPS_CONTRACT, "wave": 32, "numthreads": (1, 1, 1), "local_ids": 1, "lds_size": 1024}
LDS_D = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[4:7], s[2:3], 0x10",
    "s_waitcnt lgkmcnt(0)",
    "s_buffer_load_dword s1, s[4:7], 0x4",
    "v_lshl_add_u32 v1, s0, 7, v0",
    "s_lshl_b32 s16, s0, 7",
    "s_waitcnt lgkmcnt(0)",
    "s_sub_u32 s16, s1, s16",
    "s_min_u32 s16, s16, 0x80",
    "v_cmpx_gt_u32_e32 s1, v1",
    "s_cbranch_execz BB9",
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "v_lshlrev_b32_e32 v1, 5, v1",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dword v2, v1, s[8:11], 0 offen",
    "s_mov_b32 s0, 0",
    "v_mov_b32_e32 v7, 0",
    "BB2:",
    "s_cmp_ge_u32 s0, s1",
    "s_cbranch_scc1 BB8",
    "v_add_nc_u32_e32 v8, s0, v0",
    "s_mov_b64 s[2:3], exec",
    "v_cmpx_gt_u32_e32 s1, v8",
    "s_cbranch_execz BB5",
    "v_lshlrev_b32_e32 v8, 5, v8",
    "buffer_load_dwordx4 v[8:11], v8, s[8:11], 0 offen",
    "v_lshlrev_b32_e32 v12, 4, v0",
    "s_waitcnt vmcnt(0)",
    "ds_write_b128 v12, v[8:11]",
    "BB5:",
    "s_andn2_b64 exec, s[2:3], exec",
    "s_cbranch_execz BB7",
    "v_lshlrev_b32_e32 v8, 4, v0",
    "v_mov_b32_e32 v12, 0",
    "v_mov_b32_e32 v13, 0",
    "v_mov_b32_e32 v14, 0",
    "v_mov_b32_e32 v15, 0",
    "ds_write_b128 v8, v[12:15]",
    "BB7:",
    "s_mov_b64 exec, s[2:3]",
    "s_barrier",
    "s_mov_b32 s2, 0",
    "BB10:",
    "s_cmp_ge_u32 s2, s16",
    "s_cbranch_scc1 BB12",
    "s_lshl_b32 s3, s2, 4",
    "v_mov_b32_e32 v8, s3",
    "ds_read_b64 v[8:9], v8",
    "s_add_u32 s2, s2, 1",
    "s_waitcnt lgkmcnt(0)",
    "v_readfirstlane_b32 s12, v8",
    "v_readfirstlane_b32 s13, v9",
    "s_waitcnt vmcnt(0)",
    "v_xor_b32_e32 v9, s12, v2",
    "v_add_nc_u32_e32 v7, v7, v9",
    "v_add_nc_u32_e32 v7, s13, v7",
    "s_branch BB10",
    "BB12:",
    "s_barrier",
    "s_addk_i32 s0, 0x80",
    "s_branch BB2",
    "BB8:",
    "buffer_store_dword v7, v1, s[8:11], 0 offen offset:16",
    "BB9:",
    "s_endpgm",
]
LDS_D_CONTRACT = {**LDS_GROUPS_CONTRACT, "numthreads": (128, 1, 1), "local_ids": 1, "lds_size": 2048,
                  "constant_descriptor": 0x10}


def lds_words(seed, count):
    """Words with every byte pattern a sub-dword read must keep apart (high bits, sign bits)."""
    out, state = [], (seed * 0x9e3779b9 + 0x7f4a7c15) & M32
    for _ in range(count):
        state = (state * 1664525 + 1013904223) & M32
        out.append(state ^ (state >> 13))
    return out


def lds_memory(words, out_bytes):
    before = struct.pack(f"<{len(words)}I", *words) + bytes(out_bytes)
    return Memory([(LDS_BASE, LDS_BASE + len(before), 0)], [before]), before


def lds_constants(size):
    constants = [0] * 64
    constants[8:12] = vsharp(LDS_BASE, 0, size, 3)
    return constants


def lds_a_reference(inputs, flaws):
    seed, = inputs
    xs = lds_words(seed, 512)
    memory, before = lds_memory(xs, 16 * 512)
    for group in range(2):
        x = xs[256 * group:256 * group + 256]
        a, b = list(x), [0x5a5a0000 | t for t in range(256)]
        marker = list(b)
        w = [(3 * v) & M32 for v in x]
        if "offset" in flaws:
            a = w  # the offset field dropped: the second write lands in A
        else:
            b = w
        seen_b = marker if "barrier" in flaws else b  # the partner's rewrite not yet visible
        step = {"stride8": 8, "stride1": 1}.get(next(iter(flaws), ""), 4)
        for t in range(256):
            tp = 255 - t
            slots = a + seen_b
            words = [seen_b[tp], a[tp], slots[(4 * tp + step) // 4], slots[(4 * tp + 64 * step) // 4]]
            for j, word in enumerate(words):
                memory.store(LDS_BASE + 2048 + 16 * (256 * group + t) + 4 * j, word)
    return (2, 1, 1), lds_constants(len(before)), memory.ranges, [before], [bytes(memory.slots[0])]


def lds_b_reference(inputs, flaws):
    seed, = inputs
    data = lds_words(seed, 256)
    data[0], data[1], data[2] = 0x80000000, 0x7fffffff, 0xffffffff  # signed and unsigned extremes
    memory, before = lds_memory(data, 1024)
    signed = (lambda v: v - (1 << 32) if v & 0x80000000 else v)
    for group in range(2):
        lds = [((t << 25) | t) & M32 for t in range(128)]
        ops = LDS_B_OPS[:-1] if "barrier" in flaws else LDS_B_OPS
        for k, op in enumerate(ops):
            for t in range(128):
                slot = (t & 7) + (0 if "offset" in flaws else 8 * k)
                m, d = lds[slot], data[128 * group + t]
                if op.endswith("i32") and "unsigned" not in flaws:
                    m, d = signed(m), signed(d)
                value = {"add_u32": m + d, "sub_u32": m - d if "sub_add" not in flaws else m + d,
                         "min_u32": min(m, d), "max_u32": max(m, d), "min_i32": min(m, d), "max_i32": max(m, d),
                         "and_b32": m & d, "or_b32": m | d, "xor_b32": m ^ d}[op]
                lds[slot] = value & M32
        for t in range(128):
            memory.store(LDS_BASE + 1024 + 4 * (128 * group + t), lds[t])
    return (2, 1, 1), lds_constants(len(before)), memory.ranges, [before], [bytes(memory.slots[0])]


LDS_C_INDICES = (0, 1, 5, 31, 32, 47, 60, 61, 62, 63, 64, 3, 0x0ffffe00, 17, 30, 9)


def lds_c_reference(inputs, flaws):
    seed, = inputs
    records = []
    for group, index in enumerate(LDS_C_INDICES):
        d = lds_words(seed + group, 3)
        d[(seed + group) % 3] |= 0x80808080  # sign bits in every byte and half
        records += [index, *d]
    memory, before = lds_memory(records, 2048)
    size = 1024

    def place(address):
        if address < size:
            return address
        return address % size if "nobound" in flaws else None

    for group in range(len(LDS_C_INDICES)):
        lds = bytearray(size)
        a, d0, d1, d2 = records[4 * group:4 * group + 4]
        base = (a << 4) & M32
        off = (lambda k: 0 if "offset" in flaws else k)
        adj32 = 8 if "stride" in flaws else 4
        adj64 = 4 if "stride" in flaws else 8
        st = 1 if "st64" in flaws else 64

        def write(address, value, width=4):
            at = place(address)
            if at is not None:
                lds[at:at + width] = (value & ((1 << 8 * width) - 1)).to_bytes(width, "little")

        def read(address, width=4):
            at = place(address)
            return 0 if at is None else int.from_bytes(lds[at:at + width], "little")

        for j, v in enumerate((a, d0, d1, d2)):
            write(base + off(0) + 4 * j, v)
        for j, v in enumerate((d0, d1, d2)):
            write(base + off(16) + 4 * j, v)
        write(base + off(32), d1), write(base + off(32) + 4, d2)
        write(base + off(40), d0)
        if "byte_dword" in flaws:
            write((base + off(17)) & ~3, d2)
        else:
            write(base + off(17), d2, 1)
        write(base + off(26), d1, 2)
        write(base + off(adj32 * 11), d2), write(base + off(adj32 * 12), d0)
        for k, (lo, hi) in enumerate(((d1, d2), (a, d0))):
            element = base + off(k * adj64 * st)
            write(element, lo), write(element + 4, hi)
        out = [read(base + off(0) + 4 * j) for j in range(4)]
        out += [read(base + off(16) + 4 * j) for j in range(3)]
        for k in (4, 5):
            out += [read(base + off(k * adj64)), read(base + off(k * adj64) + 4)]
        byte, half = read(base + off(17), 1), read(base + off(26), 2)
        sign = (lambda v, bits: v if "nosign" in flaws or not v >> (bits - 1) else v | (M32 ^ ((1 << bits) - 1)))
        out += [byte, sign(byte, 8), half, sign(half, 16)]
        out += [read(base), read(base + off(2 * adj32 * st))]
        out += [read(base + off(11 * adj32)), read(base + off(12 * adj32))]
        for j, word in enumerate(out):
            memory.store(LDS_BASE + 1024 + 128 * group + 4 * j, word)
    groups = (len(LDS_C_INDICES), 1, 1)
    return groups, lds_constants(len(before)), memory.ranges, [before], [bytes(memory.slots[0])]


def lds_d_reference(inputs, flaws):
    seed, count = inputs
    words = lds_words(seed, 8 * 512)  # 512 records of 32 bytes: x, y, z, w, then the output word and padding
    memory, before = lds_memory(words, 0)
    constants = lds_constants(len(before))
    constants[1] = count
    record = (lambda k, j: words[8 * k + j])
    for group in range(3):
        m = min(128, count - 128 * group)
        for t in range(128):
            index = 128 * group + t
            if index >= count:
                continue
            pos = 0 if "pos_ignored" in flaws else record(index, 0)
            acc, slots = 0, [(0, 0)] * 128
            for chunk in range(0, count, 128):
                for j in range(128):
                    if chunk + j < count or "unmasked" in flaws:
                        slots[j] = (record(chunk + j, 0), record(chunk + j, 1))
                    elif "no_zero" not in flaws:
                        slots[j] = (0, 0)
                for j in range(m):
                    x, y = slots[j]
                    acc = (acc + (x ^ pos) + (0 if "y_ignored" in flaws else y)) & M32
                if "one_chunk" in flaws:
                    break
            memory.store(LDS_BASE + 32 * index + 16, acc)
    return (3, 1, 1), constants, memory.ranges, [before], [bytes(memory.slots[0])]


LDS_PROGRAMS = [
    (LDS_A, LDS_A_CONTRACT, [(1,), (2,)], lds_a_reference, [{"barrier"}, {"offset"}, {"stride8"}, {"stride1"}]),
    (LDS_B, LDS_B_CONTRACT, [(3,), (4,)], lds_b_reference,
     [{"barrier"}, {"offset"}, {"unsigned"}, {"sub_add"}]),
    (LDS_C, LDS_C_CONTRACT, [(5,), (6,)], lds_c_reference,
     [{"offset"}, {"stride"}, {"st64"}, {"nobound"}, {"byte_dword"}, {"nosign"}]),
    (LDS_D, LDS_D_CONTRACT, [(7, 300), (8, 200)], lds_d_reference,
     [{"no_zero"}, {"one_chunk"}, {"unmasked"}, {"pos_ignored"}, {"y_ignored"}]),
]
BATCHED = {"lds"}  # families dispatched through --check-compute-batch (one renderer launch per program)


FAMILIES = {"ids": IDS_PROGRAMS, "store": STORE_PROGRAMS, "integrate": INTEGRATE_PROGRAMS,
            "image": IMAGE_PROGRAMS, "cf": CF_PROGRAMS, "neutral": NEUTRAL_PROGRAMS, "lanes": LANES_PROGRAMS,
            "dynsmem": DYNSMEM_PROGRAMS, "lds": LDS_PROGRAMS}


def check_reference_arithmetic():
    """The binary32 helpers against values whose encodings are known."""
    assert f32_bits(Fraction(1)) == 0x3f800000 and f32_bits(Fraction(-2)) == 0xc0000000
    assert f32_bits(Fraction(1, 1 << 149)) == 1 and f32_bits(Fraction(1, 1 << 150)) == 0  # ties to even: 0
    assert f32_bits(Fraction(3, 1 << 150)) == 2 and f32_bits(Fraction(2) ** 128) == 0x7f800000
    assert f32_bits(f32_value(0x3dcccccd)) == 0x3dcccccd and f32_value(0x00400000) == Fraction(1, 1 << 127)
    assert mac(0x3f800000, 0x00400000, 0) == 0 and mac(0x3f800000, 0x00400000, 0, {"noflush"}) == 0x00400000
    # 1 + 2^-24 times itself: the unfused product rounds 1 + 2^-23 + 2^-48 to 1 + 2^-23, the fused sum keeps 2^-48.
    one_plus = 0x3f800001
    assert mac(one_plus, one_plus, 0xbf800000) == f32_bits(Fraction(1, 1 << 22))
    assert mac(one_plus, one_plus, 0xbf800000, {"fused"}) == f32_bits(Fraction(1, 1 << 22) + Fraction(1, 1 << 46))


def check_lowering_controls():
    source = lower(IDS_PROGRAM, IDS_CONTRACT)
    for text in ("[numthreads(4, 2, 2)]", "void main(uint3 group_id : SV_GroupID, uint3 local_id : SV_GroupThreadID)",
                 f'[RootSignature("{compute_aot.COMPUTE_ROOT}")]', compute_aot.TITLE_DECLARATIONS_RW,
                 "buffer_store32(rsrc", "local_id.z", "group_id.z", "params[2].x"):
        assert text in source, text
    for text in ("Texture2D", "SV_Target", "SamplerState", "\nByteAddressBuffer", "return float4"):
        assert text not in source, text
    assert compute_aot.COMPUTE_ROOT.startswith("CBV(b0), SRV(t2), DescriptorTable(UAV(u0, space=1, numDescriptors=8)), "
                                               "RootConstants(num32BitConstants=1, b1), DescriptorTable(SRV(t0, "
                                               "numDescriptors=2)), DescriptorTable(UAV(u0, space=2, numDescriptors=32)), "
                                               "StaticSampler(s0, filter=FILTER_MIN_MAG_MIP_POINT,")
    # The C++ harness binds the parameters in this order (tests/compute_aot_render.cpp).
    render = (HERE / "compute_aot_render.cpp").read_text(encoding="utf-8")
    for call in ("SetComputeRootConstantBufferView(0,", "SetComputeRootShaderResourceView(1,",
                 "SetComputeRootDescriptorTable(2,", "SetComputeRoot32BitConstants(3, 1,",
                 "SetComputeRootDescriptorTable(4,", "SetComputeRootDescriptorTable(5,"):
        assert call in render, call
    # An empty program (the corpus has one) is a valid dispatch with nothing to do.
    assert "void main" in lower(["s_endpgm"], {"numthreads": (1, 1, 1), "wave": 64, "sgprs": {}})
    # Without loads or stores no title memory is declared.
    assert "title_memory" not in lower([move(1, "s3"), "s_endpgm"], {"numthreads": (8, 1, 1), "wave": 32,
                                                                   "sgprs": {"s3": "group_id.x"}})


def check_refusals():
    """Neighbours of the accepted programs that C-1 must refuse, each for its own reason."""
    base = {"numthreads": (64, 1, 1), "wave": 64, "local_ids": 1, "sgprs": {"s2": "descriptors", "s3": "group_id.x"},
            "buffer_descriptors": {0: 8}}
    head = ["s_mov_b32 s0, s3", "s_movk_i32 s3, 0x8000", "s_load_dwordx4 s[8:11], s[2:3], null",
            "v_lshlrev_b32_e32 v4, 2, v0", "s_waitcnt lgkmcnt(0)"]
    store = "buffer_store_dword v0, v4, s[8:11], 0 offen"

    def program(*body, contract=base):
        return lambda: compute_aot.lower_compute([*head, *body, "s_endpgm"], **contract)

    must_reject(lambda: compute_aot.lower_compute([*head, store], **base))  # no s_endpgm
    must_reject(program(store, "s_endpgm"))  # an instruction after the end
    assert "buffer_store32" in program(store)()
    # Cross-lane, LDS without an allocation (C-6), atomics, images, global stores, control flow and the pixel stage's
    # own forms.
    for bad in ("ds_write_b32 v4, v0", "ds_read_b32 v5, v4", "v_readfirstlane_b32 s5, v0",
                "v_readlane_b32 s5, v0, 1", "v_writelane_b32 v5, s0, 1", "v_mbcnt_lo_u32_b32 v5, -1, 0",
                "s_bcnt1_i32_b64 s5, exec", "s_ff1_i32_b64 s5, exec", "v_permlane16_b32 v5, v0, s0, s0",
                "buffer_atomic_add v0, v4, s[8:11], 0 offen", "global_store_dword v[4:5], v0, off",
                "image_store v[0:3], v4, s[8:15] dmask:0xf dim:SQ_RSRC_IMG_1D unorm",
                "s_branch _L0", "s_cbranch_execz _L0", "s_getpc_b64 s[4:5]", "s_setpc_b64 s[4:5]",
                "s_sendmsg sendmsg(MSG_DEALLOC_VGPRS)",
                "s_wqm_b64 exec, exec", "v_mov_b32_dpp v5, v0 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
                "exp mrt0 v0, v0, v0, v0 done compr vm", "v_interp_p1_f32_e32 v5, v0, attr0.x",
                "buffer_store_byte v0, v4, s[8:11], 0 offen", "buffer_store_short v0, v4, s[8:11], 0 offen",
                "buffer_store_format_x v0, v4, s[8:11], 0 offen", "flat_store_dword v[4:5], v0"):
        must_reject(program(bad))
        must_reject(program(bad, store))
    # C-7: v_readfirstlane_b32 of a wave-uniform value (forms/lanes.py). Accepted: a value built from the group id, and
    # in a one-thread workgroup any value (the only lane is the first active one). Refused: a lane-varying or loaded
    # value in a larger workgroup (a load at a uniform address too: another thread's store may land between two
    # desktop waves' loads), a masked write read after EXEC is restored, a read while the wave may have no active lane
    # (v_cmpx without a skip branch: with EXEC zero the console reads lane 0), a destination that is not an SGPR,
    # v_readlane_b32 and the pixel stage.
    masked = ["v_cmp_gt_u32_e64 s[20:21], 5, v0", "s_mov_b64 s[22:23], exec", "s_and_b64 exec, exec, s[20:21]"]
    rfl_store = ["v_mov_b32_e32 v7, s5", "buffer_store_dword v7, v4, s[8:11], 0 offen"]
    assert "uint rfl" in program("v_mov_b32_e32 v6, s0", "v_readfirstlane_b32 s5, v6", *rfl_store)()
    one = {**base, "numthreads": (1, 1, 1)}
    assert "uint rfl" in program("v_readfirstlane_b32 s5, v0", *rfl_store, contract=one)()
    for body in (("buffer_load_dword v6, v4, s[8:11], 0 offen", "s_waitcnt vmcnt(0)"),
                 ("buffer_load_dword v6, off, s[8:11], s0", "s_waitcnt vmcnt(0)"),
                 ("v_mov_b32_e32 v6, s0", *masked, "v_mov_b32_e32 v6, 7", "s_mov_b64 exec, s[22:23]"),
                 ("v_mov_b32_e32 v6, s0", "v_cmpx_gt_u32_e32 5, v0"),
                 ("v_cvt_f32_u32_e32 v6, v0",)):
        must_reject(program(*body, "v_readfirstlane_b32 s5, v6", *rfl_store))
    assert "uint rfl" in program("v_mov_b32_e32 v6, s0", "v_cmpx_gt_u32_e32 5, v0", "s_cbranch_execz _L0",
                                 "v_add_nc_u32_e32 v6, 7, v6", "v_readfirstlane_b32 s5, v6", *rfl_store, "_L0:")()
    must_reject(program("v_mov_b32_e32 v6, s0", "v_cmpx_gt_u32_e32 5, v0", "s_cbranch_execz _L0",
                        "v_add_nc_u32_e32 v6, v0, v6", "v_readfirstlane_b32 s5, v6", *rfl_store, "_L0:"))
    for bad in ("v_readfirstlane_b32 s5, v[6:7]", "v_readfirstlane_b32 m0, v6", "v_readlane_b32 s5, v6, 0"):
        must_reject(program("v_mov_b32_e32 v6, s0", bad, *rfl_store))
    must_reject(common.translate, common.with_constants(["v_readfirstlane_b32 s60, v12"]))
    # Store operands and modifiers.
    for bad in ("buffer_store_dword v0, v4, s[8:11], 0 offen tfe", "buffer_store_dword v0, v4, s[8:11], 0 offen lds",
                "buffer_store_dword v0, v4, s[8:11], 0 offen offset:4096", "buffer_store_dword v0, v4, s[8:11], 0",
                "buffer_store_dword v0, off, s[8:11], 0 offen", "buffer_store_dword v0, v4, s[8:11], 0 offen idxen",
                "buffer_store_dword v0, v4, s[9:12], 0 offen", "buffer_store_dwordx2 v0, v4, s[8:11], 0 offen",
                "buffer_store_dwordx2 v[0:2], v4, s[8:11], 0 offen", "buffer_store_dword v9, v4, s[8:11], 0 offen",
                "buffer_store_dword v0, v9, s[8:11], 0 offen", "buffer_store_dword v0, v4, s[12:15], 0 offen",
                "buffer_store_dword v0, v4, s[8:11], s70 offen", "buffer_store_dword v0, v4, s[8:11], 0 offen glc glc"):
        must_reject(program(bad))
    # Store data from a load that has not completed. A load after a store is lowered since C-3 (one D3D12 thread sees
    # its own UAV writes in program order; another lane's store without a barrier is a race on the console as well).
    load = "buffer_load_dword v6, v4, s[8:11], 0 offen offset:4"
    assert "buffer_load32" in program(load, "s_waitcnt vmcnt(0)", "buffer_store_dword v6, v4, s[8:11], 0 offen")()
    must_reject(program(load, "buffer_store_dword v6, v4, s[8:11], 0 offen"))
    assert "buffer_load32" in program(store, load, "s_waitcnt vmcnt(0)", "buffer_store_dword v6, v4, s[8:11], 0 offen")()
    # C-3: a store while the lane may be inactive is emitted under `if (ex)`; a store after EXEC is restored is not.
    masked = ["v_cmp_gt_u32_e64 s[20:21], 5, v0", "s_mov_b64 s[22:23], exec", "s_and_b64 exec, exec, s[20:21]"]
    assert "buffer_store32(rsrc" in program(*masked[:2], store)()
    guarded = program(*masked, store)()
    assert any(line.startswith("    if (ex") and "buffer_store32(" in line for line in guarded.splitlines()), guarded
    restored = program(*masked, "s_mov_b64 exec, s[22:23]", store)()
    assert not any(line.startswith("    if (") and "buffer_store32(" in line for line in restored.splitlines())
    # The pixel stage keeps refusing a store and the VGPR-only forms while the lane may be inactive.
    must_reject(common.translate, common.with_constants([
        "v_cmp_gt_u32_e64 s[60:61], 5, v12", "s_and_b64 exec, exec, s[60:61]", "v_cvt_f32_u32_e32 v13, v12"]))
    # C-3 control flow: an unstructured branch (into a loop), an EXEC re-enabled inside a skipped region, and a branch
    # on a divergent VCC stay refused.
    must_reject(program("v_cmpx_gt_u32_e32 5, v0", "s_cbranch_execz _L1", "_L0:", "s_mov_b32 s5, 0", "_L1:",
                        "s_cbranch_scc1 _L0"))
    must_reject(program("v_cmp_gt_u32_e64 s[20:21], 5, v0", "s_and_saveexec_b64 s[22:23], s[20:21]",
                        "s_cbranch_execz _L0", "s_mov_b64 exec, -1", store, "_L0:"))
    must_reject(program("v_cmp_gt_u32_e32 vcc, 5, v0", "s_cbranch_vccz _L0", store, "_L0:"))
    # C-2: image refusals. Implicit-LOD forms (no derivatives in a compute thread), an image the contract does not
    # bind, an atomic, a store to a texel every thread of the group shares, a read-only image written, a storage image
    # sampled, an RGBA8 store in the pixel stage, a mip store to RGBA8, and a sampler that is not the declared S#.
    images = {**base, "local_ids": 2, "textures": {0x40: 0}, "storage_images": {0x60: (0, "r8g8b8a8_unorm")},
              "sampler": 0x80}
    ihead = ["s_movk_i32 s3, 0x8000", "s_load_dwordx8 s[16:23], s[2:3], 0x40", "s_load_dwordx8 s[24:31], s[2:3], 0x60",
             "s_load_dwordx4 s[12:15], s[2:3], 0x80", "s_load_dwordx4 s[8:11], s[2:3], null", "s_waitcnt lgkmcnt(0)"]

    def image_program(*body):
        return lambda: compute_aot.lower_compute([*ihead, *body, "s_endpgm"], **images)

    istore = "image_store v[4:7], v[0:1], s[24:31] dmask:0xf dim:SQ_RSRC_IMG_2D unorm"
    fill = ["v_mov_b32_e32 v4, 1.0", "v_mov_b32_e32 v5, 0", "v_mov_b32_e32 v6, 0.5", "v_mov_b32_e32 v7, 0"]
    assert "image_store0(" in image_program(*fill, istore)()
    assert "tex.SampleLevel(samp" in image_program(
        "image_sample_lz v[4:6], v[0:1], s[16:23], s[12:15] dmask:0x7 dim:SQ_RSRC_IMG_2D", "s_waitcnt vmcnt(0)")()
    for bad in ("image_sample v[4:7], v[0:1], s[16:23], s[12:15] dmask:0xf dim:SQ_RSRC_IMG_2D",
                "image_sample_b v[4:7], v[0:2], s[16:23], s[12:15] dmask:0xf dim:SQ_RSRC_IMG_2D",
                "image_gather4 v[4:7], v[0:1], s[16:23], s[12:15] dmask:0x1 dim:SQ_RSRC_IMG_2D",
                "image_get_lod v[4:5], v[0:1], s[16:23], s[12:15] dmask:0x3 dim:SQ_RSRC_IMG_2D",
                "image_load v[4:7], v[0:1], s[24:31] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                "image_sample_lz v[4:6], v[0:1], s[24:31], s[12:15] dmask:0x7 dim:SQ_RSRC_IMG_2D",
                "image_sample_lz v[4:6], v[0:1], s[16:23], s[8:11] dmask:0x7 dim:SQ_RSRC_IMG_2D",
                "image_atomic_add v4, v[0:1], s[24:31] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm glc",
                "image_store v[4:7], v[0:1], s[16:23] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                "image_store_mip v[4:7], v[0:2], s[24:31] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                "image_store v[4:7], v[0:1], s[24:31] dmask:0x0 dim:SQ_RSRC_IMG_2D unorm"):
        must_reject(image_program(*fill, bad))
    must_reject(image_program(*fill, "v_mov_b32_e32 v8, s3", "v_mov_b32_e32 v9, 0",
                              "image_store v[4:7], v[8:9], s[24:31] dmask:0xf dim:SQ_RSRC_IMG_2D unorm"))
    for change in ({"textures": {0x40: 2}}, {"textures": {0x44: 0}}, {"storage_images": {0x60: (4, "r8g8b8a8_unorm")}},
                   {"storage_images": {0x60: (0, "r8g8b8a8_snorm")}}, {"sampler": 0x88},
                   {"textures": {0x40: 0, 0x50: 1}}, {"storage_images": {0x60: (0, "r32_uint"), 0x80: (1, "r32_uint")}}):
        must_reject(image_program(*fill, istore) if False else
                    (lambda change=change: compute_aot.lower_compute([*ihead, *fill, istore, "s_endpgm"],
                                                                     **{**images, **change})))
    # Descriptor words as data (descriptor_data): a T# word read by a scalar form needs them; the contract must name a
    # declared image or sampler and words inside the 64 that overlap no buffer V#, user word or other data.
    width = ["s_bfe_u32 s40, s17, 0x2001e", "v_lshlrev_b32_e32 v4, 2, v0", "v_mov_b32_e32 v8, s40", "buffer_store_dword v8, v4, s[8:11], 0 offen"]
    assert "params[5].y" in compute_aot.lower_compute([*ihead, *width, "s_endpgm"], **{**images, "descriptor_data": {0x40: 20}})
    assert "params[5].y" in compute_aot.lower_compute([*ihead, "s_bfe_u32 s40, s13, 0x2001e", *width[1:], "s_endpgm"],
                                                      **{**images, "descriptor_data": {0x80: 20}})  # an S# word
    must_reject(image_program(*width))
    for data in ({0x48: 20}, {0xa0: 20}, {0x40: 57}, {0x40: 6}, {0x40: 20, 0x60: 24}, {0x40: -1}):
        must_reject(lambda data=data: compute_aot.lower_compute([*ihead, *width, "s_endpgm"],
                                                                **{**images, "descriptor_data": data}))
    # EXEC = -1 (s_mov_b64 exec, -1 and s_andn2_b64 exec, -1, exec) where every lane of every wave is a thread and the
    # walk is in no skipped region or loop; refused for a partial wave (48 threads in wave64), in a loop, inside a
    # skipped region (above) and in the pixel stage.
    whole = ["v_cmp_gt_u32_e32 vcc, 5, v0", "s_mov_b64 exec, vcc", "v_mov_b32_e32 v5, 1", "s_andn2_b64 exec, -1, exec",
             "v_mov_b32_e32 v5, 2", "s_mov_b64 exec, -1", "buffer_store_dword v5, v4, s[8:11], 0 offen"]
    assert "bool ex" in program(*whole)()
    must_reject(program(*whole, contract={**base, "numthreads": (48, 1, 1)}))
    must_reject(program(*whole[:3], "s_mov_b64 exec, -1", whole[-1], contract={**base, "numthreads": (48, 1, 1)}))
    must_reject(program("v_cmp_gt_u32_e32 vcc, 5, v0", "s_mov_b64 exec, vcc", "s_mov_b32 s6, 0", "_L0:",
                        "s_mov_b64 exec, -1", "s_add_u32 s6, s6, 1", "s_cmp_lt_u32 s6, 3", "s_cbranch_scc1 _L0", store))
    must_reject(common.translate, common.with_constants(["s_mov_b64 exec, -1"]))
    # A descriptor word outside every declared descriptor, and a pointer of an undeclared set.
    must_reject(image_program("s_load_dwordx4 s[40:43], s[2:3], 0xa0"))
    must_reject(lambda: compute_aot.lower_compute(
        ["s_movk_i32 s5, 0x8000", "s_load_dwordx8 s[16:23], s[4:5], 0x40", "s_endpgm"], **images))
    # C-4 neighbours: v_pk_fmac_f16 with a constant src0, v_pack_b32_f16 with modifiers, src_scc without a tracked SCC.
    for bad in ("v_pk_fmac_f16 v5, 1.0, v0", "v_pack_b32_f16 v5, -v0, v0", "v_pack_b32_f16 v5, v0, v0 op_sel:[1,0,0]",
                "s_mov_b32 s5, src_scc"):
        must_reject(program(bad, store))
    # Entry registers without a role, and a descriptor pointer completed with another high word.
    must_reject(program("buffer_store_dword v1, v4, s[8:11], 0 offen"))  # v1 is not a local id with local_ids=1
    must_reject(program("v_mov_b32_e32 v5, s5", store))  # s5 has no role
    must_reject(lambda: compute_aot.lower_compute(
        ["s_mov_b32 s3, 0", "s_load_dwordx4 s[8:11], s[2:3], null", "s_waitcnt lgkmcnt(0)", store, "s_endpgm"], **base))
    must_reject(lambda: compute_aot.lower_compute(
        ["s_movk_i32 s3, 0x8000", "s_load_dwordx4 s[8:11], s[2:3], 0x10", "s_waitcnt lgkmcnt(0)", store, "s_endpgm"],
        **base))  # a descriptor offset that is not declared
    # Lane masks of the other wave size.
    wave32 = {**base, "wave": 32}
    for bad in ("v_cmp_gt_u32_e32 vcc, 5, v0", "v_cmp_gt_u32_e64 s[20:21], 5, v0", "s_mov_b64 s[22:23], exec"):
        must_reject(program(bad, contract=wave32))
    for bad in ("v_cmp_gt_u32_e32 vcc_lo, 5, v0", "v_cmp_gt_u32_e64 s20, 5, v0", "s_mov_b32 s22, exec_lo"):
        must_reject(program(bad))
    assert program("v_cmp_gt_u32_e32 vcc_lo, 5, v0", store, contract=wave32)()
    # Invalid contracts.
    for change in ({"numthreads": (0, 1, 1)}, {"numthreads": (1025, 1, 1)}, {"numthreads": (1, 1, 65)},
                   {"numthreads": (32, 32, 2)}, {"wave": 16}, {"local_ids": 4}, {"local_ids": 0}, {"packed_ids": True},
                   {"sgprs": {"s2": "descriptors", "s3": "group_id.x", "s4": "group_id.x"}},
                   {"sgprs": {"s2": "descriptors", "s3": "group_id.w"}}, {"sgprs": {"s106": "group_id.x"}},
                   {"sgprs": {"s2": "descriptors", "s3": "user:64"}},
                   {"sgprs": {"s2": "descriptors", "s3": "user:9"}},  # overlaps the V# words 8 to 11
                   {"buffer_descriptors": {4: 8}}, {"buffer_descriptors": {0: 61}},
                   {"buffer_descriptors": {0: 8}, "constant_descriptor": 0x8},
                   {"buffer_descriptors": {0: 8}, "constant_descriptor": 0}):
        must_reject(lambda: compute_aot.lower_compute([*head, store, "s_endpgm"], **{**base, **change}))
    # The pixel stage still refuses every store.
    must_reject(common.translate, common.with_constants(["buffer_store_dword v12, v12, s[52:55], 0 offen"]))


def check_dynsmem_refusals():
    """Neighbours of the dynsmem programs (dynamic scalar constant loads, loads carried around loops) that must stay
    refused, each with the reason it must give."""
    def refuses(program, contract, reason):
        try:
            compute_aot.lower_compute(program, **contract)
        except ValueError as error:
            assert reason in str(error), (reason, str(error))
            return
        raise AssertionError(f"Accepted a program that must be refused ({reason})")

    a, b = DYNSMEM_A, DYNSMEM_B

    def edit(program, old, *new):
        at = program.index(old)
        return [*program[:at], *new, *program[at + 1:]]

    # The offset: field of a run-time offset must be a multiple of 4.
    refuses(edit(a, "s_buffer_load_dwordx2 s[4:5], s[12:15], s1 offset:0x8",
                 "s_buffer_load_dwordx2 s[4:5], s[12:15], s1 offset:0x6"), DYNSMEM_CONTRACT, "misaligned")
    # The offset register holds a V# word, or a load still outstanding.
    refuses(edit(a, "s_buffer_load_dword s16, s[12:15], s1", "s_buffer_load_dword s16, s[12:15], s14"),
            DYNSMEM_CONTRACT, "numeric scalar register")
    refuses(edit(a, "s_buffer_load_dword s16, s[12:15], s1", "s_buffer_load_dword s16, s[12:15], s4"),
            DYNSMEM_CONTRACT, "known constant")
    # A descriptor load at a run-time offset (a descriptor index) is not lowered.
    refuses(edit(a, "s_load_dwordx8 s[8:15], s[2:3], null", "s_load_dwordx8 s[8:15], s[2:3], s1"),
            DYNSMEM_CONTRACT, "known constant")
    # A run-time offset into a constant slot other than b0: none in the compute stage; the words of a buffer V#.
    refuses(edit(a, "s_buffer_load_dword s16, s[12:15], s1", "s_buffer_load_dword s16, s[8:11], s1"),
            DYNSMEM_CONTRACT, "Unresolved constant buffer binding")
    # The load is outstanding at the header from the first iteration on: a read before the wait in the innermost loop,
    # a reload of the V# over the words without the wait at the outer header, and the store's V# read on the path
    # where the outer loop runs no trip (its own load is then still outstanding) are refused.
    inner = b.index("s_cbranch_scc1 BB13")
    late_wait = [*b[:inner + 1], b[inner + 2], b[inner + 1], *b[inner + 3:]]
    assert late_wait[inner + 2] == "s_waitcnt lgkmcnt(0)"
    refuses(late_wait, DYNSMEM_B_CONTRACT, "before load completion")
    body = b.index("s_cbranch_scc1 BB15")
    refuses([*b[:body + 1], *b[body + 2:]], DYNSMEM_B_CONTRACT, "outstanding scalar load")
    tail = len(b) - 1 - b[::-1].index("s_waitcnt lgkmcnt(0)")
    refuses([*b[:tail], *b[tail + 1:]], DYNSMEM_B_CONTRACT, "before load completion")
    # The V# word reused as the innermost counter holds a descriptor word on the middle loop's first trip and data
    # after: unreadable at the middle loop's header and after it.
    refuses(edit(b, "s_cbranch_scc1 BB14", "s_cbranch_scc1 BB14", "v_add_nc_u32_e32 v1, s15, v1"), DYNSMEM_B_CONTRACT,
            "s15")
    refuses(edit(b, "BB14:", "BB14:", "v_add_nc_u32_e32 v1, s15, v1"), DYNSMEM_B_CONTRACT, "Descriptor state differs")


def check_lds_refusals():
    """Neighbours of the lds programs (card C-6) that must stay refused, each with the reason it must give."""
    def refuses(program, contract, reason):
        try:
            compute_aot.lower_compute(program, **contract)
        except ValueError as error:
            assert reason in str(error), (reason, str(error))
            return
        raise AssertionError(f"Accepted a program that must be refused ({reason})")

    def edit(program, old, *new):
        at = program.index(old)
        return [*program[:at], *new, *program[at + 1:]]

    a, b, c, d = LDS_A, LDS_B, LDS_C, LDS_D
    ca, cb, cc, cd = LDS_A_CONTRACT, LDS_B_CONTRACT, LDS_C_CONTRACT, LDS_D_CONTRACT
    # The contract: no allocation, a size that is not a multiple of 16, past D3D12's 32 KiB, not an integer.
    for size, reason in ((0, "without an LDS allocation"), (1000, "Invalid LDS size"), (65536, "Invalid LDS size"),
                         (-16, "Invalid LDS size"), (True, "Invalid LDS size"), (64.0, "Invalid LDS size")):
        refuses(a, {**ca, "lds_size": size}, reason)
    # The pixel stage lowers neither LDS nor barriers.
    for line in ("ds_read_b32 v12, v12", "ds_write_b32 v12, v12", "s_barrier"):
        must_reject(common.translate, common.with_constants([line]))
    # Alignment the address does not prove: a dword at a byte address, a b64 at a dword address, b128 and b96 at 8,
    # an offset field off the access size, a half at an odd offset, ds_read2_b64 from a dword address.
    refuses(edit(a, "ds_read_b32 v11, v7", "ds_read_b32 v11, v0"), ca, "alignment to 4")
    refuses(edit(c, "ds_write_b64 v4, v[2:3] offset:32", "ds_write_b64 v4, v[2:3] offset:36"), cc, "alignment to 8")
    refuses(edit(c, "v_lshlrev_b32_e32 v4, 4, v0", "v_lshlrev_b32_e32 v4, 3, v0"), cc, "alignment to 16")
    refuses(edit(c, "ds_write_b32 v4, v1 offset:40", "ds_write_b32 v4, v1 offset:42"), cc, "alignment to 4")
    refuses(edit(c, "ds_read_u16 v22, v4 offset:26", "ds_read_u16 v22, v4 offset:27"), cc, "alignment to 2")
    refuses(edit(c, "ds_write_b96 v4, v[1:3] offset:16", "ds_write_b96 v4, v[1:3] offset:20"), cc, "alignment to 16")
    # A translation-time address outside the allocation.
    refuses(edit(c, "v_lshlrev_b32_e32 v4, 4, v0", "v_mov_b32_e32 v4, 0x3f0"), cc, "translation-time address")
    assert "lds_load32" in compute_aot.lower_compute(edit(c, "v_lshlrev_b32_e32 v4, 4, v0", "v_mov_b32_e32 v4, 0x100"),
                                                     **cc)
    # Races between threads with no barrier between: the partner's word read in the epoch it is written (A's second
    # barrier and B's last one removed), a write that every thread makes to one word, a write to the partner's word,
    # two atomic operations in one epoch, an atomic and a read, and a write after the loop's reads that the back edge
    # brings before them (D without its second barrier). A's first barrier separates only private words: each thread
    # writes its own A and B words on both sides, which needs no barrier, and is accepted without it.
    race = "may race with another thread"
    first, second = [n for n, line in enumerate(a) if line == "s_barrier"]
    assert "lds_load32" in compute_aot.lower_compute([*a[:first], *a[first + 1:]], **ca)
    refuses([*a[:second], *a[second + 1:]], ca, race)
    refuses(b[:len(b) - 1 - b[::-1].index("s_barrier")] + b[len(b) - b[::-1].index("s_barrier"):], cb, race)
    refuses(edit(a, "ds_write_b32 v9, v5", "v_mov_b32_e32 v15, 0x400", "ds_write_b32 v15, v5"), ca, race)
    refuses(edit(a, "ds_write_b32 v3, v6 offset:1024", "v_xor_b32_e32 v15, 0x3fc, v3", "ds_write_b32 v15, v6"), ca,
            race)
    refuses(edit(b, "ds_sub_u32 v5, v6 offset:32", "ds_add_u32 v5, v6 offset:32", "ds_sub_u32 v5, v6 offset:32"), cb,
            race)
    refuses(edit(b, "ds_sub_u32 v5, v6 offset:32", "ds_sub_u32 v5, v6 offset:32", "ds_read_b32 v9, v5"), cb, race)
    tail = len(d) - 1 - d[::-1].index("s_barrier")
    refuses([*d[:tail], *d[tail + 1:]], cd, race)
    # A one-thread group has no other thread: C's accesses need no barrier, and A in one thread neither.
    assert "lds_atomic" in compute_aot.lower_compute([line for line in b if line != "s_barrier"],
                                                     **{**cb, "numthreads": (1, 1, 1), "local_ids": 2})
    # Barriers HLSL cannot keep: one in a loop a lane may leave (a lane-local exit), one in a region a wave may skip
    # with another barrier after the region, one in such a region inside a loop, one on one path of a uniform branch
    # (the other path's accesses join the epoch, so D's read after it races), and one in the pixel stage.
    divergent = ["v_mov_b32_e32 v1, 0", "s_mov_b64 s[60:61], exec", "BB1:", "s_mov_b64 s[62:63], exec",
                 "v_cmpx_ge_u32_e32 v1, v0", "BB2:", "s_andn2_b64 s[62:63], s[62:63], exec", "s_cbranch_scc0 BB4",
                 "BB3:", "s_mov_b64 exec, s[62:63]", "s_barrier", "v_add_nc_u32_e32 v1, 1, v1", "s_branch BB1", "BB4:",
                 "s_mov_b64 exec, s[60:61]", "s_endpgm"]
    loop_contract = {"numthreads": (64, 1, 1), "wave": 64, "sgprs": {}, "local_ids": 1}
    refuses(divergent, loop_contract, "not workgroup-uniform")
    assert "while" in compute_aot.lower_compute([line for line in divergent if line != "s_barrier"], **loop_contract)
    one_path = [*a[:second], "s_cmp_eq_u32 s0, 0", "s_cbranch_scc1 BB2", "BB1:", "s_barrier", "BB2:", *a[second + 1:]]
    refuses(one_path, ca, race)
    assert "GroupMemoryBarrierWithGroupSync" in compute_aot.lower_compute(
        [*a[:second], "s_cmp_eq_u32 s0, 0", "s_cbranch_scc1 BB2", "BB1:", "s_barrier", "s_branch BB3", "BB2:",
         "s_barrier", "BB3:", *a[second + 1:]], **ca)
    refuses(edit(d, "BB9:", "BB9:", "s_barrier"), cd, "region a wave may skip")
    skipped = ["v_cmpx_gt_u32_e32 64, v0", "s_cbranch_execz BB2", "BB1:", "s_barrier", "BB2:", "s_endpgm"]
    assert "GroupMemoryBarrierWithGroupSync" in compute_aot.lower_compute(skipped, numthreads=(128, 1, 1), wave=64,
                                                                          sgprs={}, local_ids=1)
    looped = ["s_mov_b32 s4, 0", "BB0:", "v_cmpx_gt_u32_e32 64, v0", "s_cbranch_execz BB2", "BB1:", "s_barrier",
              "BB2:", "s_add_u32 s4, s4, 1", "s_cmp_lt_u32 s4, 4", "s_cbranch_scc1 BB0", "BB3:", "s_endpgm"]
    refuses(looped, {"numthreads": (128, 1, 1), "wave": 64, "sgprs": {}, "local_ids": 1}, "region a wave may skip")
    # The LDS wait count: a read result used, or overwritten, before s_waitcnt lgkmcnt(0).
    read2 = "ds_read2_b32 v[12:13], v7 offset0:1 offset1:64"
    refuses(edit(a, read2, read2, "v_mov_b32_e32 v15, v10"), ca, "before s_waitcnt lgkmcnt(0)")
    refuses(edit(a, "v_lshlrev_b32_e32 v14, 4, v1", "v_lshlrev_b32_e32 v11, 4, v1"), ca, "before s_waitcnt lgkmcnt(0)")
    refuses(edit(c, "ds_read_b96 v[12:14], v4 offset:16", "ds_read_b96 v[8:10], v4 offset:16"), cc,
            "before s_waitcnt lgkmcnt(0)")
    # v_readfirstlane_b32 of an LDS word read at an address that is not workgroup-uniform (the thread's own slot).
    refuses(edit(d, "v_mov_b32_e32 v8, s3", "v_lshlrev_b32_e32 v8, 4, v0"), cd, "not provably wave-uniform")
    # Cross-lane, ordered, GDS and returning forms stay refused.
    for line, reason in (("ds_swizzle_b32 v5, v4 offset:swizzle(SWAP,1)", "permutation"),
                         ("ds_bpermute_b32 v5, v4, v3", "permutation"), ("ds_permute_b32 v5, v4, v3", "permutation"),
                         ("ds_write_b32 v4, v5 gds", "GDS"), ("ds_append v5", "ordered"),
                         ("ds_add_rtn_u32 v6, v4, v5", "Unsupported instruction")):
        refuses(edit(c, "s_waitcnt lgkmcnt(0)", line, "s_waitcnt lgkmcnt(0)"), cc, reason)


def check_adapter_skip(directory):
    """Without a hardware adapter the renderer exits 77 and every family must report that skip, not a failure."""
    compiler, renderer = "stub-dxc", "stub-offscreen"

    def run_without_adapter(args, *, check=False, **_):
        assert args[0] in (compiler, renderer), args
        if args[0] == compiler:
            Path(args[args.index("-Fo") + 1]).write_bytes(b"")
        result = subprocess.CompletedProcess(args, 77 if args[0] == renderer else 0, "", "")
        if check:
            result.check_returncode()
        return result

    from unittest.mock import patch  # here, not at the top: it costs 40 ms of every import

    for name in FAMILIES:
        work = directory / f"no-adapter-{name}"
        work.mkdir()
        with patch.object(subprocess, "run", side_effect=run_without_adapter):
            assert check_render(work, compiler, renderer, "hardware", [name]) == 77, name


def check_controls(directory):
    check_reference_arithmetic()
    check_lowering_controls()
    for name, programs in FAMILIES.items():
        check_separation(name, programs)
    check_refusals()
    check_dynsmem_refusals()
    check_lds_refusals()
    check_adapter_skip(directory)


def check_binary(directory, assembler, objcopy, library):
    """Every draw program assembled by llvm-mc, disassembled again and lowered to the same HLSL."""
    for name, programs in FAMILIES.items():
        for index, (program, contract, *_) in enumerate(programs):
            source, obj, binary = (directory / f"{name}{index}.{ext}" for ext in ("s", "o", "bin"))
            source.write_text("\n".join(program) + "\n", encoding="ascii")
            subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013",
                            f"-mattr=+wavefrontsize{contract['wave']}", "-filetype=obj", source, "-o", obj], check=True)
            subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
            # The lane-mask operands print as vcc/exec only in a wave64 disassembly.
            decoded = disassemble(binary.read_bytes(), library, features=f"+wavefrontsize{contract['wave']}".encode())
            assert lower(decoded, contract) == lower(program, contract), (name, index)
    # A title container (upstream's compute envelope, R0Y00/Xbox2Windows#483): integrate shape A, wave64, read through
    # compute_aot.container_program, whose PSV gives the workgroup size; the translate CLI does the same.
    from pixel_aot_check import envelope
    from pixel_aot import _read_named_container
    program, contract = INTEGRATE_PROGRAMS[0][:2]
    source, obj, binary = (directory / f"container.{ext}" for ext in ("s", "o", "bin"))
    source.write_text("\n".join(program) + "\n", encoding="ascii")
    subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-mattr=+wavefrontsize64", "-filetype=obj",
                    source, "-o", obj], check=True)
    subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
    code = binary.read_bytes()
    padded = code + bytes.fromhex("00009fbf") * (4 - (len(code) // 4 + 10) % 4)  # s_code_end padding, as #483 pads
    payload = envelope(padded, directory_end=(40 + len(padded), 288 + len(padded)), compute_width=64)
    container = directory / "integrate.dxbc"
    container.write_bytes(_read_named_container(payload, 1 + len(b"fixture") + 1))
    from unittest.mock import patch

    with patch("pixel_aot.disassemble", lambda code, llvm: disassemble(code, llvm, features=b"+wavefrontsize64")):
        instructions, numthreads = compute_aot.container_program(container, library)
    assert numthreads == (64, 1, 1)
    others = {k: v for k, v in contract.items() if k != "numthreads"}
    assert lower(instructions, {**others, "numthreads": numthreads}) == lower(program, contract)


def check_render(directory, compiler, renderer, backend, families=None):
    for name in families or FAMILIES:
        try:
            code = run_family(directory, compiler, renderer, backend, name, FAMILIES[name])
        except subprocess.CalledProcessError as error:
            if error.returncode != 77:
                raise
            return 77
        if code:
            return code
    return 0


def main():
    mode, *args = sys.argv[1:]
    if mode == "--list-families":
        print("\n".join(FAMILIES))
        return 0
    families = []
    while "--family" in args:
        at = args.index("--family")
        families.append(args[at + 1])
        del args[at:at + 2]
    unknown = [name for name in families if name not in FAMILIES]
    if unknown or (families and mode != "draw"):
        raise ValueError(f"Unknown or misplaced --family {unknown}; known families: {', '.join(FAMILIES)}")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        if mode == "controls":
            check_controls(directory)
        elif mode == "binary":
            check_controls(directory)
            check_binary(directory, *args)
        elif mode == "draw":
            if not families:
                check_controls(directory)
            return check_render(directory, *args, families or None)
        else:
            raise ValueError("Expected binary, controls or draw mode")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:  # also on skip or failure; tools/form_coverage.py reads the test's status from JUnit
        common.write_record(os.environ.get("FORM_COVERAGE_RECORD"))
