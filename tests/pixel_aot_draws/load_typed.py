"""Draw family `load_typed`: pixel_aot_check.py draw --family load_typed."""
import pixel_aot

from .common import move, must_reject, with_constants
from .load import BASE0, BASE1, ZERO, load_program, readback, translate_loads
from .load_sub import buffer_address, mem_byte, run_rows


# Typed loads, buffer_load_format_{x,xy,xyz,xyzw} (format from V# word 3 bits 12 to 18) and tbuffer_load_format_* (format
# from the instruction), only where the conversion is exact: the 32_UINT (20) and 32_SINT (21) formats, whose single component
# is the raw dword. The V# DST_SEL fields (bits 0 to 11, three each: 0 = 0, 1 = 1, 4 to 7 = X, Y, Z, W) then place the dword
# (X), the zero fill of Y and Z and the one fill of W. Each program reads four bytes of the loaded registers. Out-of-range
# loads appear only in programs whose written channels are all zero in that case, so the alpha value of an out-of-range
# typed load, which no source here pins down, is never compared. Other formats read zero in the lowering and never
# appear in a draw, because hardware would not read zero; tbuffer_load refuses them at translation time.
UINT, SINT = 20, 21
IDENTITY = 4 | 5 << 3 | 6 << 6 | 7 << 9


def vs_typed(base, stride, records, select, fmt, sel=IDENTITY):
    return (base & 0xffffffff, base >> 32 | stride << 16, records, select << 28 | fmt << 12 | sel)


def sel_of(x, y, z, w):
    return x | y << 3 | z << 6 | w << 9


def typed_model(count, fmt_from_instruction=None, kind="offen"):
    def model(w, v, flaws=()):
        # w1 voffset (or index), w2 soffset; the instruction offset is 8.
        vs = v[0]
        fmt = (vs[3] >> 12) & 0x7f if fmt_from_instruction is None else fmt_from_instruction
        address = buffer_address(vs, w[2], w[1] if kind == "offen" else 0, 8, w[1] if kind == "idxen" else 0, flaws)
        if address is None or fmt not in (UINT, SINT):
            return [0] * count
        element = sum(mem_byte((address + k) % (1 << 64)) << (8 * k) for k in range(4))
        raw = [element, 0, 0, 0 if "w_zero" in flaws else 1]
        sel = [(vs[3] >> (3 * c)) & 7 for c in range(4)]
        out = [raw[c] if "no_swizzle" in flaws else 0 if s == 0 else 1 if s == 1 else raw[s - 4] for c, s in enumerate(sel)]
        return out[:count]
    return model


def picked(model, picks):
    return lambda w, v, flaws=(): [float((model(w, v, flaws)[r] >> (8 * n)) & 0xff) for r, n in picks]


# The wrong references a row is checked against: those among these that differ from the right answer in some set, which
# the controls require to include nocheck and every addressing term for the x rows, and no_swizzle or w_zero where the
# row's V# and width make them observable.
ALL_FLAWS = ["nocheck", "noinst", "nosoffset", "nostride", "noindex", "no_swizzle", "w_zero"]


def raw_sets(vs, oob=True, offsets=((0, 0), (4, 0), (0x14, 8), (0x24, 4))):
    sets = [((0, v, s, 0), (vs, ZERO, ZERO)) for v, s in offsets]
    return sets + ([((0, 0x30, 0, 0), (vs, ZERO, ZERO))] if oob else [])


# The raw window is 0x30 bytes at BASE0 + 0x40; with the instruction offset 8, voffset 0x24 reads the last dword.
RAW_ID = lambda fmt: vs_typed(BASE0 + 0x40, 0, 0x30, 3, fmt)
STRUCT_ID = lambda fmt: vs_typed(BASE1, 0x20, 4, 0, fmt)
Y_X = sel_of(5, 4, 0, 1)          # x = Y (zero), y = X (the dword)
W_X_ZERO = sel_of(7, 4, 0, 1)     # x = W (one), y = X, z = 0
W_Z_X_ONE = sel_of(0, 7, 4, 1)    # x = 0, y = W (one), z = X, w = 1


def table():
    rows = []

    def add(name, body, sets, model, picks):
        flaws = [f for f in ALL_FLAWS if any(model(i, v, {f}) != model(i, v) for i, v in sets)]
        rows.append((name, body, sets, picked(model, picks), flaws))

    for instruction, kind_name in (("buffer_load_format", "mubuf"), ("tbuffer_load_format", "mtbuf")):
        def op(comps, regs, fmt_suffix, addressing):
            infix = f" format:[BUF_FMT_32_{fmt_suffix}]" if kind_name == "mtbuf" else ""
            return f"{instruction}_{comps} {regs}, v18, s[52:55], s46{infix} {addressing} offset:8"

        for fmt, fmt_name in ((UINT, "UINT"), (SINT, "SINT")):
            inst_fmt = fmt if kind_name == "mtbuf" else None
            # x, identity V#: all four bytes of the dword, plus an out-of-range window that reads zero.
            add(f"{instruction}_x_{fmt_name}", load_program(move(18, "s45"), op("x", "v24", fmt_name, "offen"), "s_waitcnt vmcnt(0)",
                                                          *readback((24, 0), (24, 1), (24, 2), (24, 3))),
                raw_sets(RAW_ID(fmt)), typed_model(1, inst_fmt), [(0, 0), (0, 1), (0, 2), (0, 3)])
            # xy with the dword in Y and zero in X: the second register carries the data.
            add(f"{instruction}_xy_{fmt_name}", load_program(move(18, "s45"), op("xy", "v[24:25]", fmt_name, "offen"), "s_waitcnt vmcnt(0)",
                                                           *readback((24, 0), (25, 0), (25, 1), (25, 3))),
                raw_sets(vs_typed(BASE0 + 0x40, 0, 0x30, 3, fmt, Y_X)), typed_model(2, inst_fmt), [(0, 0), (1, 0), (1, 1), (1, 3)])
            # xyz with W, X, 0 placed: one, the dword, zero (no out-of-range set, see above).
            add(f"{instruction}_xyz_{fmt_name}", load_program(move(18, "s45"), op("xyz", "v[24:26]", fmt_name, "offen"), "s_waitcnt vmcnt(0)",
                                                            *readback((24, 0), (25, 0), (25, 3), (26, 0))),
                raw_sets(vs_typed(BASE0 + 0x40, 0, 0x30, 3, fmt, W_X_ZERO), oob=False), typed_model(3, inst_fmt),
                [(0, 0), (1, 0), (1, 3), (2, 0)])
            # xyzw, identity: dword, zero, zero, one.
            add(f"{instruction}_xyzw_{fmt_name}", load_program(move(18, "s45"), op("xyzw", "v[24:27]", fmt_name, "offen"), "s_waitcnt vmcnt(0)",
                                                             *readback((24, 0), (24, 3), (25, 0), (27, 0))),
                raw_sets(RAW_ID(fmt), oob=False), typed_model(4, inst_fmt), [(0, 0), (0, 3), (1, 0), (3, 0)])
            # xyzw, permuted: zero, one, the dword, one.
            add(f"{instruction}_xyzw_perm_{fmt_name}", load_program(move(18, "s45"), op("xyzw", "v[24:27]", fmt_name, "offen"), "s_waitcnt vmcnt(0)",
                                                                  *readback((25, 0), (26, 0), (26, 2), (27, 0))),
                raw_sets(vs_typed(BASE0 + 0x40, 0, 0x30, 3, fmt, W_Z_X_ONE), oob=False), typed_model(4, inst_fmt),
                [(1, 0), (2, 0), (2, 2), (3, 0)])
        # idxen on a structured V#: the index scales by the stride, with the instruction offset and soffset on top. The soffset
            # keeps the address dword aligned: the lowering reads an unaligned typed element as zero (an unaligned set was dropped).
        add(f"{instruction}_x_idxen", load_program(move(18, "s45"), op("x", "v24", "UINT", "idxen"), "s_waitcnt vmcnt(0)",
                                                 *readback((24, 0), (24, 1), (24, 2), (24, 3))),
            [((0, i, s, 0), (STRUCT_ID(UINT), ZERO, ZERO)) for i, s in ((0, 0), (1, 0), (3, 4), (4, 0))],
            typed_model(1, UINT if kind_name == "mtbuf" else None, "idxen"), [(0, 0), (0, 1), (0, 2), (0, 3)])
    return rows


ROWS = table()


def check_load_typed_draws(directory, compiler, renderer, backend):
    run_rows(directory, compiler, renderer, backend, ROWS, "load_typed")


def check_load_typed_controls() -> None:
    for name, _body, _sets, _model, flaws in ROWS:
        wanted = {"noinst", "nosoffset"} | ({"nostride", "noindex"} if name.endswith("idxen") else set())
        wanted |= {"nocheck"} if "_x_" in name or "_xy_" in name or name.endswith("idxen") else set()
        wanted |= {"no_swizzle"} if "_xy_" in name or "perm" in name or "_xyz_" in name else set()
        wanted |= {"w_zero"} if "xyzw" in name else set()
        assert wanted <= set(flaws), (name, wanted - set(flaws))
    ready = [move(18, "s45"), "s_load_dwordx4 s[52:55], s[20:21], 0x80", "s_waitcnt lgkmcnt(0)"]

    def case(*lines):
        return with_constants([*ready, *lines])

    wait = "s_waitcnt vmcnt(0)"
    source = translate_loads(case("buffer_load_format_xyzw v[24:27], v18, s[52:55], 0 offen", wait))
    assert "buffer_load_format(" in source and ">> 12u) & 0x7fu" in source, source
    source = translate_loads(case("tbuffer_load_format_xy v[24:25], v18, s[52:55], 0 format:[BUF_FMT_32_SINT] offen", wait))
    assert ", 21u);" in source, source
    source = translate_loads(case("tbuffer_load_format_x v24, v18, s[52:55], 0 format:20 offen glc slc dlc", wait))
    assert ", 20u);" in source, source
    # Refused neighbours: the d16 forms (half conversion), every other tbuffer format, a missing or repeated format field,
    # tfe, wrong register widths, the pending-load hazards, stores and unsupported modifiers.
    must_reject(translate_loads, case("buffer_load_format_d16_x v24, v18, s[52:55], 0 offen", wait))
    for bad in ("buffer_load_format_d16_xy v24, v18, s[52:55], 0 offen", "buffer_load_format_d16_xyz v[24:25], v18, s[52:55], 0 offen",
                "buffer_load_format_d16_xyzw v[24:25], v18, s[52:55], 0 offen",
                "tbuffer_load_format_d16_x v24, v18, s[52:55], 0 format:[BUF_FMT_32_UINT] offen",
                "tbuffer_load_format_d16_xy v24, v18, s[52:55], 0 format:[BUF_FMT_32_UINT] offen",
                "tbuffer_load_format_x v24, v18, s[52:55], 0 format:[BUF_FMT_32_FLOAT] offen",
                "tbuffer_load_format_x v24, v18, s[52:55], 0 format:[BUF_FMT_8_UNORM] offen",
                "tbuffer_load_format_xy v[24:25], v18, s[52:55], 0 format:[BUF_FMT_16_16_FLOAT] offen",
                "tbuffer_load_format_xyzw v[24:27], v18, s[52:55], 0 format:[BUF_FMT_32_32_32_32_UINT] offen",
                "tbuffer_load_format_x v24, v18, s[52:55], 0 format:22 offen", "tbuffer_load_format_x v24, v18, s[52:55], 0 format:1 offen",
                "tbuffer_load_format_x v24, v18, s[52:55], 0 offen",
                "tbuffer_load_format_x v24, v18, s[52:55], 0 format:[BUF_FMT_32_UINT] format:[BUF_FMT_32_UINT] offen",
                "tbuffer_load_format_x v24, v18, s[52:55], 0 format:[BUF_FMT_32_UINT] offen tfe",
                "tbuffer_load_format_x v[24:25], v18, s[52:55], 0 format:[BUF_FMT_32_UINT] offen",
                "tbuffer_load_format_xyz v[24:25], v18, s[52:55], 0 format:[BUF_FMT_32_UINT] offen",
                "tbuffer_load_format_x v24, v18, s[52:55], 0 format:[BUF_FMT_32_UINT]",
                "tbuffer_load_format_x v24, v18, s[52:55], 0 format:[BUF_FMT_32_UINT] offen offset:4096",
                "tbuffer_load_format_x v24, v18, s[28:31], 0 format:[BUF_FMT_32_UINT] offen",
                "tbuffer_store_format_x v24, v18, s[52:55], 0 format:[BUF_FMT_32_UINT] offen",
                "buffer_load_format_x v[24:25], v18, s[52:55], 0 offen", "buffer_load_format_xyzw v[24:26], v18, s[52:55], 0 offen",
                "buffer_load_format_x v24, v18, s[52:55], 0 offen tfe", "buffer_load_format_x v24, v18, s[52:55], 0 offen lds",
                "buffer_load_format_x v24, v18, s[52:55], 0", "buffer_load_format_x v24, v18, s[53:56], 0 offen",
                "buffer_load_format_x v24, v18, s[28:31], 0 offen", "buffer_store_format_x v24, v18, s[52:55], 0 offen"):
        must_reject(translate_loads, case(bad))
    for hazard in (("buffer_load_format_x v24, v18, s[52:55], 0 offen", "v_or_b32_e64 v25, 0, v24"),
                   ("buffer_load_format_xy v[24:25], v18, s[52:55], 0 offen", "buffer_load_format_x v25, v18, s[52:55], 0 offen", wait),
                   ("tbuffer_load_format_x v24, v18, s[52:55], 0 format:[BUF_FMT_32_UINT] offen", "v_or_b32_e64 v25, 0, v24")):
        must_reject(translate_loads, case(*hazard))


def controls(directory):
    check_load_typed_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate_loads) for _name, body, *_ in ROWS]


draw = check_load_typed_draws
