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
from unittest.mock import patch

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


def case_bytes(groups, constants, ranges, before, after):
    assert len(constants) == 64 and len(before) == len(after)
    out = struct.pack("<5I", 0x43573258, *groups, 0) + struct.pack("<64I", *constants)
    out += titlemem.section(ranges, before)
    out += struct.pack("<2I", 0x45573258, len(after))
    for blob, old in zip(after, before):
        assert len(blob) == len(old)  # the renderer checks the sizes too
        out += struct.pack("<I", len(blob)) + bytes(blob)
    return out


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
        for inputs in cases:
            groups, constants, ranges, before, after = reference(inputs, ())
            case.write_bytes(case_bytes(groups, constants, ranges, before, after))
            subprocess.run(dispatch, check=True)
            for k, flaw in enumerate(flaws):
                wrong = reference(inputs, flaw)[4]
                if wrong == after:
                    continue
                separated[k] = True
                case.write_bytes(case_bytes(groups, constants, ranges, before, wrong))
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
            assert any(reference(inputs, flaw)[4] != right[4] for inputs, right in zip(cases, results)), \
                (name, index, sorted(flaw))
        for right in results:
            assert right[4] != right[3], (name, index, "a case that stores nothing checks nothing")


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

FAMILIES = {"ids": IDS_PROGRAMS, "store": STORE_PROGRAMS, "integrate": INTEGRATE_PROGRAMS}


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
    assert compute_aot.COMPUTE_ROOT == ("CBV(b0), SRV(t2), DescriptorTable(UAV(u0, space=1, numDescriptors=8)), "
                                        "RootConstants(num32BitConstants=1, b1)")
    # The C++ harness binds the parameters in this order (tests/compute_aot_render.cpp).
    render = (HERE / "compute_aot_render.cpp").read_text(encoding="utf-8")
    for call in ("SetComputeRootConstantBufferView(0,", "SetComputeRootShaderResourceView(1,",
                 "SetComputeRootDescriptorTable(2,", "SetComputeRoot32BitConstants(3, 1,"):
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
    # Cross-lane, LDS, barrier, atomics, images, global stores, control flow and the pixel stage's own forms.
    for bad in ("ds_write_b32 v4, v0", "ds_read_b32 v5, v4", "s_barrier", "v_readfirstlane_b32 s5, v0",
                "v_readlane_b32 s5, v0, 1", "v_writelane_b32 v5, s0, 1", "v_mbcnt_lo_u32_b32 v5, -1, 0",
                "s_bcnt1_i32_b64 s5, exec", "s_ff1_i32_b64 s5, exec", "v_permlane16_b32 v5, v0, s0, s0",
                "buffer_atomic_add v0, v4, s[8:11], 0 offen", "global_store_dword v[4:5], v0, off",
                "image_store v[0:3], v4, s[8:15] dmask:0xf dim:SQ_RSRC_IMG_1D unorm",
                "s_branch _L0", "s_cbranch_execz _L0", "_L0:", "s_getpc_b64 s[4:5]", "s_sendmsg sendmsg(MSG_DEALLOC_VGPRS)",
                "s_wqm_b64 exec, exec", "v_mov_b32_dpp v5, v0 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
                "exp mrt0 v0, v0, v0, v0 done compr vm", "v_interp_p1_f32_e32 v5, v0, attr0.x",
                "buffer_store_byte v0, v4, s[8:11], 0 offen", "buffer_store_short v0, v4, s[8:11], 0 offen",
                "buffer_store_format_x v0, v4, s[8:11], 0 offen", "flat_store_dword v[4:5], v0"):
        must_reject(program(bad))
        must_reject(program(bad, store))
    # Store operands and modifiers.
    for bad in ("buffer_store_dword v0, v4, s[8:11], 0 offen tfe", "buffer_store_dword v0, v4, s[8:11], 0 offen lds",
                "buffer_store_dword v0, v4, s[8:11], 0 offen offset:4096", "buffer_store_dword v0, v4, s[8:11], 0",
                "buffer_store_dword v0, off, s[8:11], 0 offen", "buffer_store_dword v0, v4, s[8:11], 0 offen idxen",
                "buffer_store_dword v0, v4, s[9:12], 0 offen", "buffer_store_dwordx2 v0, v4, s[8:11], 0 offen",
                "buffer_store_dwordx2 v[0:2], v4, s[8:11], 0 offen", "buffer_store_dword v9, v4, s[8:11], 0 offen",
                "buffer_store_dword v0, v9, s[8:11], 0 offen", "buffer_store_dword v0, v4, s[12:15], 0 offen",
                "buffer_store_dword v0, v4, s[8:11], s70 offen", "buffer_store_dword v0, v4, s[8:11], 0 offen glc glc"):
        must_reject(program(bad))
    # Store data from a load that has not completed, a load after a store, and a store while the lane may be inactive.
    load = "buffer_load_dword v6, v4, s[8:11], 0 offen offset:4"
    assert "buffer_load32" in program(load, "s_waitcnt vmcnt(0)", "buffer_store_dword v6, v4, s[8:11], 0 offen")()
    must_reject(program(load, "buffer_store_dword v6, v4, s[8:11], 0 offen"))
    must_reject(program(store, "buffer_load_dword v6, v4, s[8:11], 0 offen offset:4"))
    masked = ["v_cmp_gt_u32_e64 s[20:21], 5, v0", "s_mov_b64 s[22:23], exec", "s_and_b64 exec, exec, s[20:21]"]
    assert "buffer_store32(rsrc" in program(*masked[:2], store)()
    must_reject(program(*masked, store))
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
    check_adapter_skip(directory)


def check_binary(directory, assembler, objcopy, library):
    """Every draw program assembled by llvm-mc, disassembled again and lowered to the same HLSL."""
    for name, programs in FAMILIES.items():
        for index, (program, contract, *_) in enumerate(programs):
            source, obj, binary = (directory / f"{name}{index}.{ext}" for ext in ("s", "o", "bin"))
            source.write_text("\n".join(program) + "\n", encoding="ascii")
            subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013",
                            *(["-mattr=+wavefrontsize32"] if contract["wave"] == 32 else []),
                            "-filetype=obj", source, "-o", obj], check=True)
            subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
            decoded = disassemble(binary.read_bytes(), library)
            assert lower(decoded, contract) == lower(program, contract), (name, index)


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
