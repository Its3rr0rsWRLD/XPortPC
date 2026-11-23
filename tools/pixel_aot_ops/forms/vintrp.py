"""VINTRP: attribute interpolation (v_interp_p1/p2) and flat attribute reads (v_interp_mov).

Attribute N is the PC input TEXCOORDN, a float4 (lowering.lower declares the signature). Attribute 0 is `uv`, the
preamble's TEXCOORD0; every other attribute is `attrN`. An attribute only interpolated (read by p1 and p2) is a linear
input; one only read flat (v_interp_mov) is nointerpolation and read through GetAttributeAtVertex. The console packs
flat and interpolated channels into one attribute slot, but one HLSL input has one interpolation mode: an attribute
read both ways is declared nointerpolation (attrN_v) and its interpolated value is the console's own evaluation,
P0 + I * P10 + J * P20, of the three vertex values with I and J the SV_Barycentrics weights of vertices 1 and 2
(lowering.lower writes it as the local attrN, or uv, at the top of main).

Exactness. The console evaluates P0 + I * P10 + J * P20 (p1 then p2, each a fused multiply-add); the PC rasterizer
interpolates the same plane in an order of its own. The two agree bit for bit when every term and every partial sum
of either evaluation is exactly representable, which the harness guarantees by its inputs, as for attr0 before:
small-integer vertex values and barycentrics that are multiples of 1/128 at the pixel centres (pixel_aot_vs.hlsl,
draw family interp_attrs). The translation claims no more than the rasterizer's interpolated value (or, for a mixed
attribute, the rasterizer's barycentrics).

The binary16 forms (v_interp_p1ll_f16, v_interp_p1lv_f16, v_interp_p2_f16) read binary16 attribute data packed two
to a channel (the `high` operand picks the half). A PC input is interpolated as one binary32 per component, so a
packed half has no input whose interpolation matches it; they are refused (interp_attrs controls).
"""
from ..dispatch import form
from ..control_flow import interpolation_half

ATTRIBUTES = range(32)  # TEXCOORD0..31


def attribute_name(attr):
    return "uv" if attr == 0 else f"attr{attr}"


def check_context(st, dst):
    # While the lane may be inactive (st.ex not "true": after a v_cmpx, a discard or inside a skipped region) the
    # interpolation is lowered as every VALU write is (lowering.masked_writes): an inactive lane keeps its old value.
    if st.scalar.get("m0") != "interp_base":
        raise ValueError("Unknown interpolation context")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")


@form(r"v_interp_p([12])_f32_e32 (v\d+), (v\d+), attr(\d+)\.([xyzw])")
def interpolate(st, i, m):
    # P0 + I * P10 (p1, from the I barycentric in v0) then + J * P20 (p2, from J in v1) of attribute N, read from the
    # slot m0 addresses: the pair is TEXCOORDN's component as the rasterizer interpolates it.
    # In whole-quad mode (after s_wqm_b64 exec, exec) the value is defined on the helper lanes too and is a quad value
    # (lowering.Lowering.quad_values) that an implicit-level sample may read; attr0.x and attr0.y keep the names uv.x
    # and uv.y they always had. At the entry mask (from R0Y00/Xbox2Windows#484 by Royoo for attr0) it is an ordinary
    # per-lane value. The two halves must be in the same mode, so the partial value records it.
    phase, dst, src, attr, component = m.groups()
    attr = int(attr)
    check_context(st, dst)
    if attr not in ATTRIBUTES:
        raise ValueError("Only attributes 0 to 31 can be interpolated")
    mode = "quad" if st.wqm else "entry"
    # While the lane may be inactive (CF-2), p1 and p2 are one masked write: on the console a lane off in EXEC runs
    # neither half and keeps the register's old value, an active lane gets P0 + I * P10 + J * P20. So the half records
    # the bit it ran under and the old value it replaced, p2 must run under the same bit (EXEC changed between the
    # halves would leave some lane with the half-done P0 + I * P10, no word), and lowering.masked_writes selects
    # `ex ? interpolated : old` at p2. A helper lane (whole-quad mode) runs with ex true, as every desktop helper
    # invocation does; a lane that discarded or failed a v_cmpx has ex false and keeps its old value. The value is
    # then the masked word, not a helper-lane value (Lowering.quad_values), which an implicit-level sample refuses.
    half = ("partial", attr, component, mode) if st.ex == "true" else \
        ("partial", attr, component, mode, st.ex, st.hidden.get(dst, st.vector.get(dst)))
    if phase == "1" and st.vector.get(src) == "bary_i":
        st.vector[dst] = half
        return
    current = st.vector.get(dst)
    # Under ex the half must be p1's under the same ex; its carried old value is whatever p1 found.
    paired = current == half if st.ex == "true" else interpolation_half(current, st.ex) and current[:4] == half[:4]
    if not (phase == "2" and st.vector.get(src) == "bary_j" and paired):
        raise ValueError("Unpaired interpolation")
    st.interp_attrs.add(attr)
    if attr == 0 and component in "zw":
        st.attribute_input = True
    name = f"{attribute_name(attr)}.{component}"
    if st.ex != "true":
        st.vector[dst] = f"alu{i}"
        st.lines.append(f"    float alu{i} = {name};")
        return
    if mode == "quad" and attr == 0 and component in "xy":
        st.vector[dst] = name
        return
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    float alu{i} = {name};")
    if mode == "quad":
        st.quad_values[f"alu{i}"] = True


@form(r"v_interp_mov_f32(?:_e32|_e64)? (v\d+), p(10|20|0), attr(\d+)\.([xyzw])")
def interpolate_move(st, i, m):
    # Copies one attribute channel without interpolation. The parameter is P0 (the first vertex's value), P10 =
    # P1 - P0 or P20 = P2 - P0, the terms of P0 + I * P10 + J * P20 that v_interp_p1 and p2 evaluate, selected by
    # p0, p10 and p20, and read from the attribute slot that m0 addresses, so m0 must hold the interpolation
    # base as for those. Parameter selection: LLVM AMDGPU gfx1030 operand table ("Interpolation parameter to
    # read"); semantics: CLRX GCN VINTRP page, V_INTERP_MOV_F32 ("Move parameter value into VDST").
    # A flat attribute is an input declared nointerpolation; GetAttributeAtVertex (shader model 6.1) reads its
    # three vertex values. It is read in whole-quad mode or at the entry mask alike: the vertex values are the
    # primitive's, the same on every lane.
    dst, param, attr, channel = m.groups()
    attr = int(attr)
    check_context(st, dst)
    if attr not in ATTRIBUTES:
        raise ValueError("Only attributes 0 to 31 can be read without interpolation")

    def vertex(k):
        return f"GetAttributeAtVertex(attr{attr}, {k}).{channel}"
    value = {"0": vertex(0), "10": f"({vertex(1)} - {vertex(0)})", "20": f"({vertex(2)} - {vertex(0)})"}[param]
    st.flat_attrs.add(attr)
    st.vector[dst] = f"alu{i}"
    if st.wqm:
        # The primitive's vertex values, the same on every lane of the quad, helper lanes included: a quad value
        # (lowering.Lowering.quad_values) that does not vary with the interpolated coordinate.
        st.quad_values[f"alu{i}"] = False
    st.lines.append(f"    precise float alu{i} = {value};")


@form(r"v_interp_(?:p1ll|p1lv|p2)_f16\b.*")
def interpolate_f16(st, i, m):
    # Binary16 attribute data, two halves to a channel (module docstring): refused, with a reason of its own.
    raise ValueError("Binary16 attribute interpolation has no PC input to match it")
