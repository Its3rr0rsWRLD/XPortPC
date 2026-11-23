"""Color export and the v_cvt_pkrtz_f16_f32 packing that feeds it."""
import re

from ..control_flow import implies
from ..dispatch import form
from ..hlsl import SALU_HELPERS
from ..registers import PackedPair, fp_operand, tracked_word, vector_u32


def packed_under(st, i, dst):
    """CF-2d: a pack while the lane may be inactive is not masked (lowering.masked_writes skips it); the export checks
    the bit it ran under (st.pack_ex)."""
    if st.ex != "true":
        st.pack_ex.setdefault(dst, {})[i] = st.ex


def discard_dead_lane(st):
    """CF-2d: the valid-mask bit of `exp ... done vm` kills a lane that is off in EXEC: `if (!ex) discard;` when the
    lane may be inactive. A lane that exports must hold every packed pair it exports as written."""
    if st.ex == "true":
        return
    st.lines.append("    discard;" if st.ex == "false" else f"    if (!{st.ex}) discard;")


# The pack as a word, for any reader but the compressed export (ported from R0Y00/Xbox2Windows#528 by Vonsek): each
# half is converted to binary16 rounding toward zero in integer arithmetic, so desktop conversion and denormal handling
# cannot change it. A finite value past the range gives the largest finite half, as LLVM folds llvm.amdgcn.cvt.pkrtz
# with rmTowardZero; a binary16 subnormal result is kept; a NaN keeps its sign and top payload bits, quieted.
SALU_HELPERS["pack16_rtz"] = (
    "// v_cvt_pkrtz_f16_f32: binary32 to binary16 rounding toward zero.\n"
    "uint pack16_rtz(float value) {\n"
    "    uint bits = asuint(value);\n"
    "    uint sign = (bits >> 16) & 0x8000u;\n"
    "    uint abs_bits = bits & 0x7fffffffu;\n"
    "    if (abs_bits > 0x7f800000u) return sign | 0x7e00u | ((abs_bits >> 13) & 0x3ffu);\n"
    "    if (abs_bits == 0x7f800000u) return sign | 0x7c00u;\n"
    "    if (abs_bits >= 0x47800000u) return sign | 0x7bffu;\n"
    "    if (abs_bits >= 0x38800000u) return sign | ((abs_bits - 0x38000000u) >> 13);\n"
    "    if (abs_bits < 0x33800000u) return sign;\n"
    "    return sign | ((0x00800000u | (abs_bits & 0x007fffffu)) >> (126u - (abs_bits >> 23)));\n"
    "}")


def pair_of(st, dst, halves):
    pair = PackedPair(halves)
    pair.helpers = st.helpers
    st.vector[dst] = pair


@form(r"v_cvt_pkrtz_f16_f32_e32 (v\d+), (v\d+), (v\d+)")
def pack_e32(st, i, m):
    dst, lo, hi = m.groups()
    pair = []
    for n, register in enumerate((lo, hi)):
        value = st.vector[register]
        if isinstance(value, tuple) and tracked_word(value) is not None:
            # A raw word is exported as the float with those bits; the export is where it becomes a float.
            st.lines.append(f"    precise float alu{i}_{n} = asfloat({value[1]});")
            value = f"alu{i}_{n}"
        pair.append(value)
    # Only the sources and the destination must be settled: another load may still be in flight (R0Y00/Xbox2Windows#176).
    if (lo in st.sample_dest or hi in st.sample_dest or dst in st.sample_dest
            or not all(isinstance(v, str) and v.startswith(("sample", "alu")) for v in pair)):
        raise ValueError("Unsupported pack operand")
    pair_of(st, dst, pair)
    packed_under(st, i, dst)


@form(r"v_cvt_pkrtz_f16_f32_e32 (v\d+), ([sv]\d+|0x[0-9a-f]{1,8}|-?\d+(?:\.\d+)?), (v\d+)", when=lambda st, m: not m[2].startswith("v"))
def pack_e32_scalar_source(st, i, m):
    # VOP2 takes S0 from an SGPR, an inline constant or a literal and S1 from a VGPR; same rules as the e64 form.
    pack_tokens(st, i, m[1], [m[2], m[3]], None)


@form(r"v_cvt_pkrtz_f16_f32_e64 (v\d+), ([^, ]+), ([^, ]+?)( clamp)?")
def pack_e64(st, i, m):
    # The VOP3 form of the pack above, with the same operand rules: numeric sources only, entry mask, no pending
    # sample. A source may also be an SGPR holding a numeric word, an inline constant or a literal, and carries
    # neg and abs, which act on the binary32 value before the conversion (the packed halves are not modified).
    # clamp is refused: the only evidence of its effect is LLVM issue 60591, which says the hardware ignores
    # clamp and omod on this instruction on GFX10.3, a single report not measured on gfx1013 and not in the
    # ISA text. omod and op_sel do not match this grammar. https://github.com/llvm/llvm-project/issues/60591
    dst, *tokens, clamp = m.groups()
    pack_tokens(st, i, dst, tokens, clamp)


def pack_tokens(st, i, dst, tokens, clamp):
    if clamp:
        raise ValueError("clamp on v_cvt_pkrtz_f16_f32_e64 is refused: its hardware behaviour is unverified "
                         "(LLVM issue 60591 reports it is ignored on GFX10.3)")
    # Only the sources and the destination must be settled, as for the e32 form: an unrelated load may still be in
    # flight (fp_operand refuses a source register that is a load destination).
    if dst in st.sample_dest:
        raise ValueError("Unsupported pack operand")
    pair = []
    for n, token in enumerate(tokens):
        for register in re.findall(r"[vs]\d+", token):
            if tracked_word((st.vector if register.startswith("v") else st.scalar).get(register)) is None:
                raise ValueError(f"Unsupported pack operand {register}")
        st.lines.append(f"    precise float alu{i}_{n} = {fp_operand(token, st.scalar, st.vector, st.pending, st.sample_pending)};")
        pair.append(f"alu{i}_{n}")
    pair_of(st, dst, pair)
    packed_under(st, i, dst)


# Pixel exports. A pixel program exports colour to mrt0..mrt7, depth to mrtz, or nothing (`exp null`, a program without
# colour or depth outputs); exports go out in program order and the last one carries done and vm, which mark the end of
# the pixel's exports and the valid-mask bit. Each export becomes one output of main: SV_Target<n> for mrt<n>, SV_Depth
# for mrtz, none for null. An export that is not the last is held in a local (and in st.exports, which the control-flow
# walk keeps per path) until the done export returns them all; nothing but further exports may come between them.
#
# en (the four sources, `off` when disabled) is the component mask, R = 1 .. A = 8. An HLSL output cannot leave a
# component unwritten, so the mask becomes the render target's write mask, which the pipeline must apply: the lowering
# names every target's mask in a comment line (WRITE_MASKS) above the output struct, a disabled component below the
# last enabled one is written as 0 and masked off, and the output is as wide as the last enabled component. The
# renderer applies the masks to targets cleared to a sentinel, so a component the export leaves off must keep it.
# Uncompressed exports write each enabled source word as a binary32 value, and any non-empty mask is accepted.
# Compressed (compr) exports hold binary16 pairs: the low and high halves of the first source word are R and G, those of
# the second B and A, and only whole pairs are accepted (RG `vA, vA, off, off`, BA `off, off, vB, vB`, RGBA). LLVM 15
# prints other raw compressed masks with `off` in one half of a pair, but reassembles such text to another mask (a pair
# survives exactly when its first operand is enabled: raw 0x5 comes back as 0xf, 0x2 and 0xa as 0), so that text has no
# single meaning and is refused, as is an empty mask. (Ported from R0Y00/Xbox2Windows#398, #429 and #434 by
# abilliontokens: the write mask applied to a sentinel-cleared target, partial uncompressed masks, and the
# pair-first-operand rule for compressed masks.)
# mrtz is accepted with the depth component alone (R): stencil (G), the sample mask (B) and the alpha-to-coverage
# alpha (A) are refused, since SV_Depth carries none of them. The depth is the binary32 source value; the draws read it
# back bit-exactly from a D32_FLOAT target and keep it within [0, 1] (normal or zero), so viewport clamping and denormal
# handling of depth values outside that are not claimed. pos, param and prim are vertex-stage and primitive exports and
# are refused in a pixel program.
EXPORT = re.compile(r"exp (\w+),? (v\d+|off), (v\d+|off), (v\d+|off), (v\d+|off)( done)?( compr)?( vm)?")
TARGET_ORDER = [f"target{n}" for n in range(8)] + ["depth"]
WRITE_MASKS = "// Render target write masks, applied by the pipeline:"


def _pair_halves(st, register):
    """The R, G (or B, A) channels of one compressed source, as binary32 expressions of its two binary16 halves."""
    value = st.vector.get(register)
    if isinstance(value, tuple) and len(value) == 2 and value[0] != "uint":
        # A v_cvt_pkrtz_f16_f32 pair: the two floats, each exported as its binary16 value.
        if not all(isinstance(v, str) and v.startswith(("sample", "alu")) for v in value):
            raise ValueError("Unsupported export")
        return [f"export16({v})" for v in value]
    # Any other numeric word: its halves, widened exactly from their encodings.
    word = vector_u32(register, st.scalar, st.vector, st.pending, st.sample_pending)
    return [f"widen16({word})", f"widen16({word} >> 16)"]


def _width_type(width):
    return "float" if width == 1 else f"float{width}"


@form(EXPORT.pattern)
def export(st, i, m):
    target, *sources, done, compr, vm = m.groups()
    if st.stage != "pixel":
        raise ValueError("A color export belongs to the pixel stage")
    if re.fullmatch(r"pos\d+|param\d+|prim", target):
        raise ValueError(f"exp {target} is a vertex or primitive export; a pixel program exports to mrt0..mrt7, mrtz and null")
    if not re.fullmatch(r"mrt[0-7]|mrtz|null", target):
        raise ValueError(f"Unknown export target {target}")
    if st.exported:
        raise ValueError("Unsupported export")
    if bool(done) != bool(vm):
        raise ValueError("Only the last export carries done, and it carries vm with it")
    enabled = [source != "off" for source in sources]
    # CF-2d: an export may run while the lane may be inactive. Only exports come between the first export and the done
    # one (lowering.lower), so every export of the path runs under the same bit, and the done export's vm kills a lane
    # that is off: `if (!ex) discard;` before the return (finish). A packed pair it exports must have been packed under
    # a bit the export's implies.
    for source in set(sources) - {"off"}:
        if not all(implies(st.lines, st.ex, {bit}) for bit in st.pack_ex.get(source, {}).values()):
            raise ValueError("Export of a pair packed while the exporting lane may have been inactive")
    if st.integer_export:
        if st.ex != "true":
            raise ValueError("Unsupported export")
        # lower(integer_export=True): the shader returns uint4 of the four bit patterns instead of binary32 values, so the
        # render target cannot canonicalize a NaN or flush a denormal: the lossless readback of integer moves, bit
        # operations and bitcasts (R0Y00/Xbox2Windows#363 by abilliontokens). Four distinct registers into mrt0.
        values = [st.vector.get(v) for v in sources]
        if (target != "mrt0" or compr or not done or not all(enabled) or len(set(sources)) != 4 or st.exports
                or any(v in st.sample_dest for v in sources) or any(tracked_word(v) is None for v in values)):
            raise ValueError("Unsupported export")
        if st.layout is not None and st.layout != (("target0", 4, 0xf),):
            raise ValueError("Paths of the program export different targets")
        st.layout = (("target0", 4, 0xf),)
        st.lines.append(f"    return uint4({', '.join(tracked_word(v) for v in values)});")
        st.exported = True
        return
    if target == "null":
        if any(enabled) or compr or not done or st.exports:
            raise ValueError("exp null is accepted only as a program's only export, with no sources: done vm")
        finish(st, (), [])
        return
    key = "depth" if target == "mrtz" else f"target{target[3:]}"
    if any(output[0] == key for output in st.exports):
        raise ValueError(f"exp {target} appears twice")
    mask = sum(1 << c for c, on in enumerate(enabled) if on)
    if target == "mrtz":
        if compr or mask != 1:
            raise ValueError("exp mrtz is accepted with the depth component alone, uncompressed: stencil, sample mask "
                             "and alpha exports are refused")
        channels = [fp_operand(sources[0], st.scalar, st.vector, st.pending, st.sample_pending)]
    elif compr:
        pairs = []
        for first, second in (sources[0:2], sources[2:4]):
            if first != second:
                raise ValueError(f"A compressed export must enable whole binary16 pairs (RG, BA or RGBA): "
                                 f"{', '.join(sources)} does not")
            pairs.append(None if first == "off" else first)
        if pairs == [None, None]:
            raise ValueError("A compressed export must enable whole binary16 pairs (RG, BA or RGBA): none is enabled")
        channels = [half for word in pairs for half in (_pair_halves(st, word) if word else ["0.0f", "0.0f"])]
        if done and target == "mrt0" and not st.exports:
            st.compressed_mrt0 = True  # lowering.finish: an unsampled one that reads no input declares none
    else:
        if not mask:
            raise ValueError("An uncompressed export must enable at least one component")
        if target == "mrt0" and done and mask == 0xf and len(set(sources)) != 4:
            # The full four-register uncompressed mrt0 export keeps its earlier rule: four distinct registers.
            raise ValueError("Unsupported export")
        channels = [fp_operand(source, st.scalar, st.vector, st.pending, st.sample_pending) if source != "off"
                    else "0.0f" for source in sources]
    channels = channels[:mask.bit_length()]
    value = channels[0] if len(channels) == 1 else f"float{len(channels)}({', '.join(channels)})"
    if not done:
        st.lines.append(f"    {_width_type(len(channels))} exp{i} = {value};")
        st.exports = (*st.exports, (key, len(channels), mask, f"exp{i}"))
        return
    outputs = sorted((*st.exports, (key, len(channels), mask, value)), key=lambda output: TARGET_ORDER.index(output[0]))
    finish(st, tuple(output[:3] for output in outputs), outputs)


def finish(st, layout, outputs):
    """The done export: return every output of the path. Every path of a program must return the same outputs with the
    same masks, since they are the signature of main and the pipeline's write masks; a single float4 SV_Target0 with
    every component enabled keeps the signature the preamble declares."""
    if st.layout is not None and st.layout != layout:
        raise ValueError("Paths of the program export different targets")
    st.layout = layout
    discard_dead_lane(st)
    if layout == (("target0", 4, 0xf),):
        st.lines.append(f"    return {outputs[0][3]};")
    elif not layout:
        st.lines.append("    return;")
        st.signature = ("void", None)
    else:
        semantic = lambda name: "SV_Depth" if name == "depth" else f"SV_Target{name[6:]}"
        members = " ".join(f"{_width_type(width)} {name} : {semantic(name)};" for name, width, _ in layout)
        declaration = f"struct PixelOutput {{ {members} }};"
        masks = [f"{semantic(name)} 0x{mask:x}" for name, _, mask in layout if name != "depth"]
        if masks:
            declaration = f"{WRITE_MASKS} {', '.join(masks)}\n{declaration}"
        st.signature = ("PixelOutput", declaration)
        st.lines.append("    PixelOutput result;")
        st.lines.extend(f"    result.{name} = {value};" for name, _, _, value in outputs)
        st.lines.append("    return result;")
    st.exports = ()
    st.exported = True


def write_masks(source):
    """{render target index: write mask} named by the WRITE_MASKS line of a lowered program; a program returning the
    preamble's float4 SV_Target0 has {0: 0xf}, and one without colour outputs {}."""
    for line in source.splitlines():
        if line.startswith(WRITE_MASKS):
            return {int(name.removeprefix("SV_Target")): int(mask, 16)
                    for name, mask in (item.split() for item in line[len(WRITE_MASKS):].split(","))}
    return {0: 0xf} if ") : SV_Target0 {" in source else {}


# Anything else spelled as an export (another target or operand shape) is refused here, not left unclaimed.
@form(r"exp\b.*")
def unsupported_export(st, i, m):
    raise ValueError(f"Unsupported export: {m[0]}")
