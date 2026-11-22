"""Draw family `load_sub`: pixel_aot_check.py draw --family load_sub."""
import subprocess

import pixel_aot
import pixel_memory_check as titlemem

from .common import M32, byte, half_rtz, lower, move, must_reject, translate, with_constants
from .load import (BASE0, BASE1, LOAD_MEMORY, RANGES, ZERO, effective, global_program, load_program, readback,
                   translate_loads, vsharp)


# Sub-dword loads through title memory: buffer_load_{ubyte,sbyte,ushort,sshort} and the d16 and d16_hi variants, and the
# same ten global_load forms with and without saddr. Every program loads into v24 and reads all four bytes of the loaded
# word back, so the zero or sign extension (bytes 1 to 3) and the half a d16 load must keep (bytes of the old value, put
# there with v_or_b32 from constant word 0, or word 3 for the global forms) are all checked. The references are written here
# from the ISA rules on Python integers and do not share code with the lowering; a "flaw" switches one rule off to make a
# plausible wrong reference, and every flaw of every table row must separate from the right answer in at least one set.
OPS = {
    "ubyte": (1, False, None), "sbyte": (1, True, None), "ushort": (2, False, None), "sshort": (2, True, None),
    "ubyte_d16": (1, False, "lo"), "ubyte_d16_hi": (1, False, "hi"), "sbyte_d16": (1, True, "lo"),
    "sbyte_d16_hi": (1, True, "hi"), "short_d16": (2, False, "lo"), "short_d16_hi": (2, False, "hi"),
}
OLD = (0x9b5ac3e1, 0x6c2d8f17)


def mem_byte(address):
    for begin, end, slot in RANGES:
        if begin <= address < end:
            return titlemem.SLOTS[slot][address - begin]
    return 0  # a lookup miss reads zero


def mem_read(address, size):
    return sum(mem_byte(address + k) << (8 * k) for k in range(size))


def extend(op, address, old, flaws):
    """The destination word of a load of `op` at `address` (None: out of range, which reads zero)."""
    size, signed, half = OPS[op]
    size = 3 - size if "width_swap" in flaws else size
    signed = signed != ("flip_ext" in flaws)
    bits = 8 * size
    value = 0
    if address is not None:
        address += 1 if "shift1" in flaws else 0
        address &= ~3 if "align_down" in flaws else -1
        value = mem_read(address % (1 << 64), size)
    if signed and value >> (bits - 1):
        value -= 1 << bits
    if half is None:
        return value & M32
    half = {"lo": "hi", "hi": "lo"}[half] if "wrong_half" in flaws else half
    keep = 0 if "no_preserve" in flaws else old & (0xffff0000 if half == "lo" else 0xffff)
    return keep | ((value & 0xffff) << (0 if half == "lo" else 16))


def buffer_address(vs, soffset, voffset, inst, index, flaws):
    base, stride, records, select = vs[0] | (vs[1] & 0xffff) << 32, (vs[1] >> 16) & 0x3fff, vs[2], (vs[3] >> 28) & 3
    inst, soffset, index = (0 if "noinst" in flaws else inst), (0 if "nosoffset" in flaws else soffset), (0 if "noindex" in flaws else index)
    offset = voffset + inst
    in_range = (index < records and offset < stride, index < records, records != 0, offset < records)[select]
    if offset >= 1 << 32 or vs[1] >> 31 or (vs[3] >> 23) & 1 or not (in_range or "nocheck" in flaws):
        return None
    return effective([base, soffset, 0 if "nostride" in flaws else stride * index, offset], flaws)


def buffer_model(op, kind):
    def model(w, v, flaws=()):
        # w0 old value, w1 voffset (or index), w2 soffset; the instruction offset is 3.
        address = buffer_address(v[0], w[2], w[1] if kind == "offen" else 0, 3, w[1] if kind == "idxen" else 0, flaws)
        return extend(op, address, w[0], flaws)
    return model


def global_model(op, kind):
    def model(w, v, flaws=()):
        # pair: base = w0 | w1 << 32 in v[18:19]; saddr: base in s[44:45] plus the 32-bit w2 in a VGPR; w3 the old value.
        base, voffset, imm = w[0] | w[1] << 32, (w[2] if kind == "saddr" else 0), -5
        imm = 0 if "no_imm" in flaws else imm & M32 if "imm_zext" in flaws else imm
        voffset = 0 if "no_voffset" in flaws else voffset
        return extend(op, effective([base, voffset, imm % (1 << 64)], flaws), w[3], flaws)
    return model


def flaws_of(op, kind):
    # Extending a 16-bit load to 16 bits changes nothing, so flip_ext only applies to the other forms.
    flaws = ["width_swap", "shift1", "align_down"] + ([] if OPS[op][0] == 2 and OPS[op][2] else ["flip_ext"])
    if OPS[op][2]:
        flaws += ["no_preserve", "wrong_half"]
    if kind in ("offen", "idxen"):
        flaws += ["noinst", "nosoffset", "nocheck"] + (["nostride", "noindex"] if kind == "idxen" else [])
    else:
        flaws += ["no_imm", "imm_zext", "nocarry"] + (["no_voffset"] if kind == "saddr" else [])
    return flaws


RAW = vsharp(BASE0 + 0x40, 0, 0x30, 3)
STRUCTURED = vsharp(BASE1, 0x20, 4, 0)
# (old, voffset or index, soffset, unused); the loaded address is base + soffset + voffset + 3.
BUFFER_SETS = {
    "offen": [((OLD[0], v, s, 0), (RAW, ZERO, ZERO)) for v, s in
              ((0x00, 0x00), (0x01, 0x00), (0x02, 0x04), (0x07, 0x00), (0x0a, 0x01), (0x0d, 0x03), (0x2a, 0x00), (0x30, 0x00))]
    + [((OLD[1], 0x0a, 0x01, 0), (RAW, ZERO, ZERO))],
    "idxen": [((OLD[0], i, s, 0), (STRUCTURED, ZERO, ZERO)) for i, s in ((0, 0), (1, 0), (3, 2), (2, 5), (4, 0))]
    + [((OLD[1], 1, 1, 0), (STRUCTURED, ZERO, ZERO))],
}
# Targets are the loaded address; the base is the target plus 5 (the immediate is -5) with the whole 64-bit value split into
# words, and the 4 GiB line is at BASE0 + 0x100. The target at BASE0 + 0x300 is a lookup miss.
PAIR_TARGETS = (BASE0 + 0x41, BASE0 + 0x42, BASE0 + 0x4b, BASE0 + 0xfe, BASE0 + 0xff, BASE0 + 0x103, BASE1 + 0x21, BASE0 + 0x300)
SADDR_SPLITS = ((BASE0 + 0x41, 0), (BASE0 + 0x20, 0x21), (BASE0 + 0xe0, 0x1b), (BASE0 + 0x4b + 8, 0x1e), (BASE0 + 0xfc, 0x7), (BASE1, 0x25),
                (BASE0 + 0x2e0, 0x1b))


def pair_sets():
    out = []
    for n, target in enumerate(PAIR_TARGETS):
        base = target + 5
        out.append(((base & M32, base >> 32, 0, OLD[n % 2]), (ZERO, ZERO, ZERO)))
    return out


def saddr_sets():
    # Targets BASE0 + 0x41 - 5 ... : base + voffset - 5 with base lo words near the 4 GiB wrap so the 32-bit add carries.
    return [(((b := base) & M32, b >> 32, voffset, OLD[n % 2]), (ZERO, ZERO, ZERO)) for n, (base, voffset) in enumerate(SADDR_SPLITS)]


def buffer_body(op, kind):
    return load_program(move(18, "s45"), move(24, "s44"),
                        f"buffer_load_{op} v24, v18, s[52:55], s46 {kind} offset:3",
                        "s_waitcnt vmcnt(0)", *readback((24, 0), (24, 1), (24, 2), (24, 3)))


def global_body(op, kind):
    if kind == "pair":
        lines = [move(18, "s44"), move(19, "s45"), move(24, "s47"), f"global_load_{op} v24, v[18:19], off offset:-5"]
    else:
        lines = [move(20, "s46"), move(24, "s47"), f"global_load_{op} v24, v20, s[44:45] offset:-5 glc"]
    return global_program(*lines, "s_waitcnt vmcnt(0)", *readback((24, 0), (24, 1), (24, 2), (24, 3)))


def rows():
    for op in OPS:
        for kind in ("offen", "idxen"):
            if kind == "offen" or op in ("ubyte", "sbyte_d16", "short_d16_hi"):
                yield (f"buffer_load_{op}_{kind}", buffer_body(op, kind), BUFFER_SETS[kind], buffer_model(op, kind), flaws_of(op, kind))
        for kind, sets in (("pair", pair_sets()), ("saddr", saddr_sets())):
            yield (f"global_load_{op}_{kind}", global_body(op, kind), sets, global_model(op, kind), flaws_of(op, kind))


ROWS = list(rows())


def channels(word):
    return [float(byte(word, n)) for n in range(4)]


def run_rows(directory, compiler, renderer, backend, table, stem):
    case = directory / f"{stem}.case"
    for index, (name, body, sets, model, flaws) in enumerate(table):
        source, shader = directory / f"{stem}{index}.hlsl", directory / f"{stem}{index}.cso"
        source.write_text(translate_loads(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = dict.fromkeys(flaws, False)
        for inputs, sharps in sets:
            words = [0] * 64
            words[3:7] = inputs
            words[8:20] = [word for vs in sharps for word in vs]
            expected = channels_of(model(inputs, sharps))
            for value in expected:
                assert half_rtz(value) == value, value
            case.write_bytes(titlemem.case_file(words, expected, LOAD_MEMORY))
            subprocess.run(draw, check=True)
            for flaw in flaws:
                wrong = channels_of(model(inputs, sharps, {flaw}))
                if wrong == expected or separated[flaw]:
                    continue
                separated[flaw] = True
                case.write_bytes(titlemem.case_file(words, wrong, LOAD_MEMORY))
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong load result escaped detection in {name}, flaw {flaw}")
        assert all(separated.values()), (name, separated)


def channels_of(value):
    return channels(value) if isinstance(value, int) else [float(v) for v in value]


def check_load_sub_draws(directory, compiler, renderer, backend):
    run_rows(directory, compiler, renderer, backend, ROWS, "load_sub")


def check_model_separates():
    """The wrong references must differ from the right one without a GPU, so a table edit cannot make a flaw vacuous."""
    for name, _body, sets, model, flaws in ROWS:
        for flaw in flaws:
            assert any(channels_of(model(i, s, {flaw})) != channels_of(model(i, s)) for i, s in sets), (name, flaw)


def check_load_sub_controls() -> None:
    check_model_separates()
    ready = [move(18, "s45"), move(19, "s46"), move(24, "s44"), "s_load_dwordx4 s[52:55], s[20:21], 0x80", "s_waitcnt lgkmcnt(0)"]

    def case(*lines):
        return with_constants([*ready, *lines])

    wait = "s_waitcnt vmcnt(0)"
    # Accepted forms emit the extension and the half merge in the word domain.
    source = translate_loads(case("buffer_load_sbyte v25, v18, s[52:55], 0 offen", wait))
    assert "asuint(asint(" in source and "<< 24u) >> 24u" in source and "buffer_load_sub(" in source, source
    source = translate_loads(case("buffer_load_short_d16_hi v24, v18, s[52:55], 0 offen", wait))
    assert "& 0xffffu) | ((" in source and "<< 16" in source, source
    source = translate_loads(case("global_load_ubyte_d16 v24, v[18:19], off", wait))
    assert "global_load_sub(" in source and "& 0xffff0000u" in source, source
    # d16 loads read the old register: it must be set and settled, and a pending load of it is a hazard.
    must_reject(translate_loads, case("buffer_load_ubyte_d16 v30, v18, s[52:55], 0 offen", wait))
    must_reject(translate_loads, case("buffer_load_ubyte v24, v18, s[52:55], 0 offen", "buffer_load_ubyte_d16 v24, v18, s[52:55], 0 offen", wait))
    must_reject(translate_loads, case("global_load_short_d16_hi v24, v[18:19], off", "global_load_ubyte_d16 v24, v[18:19], off", wait))
    # A result used before vmcnt(0), a second load over it, and a pending load's register as an address.
    must_reject(translate_loads, case("buffer_load_ubyte v25, v18, s[52:55], 0 offen", "v_or_b32_e64 v26, 0, v25"))
    must_reject(translate_loads, case("buffer_load_ubyte v25, v18, s[52:55], 0 offen", "buffer_load_ubyte v25, v18, s[52:55], 0 offen", wait))
    must_reject(translate_loads, case("global_load_sbyte v25, v[18:19], off", "global_load_sbyte v26, v[25:26], off", wait))
    for bad in ("buffer_load_ubyte v[24:25], v18, s[52:55], 0 offen", "buffer_load_ubyte v24, v18, s[52:55], 0 offen tfe",
                "buffer_load_ubyte v24, v18, s[52:55], 0 offen lds", "buffer_load_ushort v24, v18, s[52:55], 0 offen offset:4096",
                "buffer_load_sshort v24, v18, s[52:55], 0", "buffer_load_sbyte v24, v18, s[52:55], 0 offen idxen",
                "buffer_load_sbyte_d16_hi v24, v[18:19], s[52:55], 0 offen", "buffer_load_short_d16 v24, v18, s[53:56], 0 offen",
                "buffer_load_ubyte v24, v18, s[28:31], 0 offen", "buffer_load_ubyte v24, v18, s[52:55], s70 offen",
                "buffer_load_ubyte v24, v18, s[52:55], 1 offen",
                "buffer_load_ubyte_d16 v[24:25], v18, s[52:55], 0 offen",
                "global_load_ubyte v[24:25], v[18:19], off", "global_load_ubyte v24, v18, off", "global_load_sshort v24, v[18:19], off tfe",
                "global_load_ubyte v24, v[18:19], off offset:2048", "global_load_ubyte v24, v[18:19], off offset:-2049",
                "global_load_short_d16 v24, v[18:19], s[44:45]", "global_load_sbyte_d16_hi v24, v20, s44",
                # Flat addresses may be LDS or scratch; scratch stays out. (Stores are lowered by forms/stores.py and
                # checked by the stores family; this glc-less atomic spells a returned register and is malformed.)
                "flat_load_ubyte v24, v[18:19]", "flat_load_sshort v24, v[18:19]", "flat_load_short_d16_hi v24, v[18:19]",
                "scratch_load_ubyte v24, v18, off", "global_atomic_add v24, v[18:19], v25, off"):
        must_reject(translate_loads, case(bad))


def controls(directory):
    check_load_sub_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate_loads) for _name, body, *_ in ROWS]


draw = check_load_sub_draws
