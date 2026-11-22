"""Draw family `interp_attrs`: v_interp_p1/p2_f32 and v_interp_mov_f32 on any attribute and channel (forms/vintrp.py).

Every draw is an unsampled program (lower(sampler=None)) that reads four attribute channels, interpolated or flat, at
the entry mask or in whole-quad mode, and exports them uncompressed as binary32 into a 32 by 32 float target
(--check-pixel-attribute), compared bit for bit. The per-vertex values are the harness vertex shader's table
(tests/pixel_aot_vs.hlsl, read by attribute_vertices); attribute 0 is its full-screen coordinate.

Exactness: at the centre of pixel (x, y) the barycentrics of vertices 1 and 2 are I = (2x + 1) / 128 and
J = (2y + 1) / 128, and the vertex values are small integers, so every term and partial sum of P0 + I * P10 + J * P20
and of (1 - I - J) * P0 + I * P1 + J * P2 is exact in binary32 (exact_inputs checks all of them): whatever order the
rasterizer evaluates, its value is the console's. That is the rule the attr0 draws (family unsampled) relied on.

Each channel is checked against its wrong references: another attribute, another channel, p1 and p2 swapped (I and J
exchanged, or P10 and P20), and flat instead of interpolated (or the reverse). Each wrong reference must differ from
the right one at some pixel, and the renderer must report the mismatch.
"""
from fractions import Fraction
from pathlib import Path
import re
import struct
import subprocess

from .common import lower, must_reject

SIZE = 32
CHANNELS = "xyzw"
VS = Path(__file__).resolve().parents[1] / "pixel_aot_vs.hlsl"


def attribute_vertices():
    """{attribute: (P0, P1, P2)}, each a 4-tuple of Fractions: attribute 0 from the shader's uv formula, 1..7 from its
    ATTRIBUTES table."""
    text = VS.read_text(encoding="utf-8")
    table = text[text.index("static const float4 ATTRIBUTES[7][3]"):]
    table = table[:table.index("};")]
    rows = re.findall(r"\{\s*float4\(([^)]*)\),\s*float4\(([^)]*)\),\s*float4\(([^)]*)\)\s*\}", table)
    assert len(rows) == 7, rows
    vertices = {n + 1: tuple(tuple(Fraction(int(v)) for v in vertex.split(",")) for vertex in row)
                for n, row in enumerate(rows)}
    uv = lambda x, y: (Fraction(x), Fraction(y), Fraction(1, 4) + Fraction(x, 2), 1 - Fraction(y))
    vertices[0] = (uv(0, 0), uv(2, 0), uv(0, 2))
    return vertices


VERTICES = attribute_vertices()
ATTRS = sorted(VERTICES)


def barycentrics(x, y):
    return Fraction(2 * x + 1, 128), Fraction(2 * y + 1, 128)


def value(read, x, y):
    """The console's value of one read (kind, attribute, channel) at pixel (x, y). kind: "interp", "p0", "p10", "p20",
    or the wrong-reference kinds "swapped" (I and J exchanged)."""
    kind, attr, channel = read
    p0, p1, p2 = (vertex[CHANNELS.index(channel)] for vertex in VERTICES[attr])
    i, j = barycentrics(x, y)
    return {"interp": p0 + i * (p1 - p0) + j * (p2 - p0), "swapped": p0 + j * (p1 - p0) + i * (p2 - p0),
            "p0": p0, "p10": p1 - p0, "p20": p2 - p0}[kind]


def exact32(number):
    rounded = Fraction(struct.unpack("<f", struct.pack("<f", float(number)))[0])
    return rounded == number


def exact_inputs():
    """Every term and partial sum of both evaluation orders is a binary32 value at every pixel centre, and P10 and P20
    are nonzero and differ in every channel (so that swapping p1 and p2 is visible)."""
    for attr, (p0s, p1s, p2s) in VERTICES.items():
        for c in range(4):
            p0, p1, p2 = p0s[c], p1s[c], p2s[c]
            assert (attr == 0 or (p1 != p0 and p2 != p0)) and p1 - p0 != p2 - p0, (attr, c)
            for y in range(SIZE):
                for x in range(SIZE):
                    i, j = barycentrics(x, y)
                    d1, d2 = p1 - p0, p2 - p0
                    terms = (p0, p1, p2, d1, d2, i, j, i * d1, j * d2, p0 + i * d1, p0 + j * d2, i * d1 + j * d2,
                             1 - i - j, (1 - i - j) * p0, i * p1, j * p2, (1 - i - j) * p0 + i * p1,
                             i * p1 + j * p2, (1 - i - j) * p0 + j * p2, p0 + i * d1 + j * d2)
                    assert all(exact32(t) for t in terms), (attr, c, x, y)


def program(reads, wqm):
    """The four reads into v8..v11 and their uncompressed export. Interpolations issue every p1 first and their p2
    in the opposite order, so a pairing by position would be wrong."""
    code = ["s_mov_b64 s[50:51], exec", "s_wqm_b64 exec, exec"] if wqm else []
    code.append("s_mov_b32 m0, s14")
    interp = [(k, read) for k, read in enumerate(reads) if read[0] == "interp"]
    for k, (kind, attr, channel) in enumerate(reads):
        if kind != "interp":
            code.append(f"v_interp_mov_f32_e32 v{8 + k}, {kind}, attr{attr}.{channel}")
    code += [f"v_interp_p1_f32_e32 v{8 + k}, v0, attr{attr}.{channel}" for k, (_, attr, channel) in interp]
    code += [f"v_interp_p2_f32_e32 v{8 + k}, v1, attr{attr}.{channel}" for k, (_, attr, channel) in reversed(interp)]
    if wqm:
        code.append("s_and_b64 exec, exec, s[50:51]")
    return code + ["exp mrt0 v8, v9, v10, v11 done vm", "s_endpgm"]


def translate_attributes(code):
    return lower(code, 8, 14, None)


def rotate(sequence, n):
    return sequence[n % len(sequence):] + sequence[:n % len(sequence)]


# At the entry mask: all four channels of each attribute, in an order that differs per attribute.
ENTRY = [(tuple(("interp", attr, c) for c in rotate("wzxy", attr)), False) for attr in ATTRS]
# In whole-quad mode: slot c of draw k reads channel c of attribute k + c, so the eight draws read every channel of
# every attribute, four attributes in each.
QUAD = [(tuple(("interp", ATTRS[(k + c) % len(ATTRS)], CHANNELS[c]) for c in range(4)), True) for k in range(len(ATTRS))]
# Flat and interpolated reads of one attribute (the console packs both into one slot): the attribute is then
# nointerpolation and interpolated from SV_Barycentrics. And attribute 0 read flat only.
MIXED = [
    ((("interp", 2, "x"), ("p0", 2, "y"), ("p20", 2, "z"), ("interp", 5, "w")), False),
    ((("interp", 0, "x"), ("p10", 3, "y"), ("interp", 7, "z"), ("p0", 0, "w")), True),
    ((("p20", 0, "y"), ("p10", 0, "x"), ("p20", 0, "z"), ("interp", 6, "w")), False),
    ((("p20", 4, "w"), ("interp", 4, "y"), ("interp", 1, "z"), ("p10", 7, "x")), True),
]
DRAWS = ENTRY + QUAD + MIXED


def wrong_reads(read):
    """The wrong references of one read: another attribute, another channel, p1/p2 swapped, flat/interpolated."""
    kind, attr, channel = read
    other_attr = ATTRS[(ATTRS.index(attr) + 1) % len(ATTRS)]
    other_channel = CHANNELS[(CHANNELS.index(channel) + 1) % 4]
    swapped = {"interp": "swapped", "p0": "p10", "p10": "p20", "p20": "p10"}[kind]
    flat = "p0" if kind == "interp" else "interp"
    return [("attribute", (kind, other_attr, channel)), ("channel", (kind, attr, other_channel)),
            ("p1/p2 swapped", (swapped, attr, channel)), ("flat/interpolated", (flat, attr, channel))]


def reference(reads, wrong=None):
    """The 32 by 32 float4 colors, row-major; wrong = (slot, read) replaces one slot's read."""
    data = bytearray(256)
    for y in range(SIZE):
        for x in range(SIZE):
            channels = [value(wrong[1] if wrong and wrong[0] == k else read, x, y) for k, read in enumerate(reads)]
            data += struct.pack("<4f", *(float(c) for c in channels))
    return bytes(data)


def shader_model(source):
    return "ps_6_1" if "GetAttributeAtVertex" in source else "ps_6_0"


def controls(directory):
    exact_inputs()
    for reads, wqm in DRAWS:
        source = translate_attributes(program(reads, wqm))
        right = reference(reads)
        for slot, read in enumerate(reads):
            for name, wrong in wrong_reads(read):
                assert reference(reads, (slot, wrong)) != right, (reads, slot, name)
        attrs = {attr for _, attr, _ in reads}
        flat = {attr for kind, attr, _ in reads if kind != "interp"}
        interp = {attr for kind, attr, _ in reads if kind == "interp"}
        for n in range(1, max(attrs) + 1):
            name = f"attr{n}_v" if n in flat & interp else f"attr{n}"
            mode = "nointerpolation " if n in flat else ""
            assert f", {mode}float4 {name} : TEXCOORD{n}" in source, (n, source)
        assert ("SV_Barycentrics" in source) == bool(flat & interp), source
        if 0 in flat:
            assert f"nointerpolation float4 attr0{'_v' if 0 in interp else ''} : TEXCOORD0" in source, source
    # Whole-quad interpolation is a helper-lane value (lowering.Lowering.quad_values); at the entry mask it is not.
    code = program(QUAD[3][0], True)
    st_source = translate_attributes(code)
    assert "float alu" in st_source and "attr4.y" in st_source, st_source
    # An attribute read only in TEXCOORD3 still declares TEXCOORD1 and 2, so that it sits in the vertex shader's register.
    source = translate_attributes(program((("interp", 3, "x"), ("interp", 3, "y"), ("p0", 1, "x"), ("interp", 3, "w")), False))
    assert ("SV_Position, nointerpolation float4 attr1 : TEXCOORD1, float4 attr2 : TEXCOORD2, "
            "float4 attr3 : TEXCOORD3)") in source, source
    mixed = translate_attributes(program(*MIXED[0]))
    assert ("precise float4 attr2 = (GetAttributeAtVertex(attr2_v, 0) + bary.y * (GetAttributeAtVertex(attr2_v, 1) - "
            "GetAttributeAtVertex(attr2_v, 0))) + bary.z * (GetAttributeAtVertex(attr2_v, 2) - "
            "GetAttributeAtVertex(attr2_v, 0));") in mixed, mixed
    assert "float alu" in mixed and "= attr2.x;" in mixed and "GetAttributeAtVertex(attr2," not in mixed, mixed

    base = program(ENTRY[2][0], False)  # attribute 2, channels x y z w after rotation by 2: x y w z
    p1 = next(n for n, line in enumerate(base) if line.startswith("v_interp_p1"))
    p2 = next(n for n, line in enumerate(base) if line.startswith("v_interp_p2"))
    first, second = base[p1], base[p2]
    reject = lambda code: must_reject(translate_attributes, code)
    reject([line for line in base if line != second])  # p1 alone: its partial value is exported
    reject([line for line in base if line != first])  # p2 without p1
    reject([line.replace(", v0, ", ", v1, ") if line == first else line for line in base])  # p1 from J
    reject([line.replace(", v1, ", ", v0, ") if line == second else line for line in base])  # p2 from I
    reject([second.replace("v_interp_p2", "v_interp_p1").replace(", v1, ", ", v0, ") if line == first
            else first.replace("v_interp_p1", "v_interp_p2").replace(", v0, ", ", v1, ") if line == second
            else line for line in base])  # p2 issued before p1
    for old, new in (("attr2.", "attr3."), ("attr2.", "attr0.")):
        reject([line.replace(old, new) if line == second else line for line in base])  # p2 of another attribute
    channel = second[-1]
    reject([line[:-1] + CHANNELS[(CHANNELS.index(channel) + 1) % 4] if line == second else line for line in base])
    reject([line for line in base if line != "s_mov_b32 m0, s14"])
    reject([line.replace("m0, s14", "m0, s15") for line in base])
    reject(base[:p2] + ["s_mov_b64 s[50:51], exec", "s_wqm_b64 exec, exec"] + base[p2:])  # p1 at entry, p2 in WQM
    reject(base[:p1] + ["v_add_f32_e32 v20, 1.0, v0"] + base[p1:])  # the barycentrics are not numeric
    reject(base[:p2] + [f"v_add_f32_e32 v20, 1.0, {first.split()[1].rstrip(',')}"] + base[p2:])  # nor a partial value
    for line in ("v_interp_p1_f32_e32 v8, v0, attr32.x", "v_interp_mov_f32_e32 v8, p0, attr32.x",
                 "v_interp_p1_f32_e64 v8, v0, attr1.x", "v_interp_p2_f32_e64 v8, v1, attr1.x",
                 "v_interp_p1_f32_e32 v8, v0, attr1.x high", "v_interp_mov_f32_e32 v8, p1, attr1.x",
                 # binary16 attribute data (packed halves) has no PC input interpolated to match it: refused.
                 "v_interp_p1ll_f16 v8, v0, attr1.x", "v_interp_p1ll_f16 v8, v0, attr1.x high",
                 "v_interp_p1lv_f16 v8, v0, attr1.x, v2", "v_interp_p1lv_f16 v8, v0, attr1.x, v2 high",
                 "v_interp_p2_f16 v8, v1, attr1.x, v8", "v_interp_p2_f16 v8, v1, attr1.x, v8 high"):
        reject(base[:p1] + [line] + base[p1:])
    # A flat read of the attribute in the middle of its interpolation still pairs p1 with p2.
    assert "attr2_v" in translate_attributes(base[:p2] + ["v_interp_mov_f32_e32 v20, p0, attr2.x"] + base[p2:])


def binary_fixtures():
    return [(program(reads, wqm), translate_attributes) for reads, wqm in DRAWS]


def draw(directory, compiler, renderer, backend):
    src, cso, case = (directory / name for name in ("interp.hlsl", "interp.cso", "interp.case"))
    for index, (reads, wqm) in enumerate(DRAWS):
        source = translate_attributes(program(reads, wqm))
        src.write_text(source, encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", shader_model(source), "-E", "main", "-Fo", cso, src], check=True)
        cmd = [renderer, backend, "--check-pixel-attribute", cso, case]
        case.write_bytes(reference(reads))
        result = subprocess.run(cmd)
        if result.returncode:
            return result.returncode
        for slot, read in enumerate(reads):
            for name, wrong in wrong_reads(read):
                case.write_bytes(reference(reads, (slot, wrong)))
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"Draw {index}: a wrong {name} reference for {read} escaped detection")
    return 0
