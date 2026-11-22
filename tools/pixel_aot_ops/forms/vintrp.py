"""VINTRP: attribute interpolation (v_interp_p1/p2) and flat attribute reads (v_interp_mov)."""
from ..dispatch import form


@form(r"v_interp_p([12])_f32_e32 (v\d+), (v\d+), attr0\.([xyzw])")
def interpolate(st, i, m):
    # P0 + I * P10 (p1, from the I barycentric in v0) then + J * P20 (p2, from J in v1) of attribute 0, read from the
    # slot m0 addresses: the pair is TEXCOORD0's component as the rasterizer interpolates it.
    # In whole-quad mode (after s_wqm_b64 exec, exec), the coordinate a sample's implicit level differentiates: x and
    # y only, and the result is a quad value (lowering.Lowering.quad_values).
    # At the entry mask with no sampler bound (lower(sampler=None)), any of the four components, as an ordinary
    # per-lane value; TEXCOORD0 is then declared float4 (from R0Y00/Xbox2Windows#484 by Royoo). The two halves must
    # be in the same mode, so the partial value records it.
    phase, dst, src, component = m.groups()
    entry = not st.wqm and st.ex == "true" and not st.bindings
    if ((not entry and (not st.wqm or st.ex != "true" or component not in "xy"))
            or st.scalar.get("m0") != "interp_base"):
        raise ValueError("Unknown interpolation context")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    if phase == "1" and st.vector.get(src) == "bary_i":
        st.vector[dst] = ("partial", component, entry)
    elif phase == "2" and st.vector.get(src) == "bary_j" and st.vector.get(dst) == ("partial", component, entry):
        if entry:
            st.attribute_input = True
            st.vector[dst] = f"alu{i}"
            st.lines.append(f"    float alu{i} = uv.{component};")
        else:
            st.vector[dst] = f"uv.{component}"
    else:
        raise ValueError("Unpaired interpolation")


@form(r"v_interp_mov_f32(?:_e32|_e64)? (v\d+), p(10|20|0), attr(\d+)\.([xyzw])")
def interpolate_move(st, i, m):
    # Copies one attribute channel without interpolation. The parameter is P0 (the first vertex's value), P10 =
    # P1 - P0 or P20 = P2 - P0, the terms of P0 + I * P10 + J * P20 that v_interp_p1 and p2 evaluate, selected by
    # p0, p10 and p20, and read from the attribute slot that m0 addresses, so m0 must hold the interpolation
    # base as for those. Parameter selection: LLVM AMDGPU gfx1030 operand table ("Interpolation parameter to
    # read"); semantics: CLRX GCN VINTRP page, V_INTERP_MOV_F32 ("Move parameter value into VDST").
    # A flat attribute is an input declared nointerpolation; GetAttributeAtVertex (shader model 6.1) reads its
    # three vertex values. Attribute N is TEXCOORDN. Attribute 0 is the interpolated TEXCOORD0 read by
    # v_interp_p1 and p2 and cannot also be flat.
    dst, param, attr, channel = m.groups()
    if not st.wqm or st.ex != "true" or st.scalar.get("m0") != "interp_base":
        raise ValueError("Unknown interpolation context")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    if not 1 <= int(attr) <= 31:
        raise ValueError("Only attributes 1 to 31 can be read without interpolation")

    def vertex(k):
        return f"GetAttributeAtVertex(attr{attr}, {k}).{channel}"
    value = {"0": vertex(0), "10": f"({vertex(1)} - {vertex(0)})", "20": f"({vertex(2)} - {vertex(0)})"}[param]
    st.flat_attrs.add(int(attr))
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {value};")
