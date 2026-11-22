"""Quad lanes: the DPP16 (quad_perm) and DPP8 controls that stay inside one 2x2 quad, and the HLSL quad reads that
perform them (docs/design/module-layout.md). Shared by the DPP forms (forms/dpp.py).

A DPP read is a cross-lane read of a 32-bit register word. It is emitted on the unsigned word, so a NaN payload, a
denormal or any other bit pattern crosses lanes unchanged; a float, a binary16 pair or an integer is only given its
type after the read. Only controls that stay inside a quad, with every row and bank enabled, are accepted: that is
what QuadReadAcrossX, QuadReadAcrossY, QuadReadAcrossDiagonal and QuadReadLaneAt can express. Anything else (a row
shift, a row mirror, a wave shift, a partial row or bank mask, a DPP8 select that leaves its quad) is refused."""
import re

# Quad lane numbers are those of HLSL (SM 6.0) and of the hardware: 0 top-left, 1 top-right, 2 bottom-left,
# 3 bottom-right, so lane l reads lane l ^ 1 across X, l ^ 2 across Y and l ^ 3 across the diagonal.
QUAD_LANE = "((uint(frag_position.x) & 1u) | ((uint(frag_position.y) & 1u) << 1))"


def dpp_control(modifiers):
    """Validate the modifier words that follow the operands of a DPP instruction. Returns (perm, dpp8): perm gives,
    for each lane of a quad, the quad lane it reads, and dpp8 tells the DPP8 encoding (which has no source
    modifiers). DPP16 must spell out row_mask:0xf and bank_mask:0xf, as the disassembler prints them; an omitted
    mask or any other value is refused."""
    if not modifiers:
        raise ValueError("Missing DPP control modifiers")
    control, rest = modifiers[0], modifiers[1:]
    if m := re.fullmatch(r"dpp8:\[([0-7](?:,[0-7]){7})\]", control):
        select = [int(n) for n in m.group(1).split(",")]
        # Both quads of the group of eight must read inside their own quad, with the same pattern.
        if any(s > 3 for s in select[:4]) or select[4:] != [s + 4 for s in select[:4]]:
            raise ValueError(f"DPP8 select leaves its quad: {control}")
        if len(rest) > 1 or any(not re.fullmatch(r"fi:[01]", word) for word in rest):
            raise ValueError(f"Unsupported DPP8 modifier {' '.join(rest)}")
        return tuple(select[:4]), True
    if m := re.fullmatch(r"quad_perm:\[([0-3]),([0-3]),([0-3]),([0-3])\]", control):
        seen = set()
        for word in rest:
            key = word.split(":", 1)[0]
            if key in seen:
                raise ValueError(f"Duplicate DPP16 modifier {word}")
            if word not in ("row_mask:0xf", "bank_mask:0xf") and not re.fullmatch(r"(?:bound_ctrl|fi):[01]", word):
                raise ValueError(f"Unsupported DPP16 modifier {word} (only quad-local reads with all rows and banks)")
            seen.add(key)
        if not {"row_mask", "bank_mask"} <= seen:
            raise ValueError("DPP16 needs row_mask:0xf and bank_mask:0xf")
        return tuple(int(n) for n in m.groups()), False
    raise ValueError(f"Unsupported DPP control {control}")


def quad_read(st, i, word, perm):
    """The unsigned word each lane reads under the quad permutation `perm`, as an HLSL expression. Lines that the
    general permutation needs are appended to st.lines under names that carry the instruction index i."""
    if perm == (0, 1, 2, 3):
        return word
    for across, read in (((1, 0, 3, 2), "QuadReadAcrossX"), ((2, 3, 0, 1), "QuadReadAcrossY"),
                         ((3, 2, 1, 0), "QuadReadAcrossDiagonal")):
        if perm == across:
            return f"{read}({word})"
    if len(set(perm)) == 1:
        return f"QuadReadLaneAt({word}, {perm[0]})"
    # An arbitrary permutation reads each wanted lane for the whole quad and picks by this lane's own number, which
    # the pixel position gives exactly (the lane number within a quad is not WaveGetLaneIndex() & 3 in general).
    st.quad_position = True
    st.lines.append(f"    uint dpp{i}_in = {word};")
    reads = {lane: f"dpp{i}_l{lane}" for lane in sorted(set(perm))}
    for lane, name in reads.items():
        st.lines.append(f"    uint {name} = QuadReadLaneAt(dpp{i}_in, {lane});")
    st.lines.append(f"    uint dpp{i}_q = {QUAD_LANE};")
    a, b, c, d = (reads[p] for p in perm)
    st.lines.append(f"    uint dpp{i}_s = dpp{i}_q == 0u ? {a} : (dpp{i}_q == 1u ? {b} : (dpp{i}_q == 2u ? {c} : {d}));")
    return f"dpp{i}_s"
