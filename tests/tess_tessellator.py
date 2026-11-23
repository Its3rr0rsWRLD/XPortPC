"""The tessellator check of cards T-1 and T-2 (docs/design/stages.md, "The tessellator"): does the desktop's fixed-function
tessellator produce the domain points and triangles the console's does, for each domain, partitioning and winding?

The console reference is the D3D11 fixed-function tessellator as Microsoft specifies it in code (CHWTessellator,
tests/third_party/d3d11_tessellator, run through tests/tess_reference.cpp). RADV programs the gfx10 tessellator with
the factors the hull shader writes to the TF ring and the partitioning and output winding of VGT_TF_PARAM, and does
not transform the domain points the hardware hands the evaluation shader (radv_cmd_buffer.c
radv_emit_tess_domain_origin_state; ac_nir_lower_tess_io_to_mem.c hs_store_tess_factors_for_tessellator): the
console's points are what its tessellator computes, which is the D3D11 specification it implements. A capture on the
console itself would confirm that and is not available here; the measurement below is of the desktop.

The desktop side draws patches through a probe hull shader (factors from the constant buffer, one per patch, by
SV_PrimitiveID) and a probe domain shader whose stream output holds SV_DomainLocation as raw words and the patch id.
Each captured triangle is keyed by its domain points (u, v as binary32 words, rotated so the smallest key comes first,
which keeps the winding), and the multiset of triangles of each patch is compared with the reference's. A partitioning
is "exact" on an adapter when every patch matches bit for bit.
"""
from collections import Counter
import math
from pathlib import Path
import struct
import subprocess

M32 = 0xffffffff
DOMAINS = ("tri", "quad")
PARTITIONINGS = ("integer", "pow2", "fractional_odd", "fractional_even")
TOPOLOGIES = ("triangle_cw", "triangle_ccw")
FACTOR_COUNT = {"tri": 4, "quad": 6}


def f32(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def factor_sets(domain, seed=7):
    """Factor tuples (binary32 words) for one draw: uniform and mixed integers, the fractional range on both sides of
    each odd and even step, the clamps (below 1, above 64), and seeded random values. Every factor is positive and
    finite, so no patch is culled; culled patches are their own family (culled_sets)."""
    count = FACTOR_COUNT[domain]
    values = [1.0, 1.5, 2.0, 2.25, 2.5, 3.0, 3.5, 3.999, 4.0, 4.001, 5.3, 6.0, 7.9, 8.0, 9.5, 12.0, 13.1, 16.0, 17.5]
    out = [tuple([v] * count) for v in values]
    out += [(0.25,) * count, (63.0,) * count, (64.0,) * count, (70.0,) * count]
    state = seed
    for _ in range(48):
        row = []
        for _ in range(count):
            state = (state * 6364136223846793005 + 1442695040888963407) % (1 << 64)
            row.append(0.5 + (state >> 40) % 20000 / 1000.0)  # 0.5 .. 20.5 in steps of 1/1000
        out.append(tuple(row))
    # Edges unequal to the inside factor, which exercises the transition rings.
    out += [(1.0, 2.0, 3.0, 4.0, 5.0, 6.0)[:count], (7.5, 1.0, 1.0, 3.3, 2.0, 9.0)[:count],
            (2.0, 2.0, 2.0, 1.0, 1.0, 1.0)[:count], (1.0, 1.0, 1.0, 9.0, 9.0, 9.0)[:count]]
    return [tuple(f32(v) for v in row) for row in out]


def culled_sets(domain):
    """Patches the tessellator discards: an outer factor that is 0, negative or NaN (inside factors ignored)."""
    count = FACTOR_COUNT[domain]
    edges = count - (1 if domain == "tri" else 2)
    rows = []
    for bad in (0.0, -1.0, float("nan")):
        for edge in range(edges):
            row = [4.0] * count
            row[edge] = bad
            rows.append(tuple(f32(v) if not math.isnan(v) else 0x7fc00000 for v in row))
    return rows


def run_reference(tool, domain, partitioning, topology, patches):
    """[(points [(u, v)], triangles [(a, b, c) indices])] for each factor tuple, from tests/tess_reference.cpp."""
    text = "".join(f"{domain} {partitioning} {topology} {' '.join(f'{w:08x}' for w in row)}\n" for row in patches)
    result = subprocess.run([str(tool)], input=text, capture_output=True, text=True, check=True)
    lines = result.stdout.splitlines()
    assert len(lines) == 2 * len(patches), (len(lines), len(patches))
    out = []
    for j in range(len(patches)):
        pts = lines[2 * j].split()
        idx = lines[2 * j + 1].split()
        assert pts[0] == "points" and idx[0] == "indices"
        words = [int(w, 16) for w in pts[2:]]
        points = list(zip(words[0::2], words[1::2]))
        indices = [int(i) for i in idx[2:]]
        assert len(points) == int(pts[1]) and len(indices) == int(idx[1]) and len(indices) % 3 == 0
        out.append((points, [tuple(indices[k:k + 3]) for k in range(0, len(indices), 3)]))
    return out


def canonical(triangle):
    """A triangle of point keys rotated so that its smallest key comes first: the same winding compares equal."""
    k = triangle.index(min(triangle))
    return triangle[k:] + triangle[:k]


def reference_triangles(points, triangles):
    return Counter(canonical(tuple(points[i] for i in t)) for t in triangles)


PROBE_HS = """cbuffer Constants : register(b0) {{ uint4 params[{rows}]; }};
struct Cp {{ uint id : TEXCOORD0; }};
struct Patch {{ float edges[{edges}] : SV_TessFactor; {inside_decl} }};
Patch pcf(uint patch : SV_PrimitiveID) {{
    Patch p;
    uint4 a = params[2 * patch], b = params[2 * patch + 1];
    uint f[6] = {{ a.x, a.y, a.z, a.w, b.x, b.y }};
{assign}
    return p;
}}
[domain("{domain}")]
[partitioning("{partitioning}")]
[outputtopology("{topology}")]
[outputcontrolpoints(1)]
[patchconstantfunc("pcf")]
Cp main(InputPatch<Cp, 1> ip, uint i : SV_OutputControlPointID) {{ return ip[i]; }}
"""

PROBE_DS = """struct Cp {{ uint id : TEXCOORD0; }};
struct Patch {{ float edges[{edges}] : SV_TessFactor; {inside_decl} }};
struct Out {{ float4 pos : SV_Position; uint4 probe : TEXCOORD0; }};
[domain("{domain}")]
Out main(Patch p, {loc_type} loc : SV_DomainLocation, uint prim : SV_PrimitiveID, const OutputPatch<Cp, 1> cp) {{
    Out o;
    o.pos = float4(0.0, 0.0, 0.0, 1.0);
    o.probe = uint4(asuint(loc.x), asuint(loc.y), {third}, prim);
    return o;
}}
"""

PROBE_VS = """struct Cp { uint id : TEXCOORD0; };
Cp main(uint vid : SV_VertexID) { Cp c; c.id = vid; return c; }
"""


def probe_sources(domain, partitioning, topology, patches):
    edges, inside = (3, 1) if domain == "tri" else (4, 2)
    inside_decl = ("float inside : SV_InsideTessFactor;" if inside == 1 else
                   "float inside[2] : SV_InsideTessFactor;")
    assign = [f"    p.edges[{j}] = asfloat(f[{j}]);" for j in range(edges)]
    assign += ([f"    p.inside = asfloat(f[{edges}]);"] if inside == 1 else
               [f"    p.inside[{j}] = asfloat(f[{edges + j}]);" for j in range(2)])
    rows = max(16, 2 * patches)
    hs = PROBE_HS.format(rows=rows, edges=edges, inside_decl=inside_decl, assign="\n".join(assign), domain=domain,
                         partitioning=partitioning, topology=topology)
    ds = PROBE_DS.format(edges=edges, inside_decl=inside_decl, domain=domain,
                         loc_type="float3" if domain == "tri" else "float2",
                         third="asuint(loc.z)" if domain == "tri" else "0u")
    return PROBE_VS, hs, ds


def tess_case(control_points, patches, semantics, capacity, constants, descriptors=None, push=(), memory=b""):
    """tests/vertex_aot_render.cpp's tessellation case file."""
    descriptors = [0] * 64 if descriptors is None else descriptors
    assert len(constants) % 4 == 0 and 64 <= len(constants) <= 16384 and len(descriptors) == 64
    assert 1 <= len(semantics) <= 16 and len(push) <= 32
    header = [0x54573258, control_points, patches, len(semantics), *semantics, *[0] * (16 - len(semantics)),
              capacity, 0 if len(constants) == 64 else len(constants), len(push), *[0] * 9]
    assert len(header) == 32
    body = header + list(constants) + list(descriptors) + list(push)
    return struct.pack(f"<{len(body)}I", *body) + memory


def read_capture(path):
    """(stride in words, [record words]) of a --capture-tess-case output file."""
    data = Path(path).read_bytes()
    filled, stride = struct.unpack_from("<II", data)
    assert len(data) == 8 + filled and stride % 4 == 0
    words = struct.unpack_from(f"<{filled // 4}I", data, 8)
    n = stride // 4
    return n, [list(words[k:k + n]) for k in range(0, len(words), n)]


def compile_shader(compiler, source, directory, name, model):
    hlsl, shader = Path(directory) / f"{name}.hlsl", Path(directory) / f"{name}.cso"
    hlsl.write_text(source, encoding="ascii")
    subprocess.run([str(compiler), "-Gis", "-T", model, "-E", "main", "-Fo", str(shader), str(hlsl)], check=True)
    return shader


def capture(renderer, backend, shaders, case_path, case_bytes, out_path):
    Path(case_path).write_bytes(case_bytes)
    result = subprocess.run([str(renderer), backend, "--capture-tess-case", *map(str, shaders), str(case_path),
                             str(out_path)], capture_output=True, text=True)
    if result.returncode == 77:
        return 77, None
    if result.returncode:
        raise AssertionError(f"tessellation capture failed ({result.returncode}): {result.stdout}{result.stderr}")
    return 0, read_capture(out_path)


def measure(directory, compiler, renderer, backend, tool, domain, partitioning, topology):
    """Draw the factor sets and the culled sets through the probe; returns (summary dict, first mismatch or None),
    or None for a capability skip."""
    rows = factor_sets(domain) + culled_sets(domain)
    references = run_reference(tool, domain, partitioning, topology, rows)
    constants = []
    for row in rows:
        constants += list(row) + [0] * (8 - len(row))
    constants += [0] * (max(64, len(constants)) - len(constants))
    constants += [0] * (-len(constants) % 4)
    expected_records = sum(3 * len(tris) for _, tris in references)
    capacity = 2 * expected_records + 192
    name = f"probe_{domain}_{partitioning}_{topology}"
    vs_src, hs_src, ds_src = probe_sources(domain, partitioning, topology, len(rows))
    shaders = [compile_shader(compiler, vs_src, directory, f"{name}_vs", "vs_6_0"),
               compile_shader(compiler, hs_src, directory, f"{name}_hs", "hs_6_0"),
               compile_shader(compiler, ds_src, directory, f"{name}_ds", "ds_6_0")]
    code, captured = capture(renderer, backend, shaders, Path(directory) / f"{name}.case",
                             tess_case(1, len(rows), [0, 1], capacity, constants), Path(directory) / f"{name}.out")
    if code == 77:
        return None
    _, records = captured
    assert len(records) % 3 == 0
    by_patch = {}
    third = Counter()
    for k in range(0, len(records), 3):
        tri = records[k:k + 3]
        patches = {r[7] for r in tri}
        if len(patches) != 1:
            raise AssertionError(f"{name}: a captured triangle spans patches {sorted(patches)}")
        by_patch.setdefault(tri[0][7], Counter())[canonical(tuple((r[4], r[5]) for r in tri))] += 1
        if domain == "tri":
            for r in tri:
                w = struct.unpack("<f", struct.pack("<I", r[6]))[0]
                exact = struct.unpack("<I", struct.pack("<f", 1.0 - struct.unpack("<f", struct.pack("<I", r[4]))[0]
                                                         - struct.unpack("<f", struct.pack("<I", r[5]))[0]))[0]
                third["w_is_1_minus_u_minus_v" if r[6] == exact else "w_other"] += 1
                del w
    mismatch = None
    exact_patches = 0
    for j, (points, tris) in enumerate(references):
        want = reference_triangles(points, tris)
        got = by_patch.pop(j, Counter())
        if got == want:
            exact_patches += 1
            continue
        if mismatch is None:
            only_ref = sorted(want - got)[:2]
            only_gpu = sorted(got - want)[:2]
            ref_points = {p for t in want for p in t}
            gpu_points = {p for t in got for p in t}
            mismatch = (f"patch {j} factors {' '.join(f'{w:08x}' for w in rows[j])}: reference {sum(want.values())} "
                        f"triangles / {len(ref_points)} points, desktop {sum(got.values())} / {len(gpu_points)}; "
                        f"points only in the reference {sorted(ref_points - gpu_points)[:3]}, only on the desktop "
                        f"{sorted(gpu_points - ref_points)[:3]}; triangles only in the reference {only_ref}, only on "
                        f"the desktop {only_gpu}")
    if by_patch:
        mismatch = mismatch or f"captured triangles of patches the reference has no rows for: {sorted(by_patch)[:4]}"
    summary = {"patches": len(rows), "exact": exact_patches, "records": len(records),
               "reference_records": expected_records, **third}
    return summary, mismatch


def check(directory, compiler, renderer, backend, tool, configs=None):
    """Measure every (domain, partitioning, topology); print one line each and return ({config: exact?}, skipped)."""
    results = {}
    for domain in DOMAINS:
        for partitioning in PARTITIONINGS:
            for topology in TOPOLOGIES:
                config = (domain, partitioning, topology)
                if configs is not None and config not in configs:
                    continue
                measured = measure(directory, compiler, renderer, backend, tool, *config)
                if measured is None:
                    return results, True
                summary, mismatch = measured
                exact = mismatch is None
                results[config] = exact
                fields = " ".join(f"{k}={v}" for k, v in summary.items())
                print(f"tessellator {backend} {domain} {partitioning} {topology}: "
                      f"{'exact' if exact else 'MISMATCH'} {fields}" + ("" if exact else f" first: {mismatch}"),
                      flush=True)
    return results, False
