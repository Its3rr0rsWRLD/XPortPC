"""Draw family `load`: pixel_aot_check.py draw --family load."""
import subprocess

import pixel_aot
import pixel_memory_check as titlemem

from .common import M32, byte, half_rtz, lower, move, must_reject, translate, ubyte, with_constants
from .curve_shaping import curve


# MUBUF and global loads through runtime V# words and title memory. The constant buffer holds the inputs in words 3 to 6
# (loaded into s44 to s47 by with_constants) and three V# in words 8 to 11, 12 to 15 and 16 to 19; the descriptor-table
# entries at byte offsets 0x80, 0x90 and 0xa0 name those words, and each buffer program loads them into s[52:55],
# s[56:59] and s[60:63]. Memory is the pixel_memory_check section: slot 0 at 0xffffff00 (0x200 bytes, so it crosses the
# 4 GiB line at offset 0x100) and slot 1 at 0x200000400 (0x100 bytes); data exists on both sides of every limit a V#
# sets, so a missing check shows. Byte N of a loaded dword is read with v_cvt_f32_ubyteN. Integer words reach address
# registers through v_or_b32 with 0, not v_mov_b32, so no float conversion is involved. The references follow the gfx10
# rules of Mesa's ac_set_buf_desc_word3 (see tools/pixel_aot.py) on Python integers; a "flaw" switches one rule off to
# make a plausible wrong reference.
VSHARP_OFFSETS = {0x80: 8, 0x90: 12, 0xa0: 16}
BASE0, SIZE0, BASE1, SIZE1 = titlemem.BASE0, titlemem.SIZE0, titlemem.BASE1, titlemem.SIZE1
RANGES = ((BASE0, BASE0 + SIZE0, 0), (BASE1, BASE1 + SIZE1, 1))
LOAD_MEMORY = titlemem.section(RANGES, titlemem.SLOTS)
NOISE = (1 << 24) | (0x14 << 12) | 0xfac  # RESOURCE_LEVEL, a FORMAT value and DST_SEL_XYZW: fields the loads ignore
ZERO = (0, 0, 0, 0)


def translate_loads(instructions):
    return lower(instructions, 20, 24, [1, 2, 3, 4], constant_descriptor=64, buffer_descriptors=VSHARP_OFFSETS)


def vsharp(base, stride, records, select, swizzle=False, add_tid=False):
    assert base >> 48 == 0 and stride < 1 << 14
    return (base & M32, (base >> 32) | stride << 16 | swizzle << 31, records, NOISE | select << 28 | add_tid << 23)


def title_word(address):
    for begin, end, slot in RANGES:
        if begin <= address and address + 4 <= end and address % 4 == 0:
            return int.from_bytes(titlemem.SLOTS[slot][address - begin:address - begin + 4], "little")
    return None  # a lookup miss


def effective(terms, flaws):
    if "nocarry" in flaws:  # each 32-bit half summed on its own
        return (sum(t >> 32 for t in terms) << 32 | sum(t & M32 for t in terms) & M32) % (1 << 64)
    return sum(terms) % (1 << 64)


def settle(words, flaws):
    """Turn per-dword outcomes ('oob', 'miss' or a value) into the destination registers."""
    if "swap_dwords" in flaws:
        words = words[::-1]
    if "all_or_nothing" in flaws and "oob" in words:
        return [0] * len(words)
    out = []
    for word in words:
        if word == "miss" and "stale" in flaws:
            out.append(out[-1] if out else 0x5a5a5a5a)  # the previous register's value instead of 0
        else:
            out.append(0 if isinstance(word, str) else word)
    return out


def buffer_load(vs, soffset, voffset, inst, index, count, flaws=()):
    base, stride, records, select = vs[0] | (vs[1] & 0xffff) << 32, (vs[1] >> 16) & 0x3fff, vs[2], (vs[3] >> 28) & 3
    inst, soffset, index = (0 if "noinst" in flaws else inst), (0 if "nosoffset" in flaws else soffset), (0 if "noindex" in flaws else index)
    words = []
    for j in range(count):
        offset = voffset + inst + 4 * j
        index_out = index > records if "index_gt" in flaws else index >= records
        in_range = (not index_out and not (offset > stride if "isa_offset" in flaws else offset >= stride),
                    not index_out and not ("offset_in_mode1" in flaws and offset >= stride),
                    records != 0 and not ("index_check_mode2" in flaws and index >= records),
                    offset <= records if "le_records" in flaws else offset < records)[select]
        if offset >= 1 << 32 or vs[1] >> 31 or (vs[3] >> 23) & 1 or not (in_range or "nocheck" in flaws):
            words.append("oob")
            continue
        product = 0 if "nostride" in flaws else stride * index
        product &= M32 if "mul32" in flaws else (1 << 64) - 1
        word = title_word(effective([base, soffset, product, offset], flaws))
        words.append("miss" if word is None else word)
    return settle(words, flaws)


def global_load(base, voffset, inst, count, flaws=()):
    inst = 0 if "no_imm" in flaws else abs(inst) if "abs_imm" in flaws else inst & M32 if "imm_zext" in flaws else inst
    voffset = 0 if "no_voffset" in flaws else voffset
    words = [title_word(effective([base, voffset, inst % (1 << 64), 4 * j], flaws)) for j in range(count)]
    return settle(["miss" if w is None else w for w in words], flaws)


def load_program(*lines):
    return ["s_load_dwordx4 s[52:55], s[20:21], 0x80", "s_load_dwordx4 s[56:59], s[20:21], 0x90",
            "s_load_dwordx4 s[60:63], s[20:21], 0xa0", "s_waitcnt lgkmcnt(0)", *lines]


def global_program(*lines):
    return list(lines)


def readback(*pairs):
    return [ubyte(n, 12 + channel, f"v{register}", "e32") for channel, (register, n) in enumerate(pairs)]


def bytes_of(values, *picks):
    return [byte(values[k], n) for k, n in picks]


def ref_addressing(w, v, f=()):
    return [byte(buffer_load(v[0], w[0], w[1], 8, 0, 1, f)[0], 0), byte(buffer_load(v[0], 0, 0, 4, w[2], 1, f)[0], 1),
            byte(buffer_load(v[0], w[0], w[1], 12, w[2], 1, f)[0] if "swap" not in f else
                 buffer_load(v[0], w[0], w[2], 12, w[1], 1)[0], 2),
            byte(buffer_load(v[0], w[0], 0, 16, 0, 1, f)[0], 3)]


def ref_structured(w, v, f=()):
    return [byte(buffer_load(v[0], 0, 0, 28, w[0], 1, f)[0], 0), byte(buffer_load(v[0], 0, w[1], 0, 0, 1, f)[0], 1),
            byte(buffer_load(v[1], 0, 0, 0, w[2], 1, f)[0], 2), byte(buffer_load(v[1], 0, w[3], 0, 0, 1, f)[0], 3)]


def ref_modes23(w, v, f=()):
    return [byte(buffer_load(v[0], 0, w[0], 0, 0, 1, f)[0], 0), byte(buffer_load(v[0], 0, 0, 0, w[1], 1, f)[0], 1),
            byte(buffer_load(v[1], w[3], w[2], 0, 0, 1, f)[0], 2), byte(buffer_load(v[1], w[3], w[2], 4, 0, 1, f)[0], 3)]


def ref_x4(w, v, f=()):
    return bytes_of(buffer_load(v[0], 0, w[0], 0, 0, 4, f), (0, 0), (1, 0), (2, 0), (3, 0))


def ref_x2x3(w, v, f=()):
    x2, x3 = buffer_load(v[0], 0, w[0], 0, 0, 2, f), buffer_load(v[0], 0, w[1], 0, 0, 3, f)
    return [byte(x2[0], 1), byte(x2[1], 0), byte(x3[1], 2), byte(x3[2], 3)]


def ref_carry(w, v, f=()):
    return bytes_of(buffer_load(v[0], w[0], w[1], 0, 0, 4, f), (0, 0), (1, 0), (2, 0), (3, 0))


def ref_wide_stride(w, v, f=()):
    return [byte(buffer_load(v[0], 0, 0, 16, w[0], 1, f)[0], 0), byte(buffer_load(v[0], 0, w[1], 4, w[0], 1, f)[0], 1),
            byte(buffer_load(v[0], w[2], 0, 0, w[0], 1, f)[0], 2), byte(buffer_load(v[0], 0, 0, 0x28, w[0], 1, f)[0], 3)]


def ref_global(w, v, f=()):
    base = w[0] | w[1] << 32
    g3 = global_load(w[3] | w[1] << 32, 0, -2048, 2, f)
    return [byte(global_load(base, 0, -16, 1, f)[0], 0), byte(global_load(base, w[2], 8, 1, f)[0], 1),
            byte(g3[0], 2), byte(g3[1], 3)]


def ref_global_carry(w, v, f=()):
    base = w[0] | w[1] << 32
    x3, x4 = global_load(base, w[2], 0, 3, f), global_load(base, 0, 4, 4, f)
    return [byte(x3[1], 0), byte(x3[2], 0), byte(x4[1], 0), byte(x4[2], 0)]


STRIDE_INDEX = 0x50000
STRIDE_BASE = BASE1 + 0x80 - 0x3ffc * STRIDE_INDEX  # base + stride * index lands in slot 1 only if the product keeps all 64 bits
assert 0 < STRIDE_BASE < 1 << 48 and 0x3ffc * STRIDE_INDEX >> 32

LOAD_PROGRAMS = (
    # Structured V# (OOB_SELECT 0, stride 0x20, base in slot 1, so base bits 32 to 47 share word 1 with the stride):
    # offen, idxen, both (index in the first register) and neither, with soffset (s44) and the instruction offset.
    (load_program(
        move(18, "s45"), move(19, "s46"), move(22, "s46"), move(23, "s45"),
        "buffer_load_dword v24, v18, s[52:55], s44 offen offset:8",
        "buffer_load_dword v25, v19, s[52:55], 0 idxen offset:4",
        "buffer_load_dword v26, v[22:23], s[52:55], s44 idxen offen offset:12",
        "buffer_load_dword v27, off, s[52:55], s44 offset:16",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((0x40, 4, 3, 0), (vsharp(BASE1, 0x20, 8, 0), ZERO, ZERO)),
      ((0x20, 0x10, 5, 0), (vsharp(BASE1, 0x20, 8, 0), ZERO, ZERO))],
     ref_addressing,
     [(0, {"nosoffset"}), (1, {"nostride"}), (2, {"swap"}), (3, {"noinst"}), (1, {"noindex"})]),
    # OOB_SELECT 0 (index < records and offset < stride) and 1 (index < records): set 1 reads the last dword inside each
    # limit, set 2 the first dword outside it. The offset is not checked in mode 1.
    (load_program(
        move(18, "s44"), move(19, "s45"), move(20, "s46"), move(22, "s47"), move(23, "s47"),
        "v_and_b32_e64 v21, 0, s44",
        "buffer_load_dword v24, v18, s[52:55], 0 idxen offset:28",
        "buffer_load_dword v25, v19, s[52:55], 0 offen",
        "buffer_load_dword v26, v20, s[56:59], 0 idxen",
        "buffer_load_dword v27, v[21:22], s[56:59], 0 idxen offen",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((3, 0x1c, 5, 0x24), (vsharp(BASE1, 0x20, 4, 0), vsharp(BASE1 + 0x10, 0x10, 6, 1), ZERO)),
      ((4, 0x20, 6, 0x24), (vsharp(BASE1, 0x20, 4, 0), vsharp(BASE1 + 0x10, 0x10, 6, 1), ZERO))],
     ref_structured,
     [(0, {"nocheck"}), (0, {"index_gt"}), (1, {"nocheck"}), (1, {"isa_offset"}), (2, {"nocheck"}), (2, {"index_gt"}),
      (3, {"offset_in_mode1"})]),
    # OOB_SELECT 2 (num_records == 0 only; the index and offset are unchecked, and stride 0 ignores the index) and 3
    # (raw, offset < num_records, soffset outside the check).
    (load_program(
        move(18, "s44"), move(19, "s45"), move(20, "s46"),
        "buffer_load_dword v24, v18, s[52:55], 0 offen",
        "buffer_load_dword v25, v19, s[52:55], 0 idxen",
        "buffer_load_dword v26, v20, s[56:59], s47 offen",
        "buffer_load_dword v27, v20, s[56:59], s47 offen offset:4",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((0x10, 1000, 0x1c, 0x20), (vsharp(BASE0 + 0x40, 0, 1, 2), vsharp(BASE0 + 0x80, 0, 0x20, 3), ZERO)),
      ((0x10, 1000, 0x18, 0x40), (vsharp(BASE0 + 0x40, 0, 0, 2), vsharp(BASE0 + 0x80, 0, 0x20, 3), ZERO))],
     ref_modes23,
     [(0, {"nocheck"}), (1, {"nocheck"}), (1, {"index_check_mode2"}), (2, {"nosoffset"}), (3, {"nocheck"}), (3, {"le_records"})]),
    # buffer_load_dwordx4: every dword in order, then a window that crosses num_records so that only the first two
    # dwords are in range (each dword is checked on its own).
    (load_program(
        move(18, "s44"),
        "buffer_load_dwordx4 v[24:27], v18, s[52:55], 0 offen glc slc dlc",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 0), (26, 0), (27, 0))),
     [((0x08, 0, 0, 0), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO, ZERO)),
      ((0x28, 0, 0, 0), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO, ZERO))],
     ref_x4,
     [(0, {"swap_dwords"}), (3, {"swap_dwords"}), (2, {"nocheck"}), (0, {"all_or_nothing"})]),
    # buffer_load_dwordx2 and x3, the same window rule, and a different byte of each dword.
    (load_program(
        move(18, "s44"), move(19, "s45"),
        "buffer_load_dwordx2 v[24:25], v18, s[52:55], 0 offen",
        "buffer_load_dwordx3 v[26:28], v19, s[52:55], 0 offen",
        "s_waitcnt vmcnt(0)", *readback((24, 1), (25, 0), (27, 2), (28, 3))),
     [((0x20, 0x24, 0, 0), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO, ZERO)),
      ((0x2c, 0x28, 0, 0), (vsharp(BASE0 + 0x40, 0, 0x30, 3), ZERO, ZERO))],
     ref_x2x3,
     [(0, {"swap_dwords"}), (1, {"swap_dwords"}), (3, {"swap_dwords"}), (1, {"nocheck"}), (3, {"nocheck"}), (0, {"all_or_nothing"})]),
    # Address carries: base 0xfffffff0 plus soffset 0x20 crosses 4 GiB, and base plus voffset 8 plus 4 * dword does too.
    (load_program(
        move(18, "s45"),
        "buffer_load_dwordx4 v[24:27], v18, s[52:55], s44 offen",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 0), (26, 0), (27, 0))),
     [((0x20, 0, 0, 0), (vsharp(0xfffffff0, 0, 0x100, 3), ZERO, ZERO)),
      ((0, 8, 0, 0), (vsharp(0xfffffff0, 0, 0x100, 3), ZERO, ZERO))],
     ref_carry,
     [(0, {"nocarry"}), (2, {"nocarry"})]),
    # A lookup miss inside num_records: the V# allows 0x100 bytes, but title memory ends 0x40 bytes after the base. The
    # window crosses that end, so the first two dwords hit and the last two miss and read 0.
    (load_program(
        move(18, "s44"),
        "buffer_load_dwordx4 v[24:27], v18, s[52:55], 0 offen",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 0), (26, 0), (27, 0))),
     [((0x38, 0, 0, 0), (vsharp(BASE0 + 0x1c0, 0, 0x100, 3), ZERO, ZERO)),
      ((0x30, 0, 0, 0), (vsharp(BASE0 + 0x1c0, 0, 0x100, 3), ZERO, ZERO))],
     ref_x4,
     [(2, {"stale"}), (3, {"stale"}), (0, {"swap_dwords"})]),
    # base + stride * index needs more than 32 bits: 0x3ffc * 0x50000 is above 4 GiB, and the base makes the sum land in slot 1.
    (load_program(
        move(18, "s44"), move(22, "s44"), move(23, "s45"),
        "buffer_load_dword v24, v18, s[52:55], 0 idxen offset:16",
        "buffer_load_dword v25, v[22:23], s[52:55], 0 idxen offen offset:4",
        "buffer_load_dword v26, v18, s[52:55], s46 idxen",
        "buffer_load_dword v27, v18, s[52:55], 0 idxen offset:40",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((STRIDE_INDEX, 0x14, 0x20, 0), (vsharp(STRIDE_BASE, 0x3ffc, 0x60000, 0), ZERO, ZERO))],
     ref_wide_stride,
     [(0, {"mul32"}), (1, {"mul32"}), (2, {"nosoffset"}), (3, {"nostride"})]),
    # global_load: a 64-bit VGPR pair with a negative immediate, an SGPR base plus a 32-bit VGPR offset, and an x2 load whose
    # base is 2048 above its data (the most negative 12-bit immediate).
    (global_program(
        move(18, "s44"), move(19, "s45"), move(20, "s46"), move(21, "s47"), move(22, "s45"),
        "global_load_dword v24, v[18:19], off offset:-16",
        "global_load_dword v25, v20, s[44:45] offset:8",
        "global_load_dwordx2 v[26:27], v[21:22], off offset:-2048 glc",
        "s_waitcnt vmcnt(0)", *readback((24, 0), (25, 1), (26, 2), (27, 3))),
     [((BASE1 + 0x40 & M32, 2, 0x10, BASE1 + 0x20 + 2048 & M32), (ZERO, ZERO, ZERO)),
      ((0x80, 1, 0x20, 0x8e0), (ZERO, ZERO, ZERO))],
     ref_global,
     [(0, {"imm_zext"}), (0, {"abs_imm"}), (1, {"no_voffset"}), (2, {"no_imm"}), (3, {"no_imm"})]),
    # global_load carries and misses: x3 with an SGPR base and x4 with a register pair from 0xfffffff8, which crosses 4 GiB
    # inside the dwords; then a base at the end of title memory, where the later dwords miss and read 0.
    (global_program(
        move(18, "s44"), move(19, "s45"), move(20, "s46"),
        "global_load_dwordx3 v[26:28], v20, s[44:45]",
        "global_load_dwordx4 v[30:33], v[18:19], off offset:4 dlc",
        "s_waitcnt vmcnt(0)", *readback((27, 0), (28, 0), (31, 0), (32, 0))),
     [((0xfffffff8, 0, 0, 0), (ZERO, ZERO, ZERO)),
      ((0xf8, 1, 0, 0), (ZERO, ZERO, ZERO))],
     ref_global_carry,
     [(1, {"nocarry"}), (2, {"nocarry"}), (1, {"swap_dwords"}), (1, {"stale"}), (2, {"stale"})]),
)


def check_load_draws(directory, compiler, renderer, backend):
    case = directory / "loads.case"
    for index, (body, sets, reference, bugs) in enumerate(LOAD_PROGRAMS):
        source = directory / f"load{index}.hlsl"
        shader = directory / f"load{index}.cso"
        source.write_text(translate_loads(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for inputs, sharps in sets:
            words = [0] * 64
            words[3:7] = inputs
            words[8:20] = [word for vs in sharps for word in vs]
            expected = [float(value) for value in reference(inputs, sharps)]
            for value in expected:
                assert half_rtz(value) == value, value
            case.write_bytes(titlemem.case_file(words, expected, LOAD_MEMORY))
            subprocess.run(draw, check=True)
            for k, (channel, flaws) in enumerate(bugs):
                value = float(reference(inputs, sharps, flaws)[channel])
                if value == expected[channel]:
                    continue
                separated[k] = True
                wrong = list(expected)
                wrong[channel] = value
                case.write_bytes(titlemem.case_file(words, wrong, LOAD_MEMORY))
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong load result escaped detection in program {index}, channel {channel}, {sorted(flaws)}")
        assert all(separated), (index, separated)


def check_load_controls() -> None:
    wait = ["s_waitcnt lgkmcnt(0)"]
    descriptor = ["s_load_dwordx4 s[52:55], s[20:21], 0x80"]
    load = "buffer_load_dword v24, v18, s[52:55], 0 offen"
    ready = [move(18, "s45"), *descriptor, *wait]

    def buffer_case(*lines):
        return translate_loads(with_constants([*ready, *lines]))

    # Memory declarations and the title lookup are present only when a program loads, and V# words are runtime parameters.
    source = buffer_case(load, "s_waitcnt vmcnt(0)", ubyte(0, 12, "v24", "e32"))
    assert pixel_aot.TITLE_LOOKUP.read_text(encoding="utf-8") in source and pixel_aot.TITLE_DECLARATIONS in source, source
    assert "uint4 rsrc" in source and "params[2].x, params[2].y" in source and "asuint(params[2]" not in source, source
    assert "title_memory" not in translate(curve()) and "TitleLookup" not in translate(curve())
    # A load's registers are unusable before vmcnt(0); a store over one, a V# not yet loaded and a bad window are refused.
    must_reject(translate_loads, with_constants([*ready, load, ubyte(0, 12, "v24", "e32")]))
    must_reject(translate_loads, with_constants([*ready, load, "v_or_b32_e64 v25, 0, v24"]))
    must_reject(translate_loads, with_constants([*ready, load, "v_add_f32_e64 v25, v24, 1.0"]))
    must_reject(translate_loads, with_constants([*ready, load, "v_or_b32_e64 v24, 0, s44"]))
    must_reject(translate_loads, with_constants([move(18, "s45"), *descriptor, load]))
    must_reject(translate_loads, with_constants([*ready, "s_waitcnt vmcnt(0)", ubyte(0, 12, "v24", "e32")]))
    # Descriptor offsets that overlap the texture descriptor (0 to 31) or the constant descriptor (0x40 to 0x4f), or are
    # misaligned, and buffer descriptors without a constant descriptor.
    program = with_constants([*ready, load, "s_waitcnt vmcnt(0)", ubyte(0, 12, "v24", "e32")])
    for offsets in ({0x10: 8}, {0x20: 8, 0x1c: 12}, {0x40: 8}, {0x3c: 8}, {0x84: 8}, {0x80: 61}, {0x80: -1}, {0x80: 8, 0x88: 12}):
        must_reject(lambda: lower(program, 20, 24, [1, 2, 3, 4], 64, buffer_descriptors=offsets))
    must_reject(lambda: lower(program, 20, 24, [1, 2, 3, 4], None, buffer_descriptors={0x80: 8}))
    must_reject(lambda: lower(program, 20, 24, [1, 2, 3, 4], 64, buffer_descriptors={0x80: 8}, second_texture_offset=0x80))
    must_reject(lambda: lower(program, 20, 24, [1, 2, 3, 4], 64))  # a descriptor that is not declared is still refused
    # flat loads, unsupported modifiers and malformed operands.
    must_reject(translate_loads, with_constants([move(18, "s45"), move(19, "s46"), "flat_load_dword v24, v[18:19]"]))
    for bad in ("buffer_load_dword v[24:25], v18, s[52:55], 0 offen tfe",
                "buffer_load_dword v24, v18, s[52:55], 0 offen lds",
                "buffer_load_dword v24, v18, s[52:55], 0 offen offset:4096",
                "buffer_load_dword v24, v18, s[52:55], 0 offen offen",
                "buffer_load_dword v24, v18, s[52:55], 0 offen glc glc",
                "buffer_load_dword v24, v18, s[52:55], 0",
                "buffer_load_dword v24, off, s[52:55], 0 offen",
                "buffer_load_dword v24, v18, s[52:55], 0 offen idxen",
                "buffer_load_dword v24, v18, s[53:56], 0 offen",
                "buffer_load_dword v24, v18, s[52:55], 1 offen",
                "buffer_load_dwordx2 v24, v18, s[52:55], 0 offen",
                "buffer_load_dwordx2 v[24:26], v18, s[52:55], 0 offen",
                "buffer_load_dword v24, v[18:19], s[52:55], 0 offen",
                "buffer_load_dword v24, v18, s[28:31], 0 offen",  # texture descriptor words are not numbers
                "buffer_load_dword v24, v30, s[52:55], 0 offen",
                "buffer_load_ubyte v24, v18, s[52:55], 0 offen",
                "buffer_load_format_x v24, v18, s[52:55], 0 offen",
                "buffer_store_dword v24, v18, s[52:55], 0 offen",
                "buffer_load_dword v24, v18, s[52:55], s70 offen"):
        must_reject(translate_loads, with_constants([*ready, bad]))
    for bad in ("global_load_dword v24, v[18:19], off tfe", "global_load_dword v24, v[18:19], off offset:2048",
                "global_load_dword v24, v[18:19], off offset:-2049", "global_load_dword v24, v18, off",
                "global_load_dword v24, v[18:19], s[44:45]", "global_load_dword v24, v20, s[45:46]",
                "global_load_dword v24, v20, s44", "global_load_dword v24, v[18:19], off offset:4 offset:4",
                "global_load_ubyte v24, v[18:19], off", "global_store_dword v[18:19], v24, off"):
        must_reject(translate_loads, with_constants([move(18, "s44"), move(19, "s45"), move(20, "s46"), bad]))


def controls(directory):
    check_load_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate_loads) for body, *_ in LOAD_PROGRAMS),
    ]


draw = check_load_draws
