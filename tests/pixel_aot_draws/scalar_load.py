"""Draw family `scalar_load`: pixel_aot_check.py draw --family scalar_load."""
import re
import struct
import subprocess

from .common import half_rtz, lower, must_reject, translate, ubyte, with_constants


# Wide scalar loads. s_buffer_load_dword{,x2,x4,x8,x16} read constant words through the constant descriptor and
# s_load_dword{,x2,x4,x8,x16} read descriptor-table words: the constant descriptor at 0x40 and the V#s of
# SCALAR_TABLE. Every draw reads four loaded words through the byte readback; a word is folded to one byte by
# FOLD (t = w ^ w >> 16, then t ^ t >> 8, byte 0), so that all 32 bits of it matter, and the words are chosen so
# that the 64 folds differ. The load goes into s64 to s95, apart from the base descriptor in s44 to s47, and
# s96 holds a constant SGPR offset. Each program lists the registers read and the constant words they must hold
# (word k is bytes 4k to 4k + 3 of the case's constants), and wrong word lists that a plausible bug would read.
SCALAR_TABLE = {0x50: 24, 0x60: 28, 0x70: 32}


def translate_table(instructions):
    return lower(instructions, 20, 24, [1, 2, 3, 4], constant_descriptor=64, buffer_descriptors=SCALAR_TABLE)


def fold32(word):
    t = word ^ (word >> 16)
    return (t ^ (t >> 8)) & 0xff


def scalar_load_words(seed):
    words, folds, state = [], set(), seed
    while len(words) < 64:
        state = (state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        word = state >> 32
        if fold32(word) and fold32(word) not in folds:
            folds.add(fold32(word))
            words.append(word)
    return words


SCALAR_LOAD_SETS = (scalar_load_words(0x5eed0001), scalar_load_words(0x5eed0002))


def folded(registers):
    lines = []
    for channel, register in enumerate(registers):
        lines += [f"v_lshrrev_b32_e64 v18, 16, {register}", f"v_xor_b32_e32 v18, {register}, v18",
                  "v_lshrrev_b32_e32 v19, 8, v18", "v_xor_b32_e32 v18, v19, v18", ubyte(0, 12 + channel, "v18", "e32")]
    return lines


def with_scalar_loads(loads, body, lgkm="s_waitcnt lgkmcnt(0)", vm="s_waitcnt vmcnt(0)"):
    """with_constants with its constant read replaced by loads; lgkm and vm replace the two waits after it."""
    program = with_constants(body)
    at = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc")
    assert program[at + 1] == "s_waitcnt lgkmcnt(0)"
    program[at:at + 2] = [*loads, *([lgkm] if isinstance(lgkm, str) else lgkm)]
    at = program.index("s_waitcnt vmcnt(0)")
    program[at:at + 1] = [vm] if isinstance(vm, str) else list(vm)
    return program


def group(first, count=4):
    return [f"s{first + k}" for k in range(count)]


def words_of(first, count=4):
    return list(range(first, first + count))


def wrong(indices, **flaws):
    """The word lists that bugs read: the offset ignored, the words in reverse order or one word late."""
    return {name: list(value) for name, value in flaws.items()} | {
        "reversed": indices[::-1], "next": [k + 1 for k in indices]}


SPLIT_WAITS = {"lgkm": "s_waitcnt_lgkmcnt null, 0x0",
               "vm": ["s_waitcnt_vmcnt null, 0x0", "s_waitcnt_vscnt null, 0x0", "s_waitcnt_depctr 0xffe3",
                      "s_waitcnt_depctr 0xfffe"]}
COMBINED_WAITS = {"lgkm": "s_waitcnt vmcnt(0) lgkmcnt(0)",
                  "vm": ["s_waitcnt expcnt(0)", "s_waitcnt_expcnt null, 0x0", "s_waitcnt_vscnt null, 0x3f",
                         "s_waitcnt_depctr 0x0"]}
ALL_WAITS = {"lgkm": "s_waitcnt vmcnt(0) expcnt(0) lgkmcnt(0)", "vm": "s_waitcnt_vmcnt null, 0x0"}

X16 = ["s_buffer_load_dwordx16 s[64:79], s[44:47], 0x40"]  # words 16 to 31
X8 = ["s_buffer_load_dwordx8 s[80:87], s[44:47], 0x78"]  # words 30 to 37
SIZES = [("x16 at 0x40", X16, group(64 + 4 * g), words_of(16 + 4 * g), {"no_offset": words_of(4 * g)})
         for g in range(4)]
SIZES += [("x8 at 0x78", X8, group(80 + 4 * g), words_of(30 + 4 * g), {"no_offset": words_of(4 * g)})
          for g in range(2)]
SCALAR_LOAD_PROGRAMS = [
    # (name, loads, registers read, their constant words, wrong word lists, translate, wait spellings)
    *((name, load, regs, idx, wrong(idx, **flaws), translate, {}) for name, load, regs, idx, flaws in SIZES),
    # x2 at the last two words, an SGPR offset (word 33), and glc dlc.
    ("x2, SGPR offset, glc dlc",
     ["s_buffer_load_dwordx2 s[92:93], s[44:47], 0xf8", "s_mov_b32 s96, 0x84", "s_buffer_load_dword s94, s[44:47], s96",
      "s_buffer_load_dword s95, s[44:47], 0x20 glc dlc"],
     ["s92", "s93", "s94", "s95"], [62, 63, 33, 8],
     {"no_sgpr": [62, 63, 0, 8], "swap_pair": [63, 62, 33, 8], "previous": [61, 62, 32, 7]}, translate, {}),
    # x4 at an SGPR offset plus an offset: field (words 37 to 40).
    ("x4, SGPR offset plus offset:", ["s_mov_b32 s96, 0x84", "s_buffer_load_dwordx4 s[88:91], s[44:47], s96 offset:0x10"],
     group(88), [37, 38, 39, 40],
     wrong([37, 38, 39, 40], no_sgpr=[4, 5, 6, 7], no_field=[33, 34, 35, 36]), translate, {}),
    # s_load of 16 dwords from the constant descriptor: three V#s at 0x50, 0x60 and 0x70 (params words 24 to 35).
    *((f"s_load x16, V# {k}", ["s_load_dwordx16 s[64:79], s[20:21], 0x40"], group(68 + 4 * k), words_of(24 + 4 * k),
       wrong(words_of(24 + 4 * k), table_start=words_of(4 * k)), translate_table, {}) for k in range(3)),
    # The first four words of that load are the constant descriptor: reading through s[64:67] works.
    ("s_load x16, constant words through the loaded descriptor",
     ["s_load_dwordx16 s[64:79], s[20:21], 0x40", "s_waitcnt lgkmcnt(0)", "s_buffer_load_dwordx4 s[80:83], s[64:67], 0x10"],
     group(80), words_of(4), wrong(words_of(4), no_offset=words_of(0)), translate_table, {}),
    # s_load x8 starting in the middle of a V# (0x58 to 0x77: words 26 to 33).
    *((f"s_load x8 at 0x58, half {k}", ["s_load_dwordx8 s[80:87], s[20:21], 0x58"], group(80 + 4 * k),
       words_of(26 + 4 * k), wrong(words_of(26 + 4 * k), aligned_down=words_of(24 + 4 * k)), translate_table, {})
      for k in range(2)),
    ("s_load x2, x1, glc",
     ["s_load_dwordx2 s[88:89], s[20:21], 0x78", "s_load_dword s90, s[20:21], 0x6c", "s_load_dword s91, s[20:21], 0x50 glc"],
     ["s88", "s89", "s90", "s91"], [34, 35, 31, 24],
     {"swap_pair": [35, 34, 31, 24], "no_offset": [32, 33, 28, 24], "next": [35, 36, 32, 25]}, translate_table, {}),
    ("s_load x4, SGPR offset plus offset:", ["s_mov_b32 s96, 0x60", "s_load_dwordx4 s[92:95], s[20:21], s96 offset:0x10"],
     group(92), words_of(32), wrong(words_of(32), no_sgpr=words_of(24), no_field=words_of(28)), translate_table, {}),
    # A constant descriptor assembled from two s_load_dwordx2, then an x8 read through it (words 44 to 51).
    ("two s_load x2 make a descriptor",
     ["s_load_dwordx2 s[64:65], s[20:21], 0x40", "s_load_dwordx2 s[66:67], s[20:21], 0x48", "s_waitcnt lgkmcnt(0)",
      "s_buffer_load_dwordx8 s[80:87], s[64:67], 0xb0"],
     ["s80", "s83", "s84", "s87"], [44, 47, 48, 51],
     {"reversed": [51, 48, 47, 44], "no_offset": [0, 3, 4, 7], "next": [45, 48, 49, 52]}, translate_table, {}),
    # The split and combined wait spellings give the same result as the plain waits.
    *((f"{name} waits", X16, group(64), words_of(16), {}, translate, waits)
      for name, waits in (("split", SPLIT_WAITS), ("combined", COMBINED_WAITS), ("all-counter", ALL_WAITS))),
]


def check_scalar_load_draws(directory, compiler, renderer, backend):
    case = directory / "scalar_load.case"
    for index, (name, loads, regs, indices, flaws, translator, waits) in enumerate(SCALAR_LOAD_PROGRAMS):
        source = directory / f"scalar_load{index}.hlsl"
        shader = directory / f"scalar_load{index}.cso"
        source.write_text(translator(with_scalar_loads(loads, folded(regs), **waits)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = dict.fromkeys(flaws, False)
        for words in SCALAR_LOAD_SETS:
            constants = struct.pack("<64I", *words)
            expected = [float(fold32(words[k])) for k in indices]
            for value in expected:
                assert half_rtz(value) == value, value
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for flaw, buggy in flaws.items():
                if separated[flaw]:
                    continue
                values = [float(fold32(words[k])) for k in buggy]
                channel = next((c for c in range(4) if values[c] != expected[c]), None)
                if channel is None:
                    continue
                separated[flaw] = True
                bad = list(expected)
                bad[channel] = values[channel]
                case.write_bytes(constants + struct.pack("<4f", *bad) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong scalar load escaped detection in program {name!r}, {flaw}")
        assert all(separated.values()), (name, separated)


def refuses(translator, reason, program):
    try:
        translator(program)
    except ValueError as error:
        assert reason in str(error), (reason, str(error), program)
        return
    raise AssertionError(f"{reason!r}: invalid program accepted: {program}")


def check_scalar_load_controls() -> None:
    def make(*loads, regs=(), **waits):
        return with_scalar_loads(list(loads), folded(regs), **waits)

    # The last word is params[15].w, and the x16 load at 0xc0 is the widest accepted read.
    source = translate(make("s_buffer_load_dwordx16 s[64:79], s[44:47], 0xc0", regs=group(76)))
    assert "params[15].w" in source and "params[15].x" in source, source
    for load, regs in (("s_buffer_load_dwordx8 s[80:87], s[44:47], 0xe0", group(84)),
                       ("s_buffer_load_dwordx4 s[88:91], s[44:47], 0xf0", group(88)),
                       ("s_buffer_load_dwordx2 s[92:93], s[44:47], 0xf8", group(92, 2) + group(92, 2)),
                       ("s_buffer_load_dword s94, s[44:47], 0xfc", ["s94"] * 4),
                       ("s_buffer_load_dword s94, s[44:47], 0xfc glc dlc", ["s94"] * 4),
                       ("s_buffer_load_dwordx2 s[104:105], s[44:47], null", ["s104"] * 4)):
        translate(make(load, regs=regs))
    # A read that ends past constant word 63 is refused, whatever its width.
    for load in ("s_buffer_load_dwordx16 s[64:79], s[44:47], 0xc4", "s_buffer_load_dwordx16 s[64:79], s[44:47], 0xd0",
                 "s_buffer_load_dwordx16 s[64:79], s[44:47], 0x100", "s_buffer_load_dwordx8 s[80:87], s[44:47], 0xe4",
                 "s_buffer_load_dwordx4 s[88:91], s[44:47], 0xf4", "s_buffer_load_dwordx2 s[92:93], s[44:47], 0xfc",
                 "s_buffer_load_dword s94, s[44:47], 0x100"):
        refuses(translate, "exceeds", make(load))
    for imm in ("0x2", "0x42", "0x100000"):
        refuses(translate, "misaligned or out of range", make(f"s_buffer_load_dword s94, s[44:47], {imm}"))
    # SGPR offsets are added to the immediate; a past-the-end sum and a misaligned one are refused.
    refuses(translate, "exceeds", make("s_mov_b32 s96, 0xf8", "s_buffer_load_dwordx4 s[88:91], s[44:47], s96"))
    refuses(translate, "exceeds", make("s_mov_b32 s96, 0xe8", "s_buffer_load_dwordx4 s[88:91], s[44:47], s96 offset:0x10"))
    refuses(translate, "misaligned", make("s_mov_b32 s96, 0x3", "s_buffer_load_dword s94, s[44:47], s96"))
    # An offset register must hold a value known when translating: a loaded word, a pending one and an unset one are not.
    for loads in (["s_buffer_load_dword s96, s[44:47], 0x8", "s_waitcnt lgkmcnt(0)"], ["s_buffer_load_dword s96, s[44:47], 0x8"], []):
        refuses(translate, "known constant", make(*loads, "s_buffer_load_dword s94, s[44:47], s96"))
    must_reject(translate, make("s_buffer_load_dword s94, s[44:47], 0x10 offset:0x10"))
    # Destination ranges: 64-bit pairs are even-aligned, wider ranges are 4-aligned, and s105 is the last SGPR.
    for load in ("s_buffer_load_dwordx16 s[66:81], s[44:47], 0x40", "s_buffer_load_dwordx16 s[96:111], s[44:47], 0x40",
                 "s_buffer_load_dwordx16 s[64:78], s[44:47], 0x40", "s_buffer_load_dwordx8 s[62:69], s[44:47], 0x40",
                 "s_buffer_load_dwordx8 s[100:107], s[44:47], 0x40", "s_buffer_load_dwordx4 s[66:69], s[44:47], 0x40",
                 "s_buffer_load_dwordx4 s[88:90], s[44:47], 0x40", "s_buffer_load_dwordx2 s[65:66], s[44:47], 0x40",
                 "s_buffer_load_dwordx2 s[88:88], s[44:47], 0x40", "s_buffer_load_dwordx4 s88, s[44:47], 0x40",
                 "s_load_dwordx16 s[66:81], s[20:21], 0x40", "s_load_dwordx8 s[62:69], s[20:21], 0x40",
                 "s_load_dwordx4 s[66:69], s[20:21], 0x40", "s_load_dwordx2 s[65:66], s[20:21], 0x40"):
        refuses(translate_table, "destination", make(load))
    refuses(translate, "out of range", make("s_buffer_load_dword s106, s[44:47], 0x40"))
    # The base must be the loaded constant descriptor: misaligned, texture words and a descriptor not yet loaded are not.
    for base, reason in (("s[45:48]", "Invalid scalar buffer"), ("s[28:31]", "Unresolved"), ("s[64:67]", "Unresolved")):
        refuses(translate, reason, make(f"s_buffer_load_dword s94, {base}, 0x40"))
    refuses(translate_table, "Unresolved", make("s_load_dwordx16 s[64:79], s[20:21], 0x40", "s_buffer_load_dword s94, s[64:67], 0x40"))
    # A result read before s_waitcnt lgkmcnt(0), in the first and the last register of a wide load, and writes that
    # overlap an outstanding load.
    for regs in (group(64), group(76), ["s64", "s70", "s75", "s79"]):
        refuses(translate, "before load completion", make(*X16, regs=regs, lgkm=[]))
    refuses(translate, "Unresolved scalar memory dependency", make(*X16, "s_mov_b32 s79, 0", lgkm=[]))
    refuses(translate, "outstanding", make(*X16, "s_buffer_load_dwordx4 s[76:79], s[44:47], 0x0"))
    refuses(translate, "outstanding", make("s_buffer_load_dwordx2 s[64:65], s[44:47], 0x0",
                                           "s_buffer_load_dwordx8 s[64:71], s[44:47], 0x0"))
    ok = make(*X16, regs=group(64))
    assert ok.count("s_waitcnt lgkmcnt(0)") == 2
    # Descriptor-table reads: only words of tracked descriptors. Without V#s the constant descriptor alone is tracked.
    translate(make("s_load_dwordx2 s[64:65], s[20:21], 0x40"))
    translate(make("s_load_dwordx2 s[64:65], s[20:21], 0x48"))
    translate(make("s_load_dword s64, s[20:21], 0x4c"))
    for load in ("s_load_dwordx16 s[64:79], s[20:21], 0x40", "s_load_dwordx8 s[64:71], s[20:21], 0x40",
                 "s_load_dwordx4 s[64:67], s[20:21], 0x44", "s_load_dwordx2 s[64:65], s[20:21], 0x4c"):
        refuses(translate, "not a tracked descriptor", make(load))
    for load in ("s_load_dwordx16 s[64:79], s[20:21], 0x40", "s_load_dwordx8 s[64:71], s[20:21], 0x58",
                 "s_load_dwordx4 s[64:67], s[20:21], 0x44", "s_load_dwordx8 s[64:71], s[20:21], 0x50",
                 "s_load_dword s64, s[20:21], 0x7c", "s_load_dwordx4 s[64:67], s[20:21], 0x50 glc dlc"):
        translate_table(make(load))
    for load in ("s_load_dwordx16 s[64:79], s[20:21], 0x50", "s_load_dwordx8 s[64:71], s[20:21], 0x70",
                 "s_load_dwordx16 s[64:79], s[20:21], 0x30", "s_load_dwordx2 s[64:65], s[20:21], 0x0",
                 "s_load_dwordx2 s[64:65], s[20:21], 0x80", "s_load_dword s64, s[20:21], 0x3c",
                 "s_load_dwordx4 s[64:67], s[20:21], 0x4"):
        refuses(translate_table, "not a tracked descriptor", make(load))
    # The address pair must be the descriptor-table pointer. A V# is not a constant buffer, so s_buffer_load from one,
    # or from words read at a shifted offset, is refused.
    for load in ("s_load_dwordx4 s[64:67], s[22:23], 0x40", "s_load_dwordx4 s[64:67], s[21:22], 0x40"):
        must_reject(translate, make(load))
    for load in ("s_load_dwordx4 s[64:67], s[20:21], 0x44", "s_load_dwordx4 s[64:67], s[20:21], 0x50"):
        refuses(translate_table, "Unresolved", make(load, "s_waitcnt lgkmcnt(0)", "s_buffer_load_dword s94, s[64:67], null"))
    refuses(translate_table, "Unresolved", make("s_load_dwordx2 s[64:65], s[20:21], 0x40", "s_waitcnt lgkmcnt(0)",
                                                "s_load_dwordx2 s[66:67], s[20:21], 0x4c", "s_waitcnt lgkmcnt(0)",
                                                "s_buffer_load_dword s94, s[64:67], null"))
    # Wait spellings. The split and combined forms with count 0 clear what the plain forms clear, and no other
    # counter does: a vmcnt wait does not finish a scalar load, and lgkmcnt, expcnt, vscnt and depctr do not finish a sample.
    sample_free = ["s_waitcnt_vscnt null, 0x0", "s_waitcnt_depctr 0xffe3", "s_waitcnt expcnt(0)", "s_waitcnt_expcnt null, 0x0",
                   "s_waitcnt_lgkmcnt null, 0x0", "s_waitcnt lgkmcnt(0)", "s_waitcnt_depctr 0x0"]
    for wait in sample_free:
        must_reject(translate, make(*X16, regs=group(64), vm=wait))
    for wait in ("s_waitcnt_vmcnt null, 0x0", "s_waitcnt vmcnt(0)", "s_waitcnt_vscnt null, 0x0", "s_waitcnt_expcnt null, 0x0",
                 "s_waitcnt expcnt(0)", "s_waitcnt_depctr 0xfffe", "s_waitcnt_depctr 0x1234"):
        must_reject(translate, make(*X16, regs=group(64), lgkm=wait))
    for wait in ("s_waitcnt_vmcnt null, 0x0", "s_waitcnt vmcnt(0) lgkmcnt(0)", "s_waitcnt vmcnt(0) expcnt(0) lgkmcnt(0)"):
        translate(make(*X16, regs=group(64), vm=["s_waitcnt vmcnt(0)", wait]))
    # Temporaries are numbered by instruction index, so compare the computation with the numbers removed.
    shape = lambda source: re.sub(r"(valu|alu)\d+", r"\1", source)
    for waits in (SPLIT_WAITS, COMBINED_WAITS, ALL_WAITS):
        assert shape(translate(make(*X16, regs=group(64), **waits))) == shape(translate(make(*X16, regs=group(64))))
    # Nonzero counts are refused in every spelling the plain forms refuse (the lone s_waitcnt vmcnt(N) is the one
    # partial wait, see dual_texture partial controls), and so are repeats and SGPR operands.
    for wait in ("s_waitcnt_vmcnt null, 0x1", "s_waitcnt_lgkmcnt null, 0x2",
                 "s_waitcnt_vmcnt null, 0xffff", "s_waitcnt vmcnt(1) lgkmcnt(0)", "s_waitcnt vmcnt(0) lgkmcnt(1)",
                 "s_waitcnt lgkmcnt(0) lgkmcnt(0)", "s_waitcnt vmcnt(0) vmcnt(0)"):
        for slot in ("lgkm", "vm"):
            refuses(translate, "Only zero wait counts", make(*X16, regs=group(64), **{slot: wait}))
    # A nonzero export-counter wait is accepted (exports are the return of main, so it orders nothing: R0Y00/
    # Xbox2Windows#271), but it completes no load either, so in place of the load's wait the program is refused.
    for wait in ("s_waitcnt_expcnt null, 0x1", "s_waitcnt expcnt(1)"):
        for slot in ("lgkm", "vm"):
            must_reject(translate, make(*X16, regs=group(64), **{slot: wait}))
    for wait in ("s_waitcnt_vmcnt s5, 0x0", "s_waitcnt_lgkmcnt exec_lo, 0x0", "s_waitcnt_vscnt s5, 0x0",
                 "s_waitcnt_expcnt vcc_lo, 0x0", "s_waitcnt_vscnt null, 0x10000", "s_waitcnt_depctr 0x10000",
                 "s_waitcnt_depctr", "s_waitcnt_depctr depctr_bogus(0)", "s_waitcnt_depctr 0xffe3 0xffe3"):
        for slot in ("lgkm", "vm"):
            must_reject(translate, make(*X16, regs=group(64), **{slot: wait}))


def controls(directory):
    check_scalar_load_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_scalar_loads(loads, folded(regs), **waits), translator)
          for _, loads, regs, _, _, translator, waits in SCALAR_LOAD_PROGRAMS),
    ]


draw = check_scalar_load_draws
