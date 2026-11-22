"""Source-built instruction regressions for the dispatch translator."""
from pathlib import Path
import math
import re
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from ffx_dispatch_aot import alu, disassemble, predecessor, translate
from ffx_scratch_reference import network, simm16


def asint(x):
    x &= 0xffffffff
    return x - 0x100000000 if x & 0x80000000 else x


def bfe_u_hlsl(src, offset, width):
    # Match HLSL SM6 32-bit shift masking (& 31) in tests/ffx_dispatch_io.hlsli.
    count = min(width & 0xffffffff, 32)
    shift = (32 - count) & 31
    return ((src & 0xffffffff) >> (offset & 31)) & (0xffffffff >> shift) if count != 0 else 0


def bfe_i_hlsl(src, offset, width):
    count = min(width & 0xffffffff, 32)
    shift = (32 - count) & 31
    shifted = asint(src) >> (offset & 31)
    aligned = ((shifted & 0xffffffff) << shift) & 0xffffffff
    return (asint(aligned) >> shift) & 0xffffffff if count != 0 else 0


def rdna_bfe(src, offset, width, signed_ext):
    offset &= 31
    width = min(width, 32)
    if width == 0:
        return 0
    bits = [(src >> i) & 1 for i in range(32)]
    msb = bits[31] if signed_ext else 0
    field = [bits[offset + i] if offset + i < 32 else msb for i in range(width)]
    fill = field[-1] if signed_ext else 0
    return sum(bit << i for i, bit in enumerate(field + [fill] * (32 - width)))


def sadd_u_hlsl(a, b):
    a, b = a & 0xffffffff, b & 0xffffffff
    r = (a + b) & 0xffffffff
    return r, (1 if r < a else 0)


def slshl4_add_u_hlsl(a, b):
    a, b = a & 0xffffffff, b & 0xffffffff
    shifted = (a << 4) & 0xffffffff
    r = (shifted + b) & 0xffffffff
    return r, (1 if ((a >> 28) != 0 or r < shifted) else 0)


def sadd_i_hlsl(a, b):
    a, b = a & 0xffffffff, b & 0xffffffff
    r = (a + b) & 0xffffffff
    scc = (((~(a ^ b)) & (a ^ r)) >> 31) & 1
    return r, scc


def ssub_i_hlsl(a, b):
    a, b = a & 0xffffffff, b & 0xffffffff
    r = (a - b) & 0xffffffff
    scc = (((a ^ b) & (a ^ r)) >> 31) & 1
    return r, scc


def smin_u_hlsl(a, b):
    a, b = a & 0xffffffff, b & 0xffffffff
    scc = 1 if a < b else 0
    return (a if scc else b), scc


def smax_u_hlsl(a, b):
    a, b = a & 0xffffffff, b & 0xffffffff
    scc = 1 if a > b else 0
    return (a if scc else b), scc


def smin_i_hlsl(a, b):
    a, b = a & 0xffffffff, b & 0xffffffff
    scc = 1 if asint(a) < asint(b) else 0
    return (a if scc else b), scc


def smax_i_hlsl(a, b):
    a, b = a & 0xffffffff, b & 0xffffffff
    scc = 1 if asint(a) > asint(b) else 0
    return (a if scc else b), scc


def sabs_i_hlsl(a):
    a &= 0xffffffff
    r = (0 - a) & 0xffffffff if asint(a) < 0 else a
    return r, (1 if r != 0 else 0)


SALU_HELPERS = {
    "sadd_u": sadd_u_hlsl,
    "slshl4_add_u": slshl4_add_u_hlsl,
    "sadd_i": sadd_i_hlsl,
    "ssub_i": ssub_i_hlsl,
    "smin_u": smin_u_hlsl,
    "smax_u": smax_u_hlsl,
    "smin_i": smin_i_hlsl,
    "smax_i": smax_i_hlsl,
    "sabs_i": sabs_i_hlsl,
}


# Input binary32, expected unsigned word, expected signed word.
CONVERSIONS = (
    (0x00000000, 0, 0), (0x80000000, 0, 0), (1, 0, 0), (0x80000001, 0, 0),
    (0x3fc00000, 1, 1), (0xc0300000, 0, 0xfffffffe),
    (0x7fc01234, 0, 0), (0xffc01234, 0, 0),
    (0x7f800000, 0xffffffff, 0x7fffffff), (0xff800000, 0, 0x80000000),
    (0x4effffff, 0x7fffff80, 0x7fffff80), (0x4f000000, 0x80000000, 0x7fffffff),
    (0x4f7fffff, 0xffffff00, 0x7fffffff), (0x4f800000, 0xffffffff, 0x7fffffff),
    (0xceffffff, 0, 0x80000080), (0xcf000000, 0, 0x80000000), (0xcf000001, 0, 0x80000000),
    (0x7f7fffff, 0xffffffff, 0x7fffffff), (0xff7fffff, 0, 0x80000000),
)


def truncate_word(bits, low, high):
    value, = struct.unpack("<f", struct.pack("<I", bits))
    return 0 if math.isnan(value) else int(min(high, max(low, value))) & 0xffffffff


def check_conversion_readback(host, backend):
    helpers = (Path(__file__).resolve().parents[1] / "src/ffx_float_to_int.hlsli").read_text()
    inputs = ", ".join(f"0x{bits:08x}u" for bits, _, _ in CONVERSIONS)
    unsigned = alu("v_cvt_u32_f32_e32", ["v1", "v0"], "")
    signed = alu("v_cvt_i32_f32_e32", ["v2", "v0"], "")
    shader = f"""{helpers}
RWStructuredBuffer<uint> outWords : register(u0);
static const uint inputs[{len(CONVERSIONS)}] = {{{inputs}}};
[numthreads(1,1,1)] void main(uint3 group : SV_GroupID) {{
    uint v0 = inputs[group.x], v1, v2;
    {unsigned}
    {signed}
    outWords[2 * group.x] = v1;
    outWords[2 * group.x + 1] = v2;
}}
"""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "convert.hlsl"
        source.write_text(shader, encoding="ascii")
        output = subprocess.check_output([host, source, backend, str(len(CONVERSIONS)), "2"], text=True)
    adapter, *rows = output.splitlines()
    print(adapter)
    assert len(rows) == len(CONVERSIONS)
    for (bits, u, i), row in zip(CONVERSIONS, rows):
        actual = tuple(map(int, row.split()))
        assert actual == (u, i), (hex(bits), actual, (u, i))
    print(f"{len(rows)} signed/unsigned pairs matched")


def check_immediate_conversion(compiler, renderer, backend):
    helpers = (Path(__file__).resolve().parents[1] / "src/ffx_float_to_int.hlsli").read_text()
    unsigned = alu("v_cvt_u32_f32_e32", ["v1", "0x7f800000"], "")
    signed = alu("v_cvt_i32_f32_e32", ["v2", "0x7f800000"], "")
    shader = f"""{helpers}
RWByteAddressBuffer output : register(u0);
[RootSignature("SRV(t0), UAV(u0), RootConstants(num32BitConstants=16,b0)")]
[numthreads(1,1,1)] void main(uint3 id : SV_DispatchThreadID) {{
    if (id.x != 0) return;
    uint v1, v2;
    {unsigned}
    {signed}
    output.Store2(0, uint2(v1, v2));
}}
"""
    with tempfile.TemporaryDirectory() as tmp:
        source, binary = Path(tmp) / "immediate.hlsl", Path(tmp) / "immediate.cso"
        source.write_text(shader, encoding="ascii")
        subprocess.run([compiler, "-T", "cs_6_0", "-E", "main", "-Fo", binary, source], check=True)
        subprocess.run([renderer, backend, "--ffx-immediate-conversion", binary], check=True)


def eval_generated(shader, init):
    env = {f"s{i}": 0 for i in range(32)}
    env.update({f"v{i}": 0 for i in range(32)})
    env.update(
        scc=0, exec_lo=1, bfe_u=bfe_u_hlsl, bfe_i=bfe_i_hlsl,
        asint=asint, min=min, max=max,
        reversebits=lambda x: int(f"{x & 0xffffffff:032b}"[::-1], 2),
        mul_high=lambda a, b: ((a & 0xffffffff) * (b & 0xffffffff)) >> 32,
        cvt_i32_f32=lambda bits: truncate_word(bits, -(1 << 31), (1 << 31) - 1),
        cvt_u32_f32=lambda bits: truncate_word(bits, 0, (1 << 32) - 1),
        **init,
    )
    for raw in shader.splitlines():
        if not raw.startswith("    "):
            continue
        line = raw.strip()
        if line.startswith("if (exec_lo) { ") and line.endswith(" }"):
            line = line[len("if (exec_lo) { "):-2]
        if m := re.fullmatch(r"\{\s*uint2 t=uint2\(([^,]+),([^)]+)\);\s*(\w+)=t\.x;\s*(\w+)=t\.y;\s*\}", line):
            a_expr, b_expr, dst_lo, dst_hi = m.groups()
            a_val = int(eval(re.sub(r"\b(0x[0-9a-fA-F]+|\d+)u\b", r"\1", a_expr), {"__builtins__": {}}, env)) & 0xffffffff
            b_val = int(eval(re.sub(r"\b(0x[0-9a-fA-F]+|\d+)u\b", r"\1", b_expr), {"__builtins__": {}}, env)) & 0xffffffff
            env[dst_lo], env[dst_hi] = a_val, b_val
            continue
        for part in line.split(";"):
            part = part.strip()
            if not part or "," in part.split("=", 1)[0]:
                continue
            lhs, rhs = (x.strip() for x in part.split("=", 1))
            py_rhs = re.sub(r"\b(0x[0-9a-fA-F]+|\d+)u\b", r"\1", rhs)
            if m := re.fullmatch(r"(s\w+)\((.+),scc\)", py_rhs):
                fn, arg_str = m.groups()
                fn_args = [int(eval(a.strip(), {"__builtins__": {}}, env)) for a in arg_str.split(",")]
                val, new_scc = SALU_HELPERS[fn](*fn_args)
                env["scc"] = new_scc & 0xffffffff
            elif "?" in py_rhs:
                cond, rest = py_rhs.split("?", 1)
                t_val, f_val = rest.split(":", 1)
                val = eval(t_val, {"__builtins__": {}}, env) if eval(cond, {"__builtins__": {}}, env) else eval(f_val, {"__builtins__": {}}, env)
            else:
                val = int(eval(py_rhs, {"__builtins__": {}}, env))
            env[lhs] = val & 0xffffffff
    return env


def check_bfe(assembler, objcopy, library):
    hlsli = (Path(__file__).resolve().parent / "ffx_dispatch_io.hlsli").read_text(encoding="ascii")
    assert "0xffffffffu >> ((32u - count) & 31u)" in hlsli
    assert "asint(uint(shifted) << shift) >> shift" in hlsli
    for src in (0, 1, 0x12345678, 0x7000000f, 0x8000000f, 0x00000080, 0xffffffff):
        for offset in (0, 1, 4, 16, 24, 28, 31, 36):
            for width in (0, 1, 4, 8, 16, 31, 32, 40, 127):
                assert bfe_u_hlsl(src, offset, width & 31) == rdna_bfe(src, offset, width & 31, False)
                assert bfe_i_hlsl(src, offset, width & 31) == rdna_bfe(src, offset, width & 31, True)
                assert bfe_u_hlsl(src, offset, width & 127) == rdna_bfe(src, offset, width & 127, False)
                assert bfe_i_hlsl(src, offset, width & 127) == rdna_bfe(src, offset, width & 127, True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source, obj, binary = (root / ("bfe." + ext) for ext in ("s", "o", "bin"))
        source.write_text("v_bfe_u32 v4, v0, 28, 8\n"
                          "v_bfe_u32 v5, v0, v1, v2\n"
                          "v_bfe_i32 v6, v0, 28, 8\n"
                          "v_bfe_i32 v7, v0, v1, v2\n"
                          "s_bfe_u32 s4, s0, 0x40200004\n"
                          "s_bfe_u32 s5, s0, s1\n"
                          "v_bfe_u32 v11, v0, v1, v2\n"
                          "v_cndmask_b32_e64 v8, v1, v2, src_scc\n"
                          "s_cselect_b32 s9, s2, s3\n"
                          "s_bfe_i32 s6, s0, 0x8001c\n"
                          "v_cndmask_b32_e64 v9, v1, v2, src_scc\n"
                          "s_bfe_i32 s7, s0, s1\n"
                          "s_cselect_b32 s10, s2, s3\n"
                          "s_bfe_u32 s8, s0, -1\n"
                          "s_endpgm\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj",
                        source, "-o", obj], check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
        code = binary.read_bytes()
        scc_src, scc_obj, scc_bin = (root / ("bfe_scc." + ext) for ext in ("s", "o", "bin"))
        scc_src.write_text("s_cmp_eq_i32 s0, s11\n"
                           "s_bfe_u32 s4, s0, s1\n"
                           "v_cndmask_b32_e64 v8, v1, v2, src_scc\n"
                           "s_cselect_b32 s9, s2, s3\n"
                           "s_cmp_lg_i32 s0, s11\n"
                           "s_bfe_i32 s6, s0, s1\n"
                           "v_cndmask_b32_e64 v9, v1, v2, src_scc\n"
                           "s_cselect_b32 s10, s2, s3\n"
                           "s_endpgm\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj",
                        scc_src, "-o", scc_obj], check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", scc_obj, scc_bin], check=True)
        scc_code = scc_bin.read_bytes()
    instructions = disassemble(code, library, offsets=True)
    expected = (
        "v4 = bfe_u(v0,0x1cu,(0x8u&31u));",
        "v5 = bfe_u(v0,v1,(v2&31u));",
        "v6 = bfe_i(v0,0x1cu,(0x8u&31u));",
        "v7 = bfe_i(v0,v1,(v2&31u));",
        "s4 = bfe_u(s0,0x40200004u,((0x40200004u>>16)&127u)); scc = s4 != 0u;",
        "s5 = bfe_u(s0,s1,((s1>>16)&127u)); scc = s5 != 0u;",
        "v8 = scc?v2:v1;",
        "s9 = scc?s2:s3;",
        "s6 = bfe_i(s0,0x8001cu,((0x8001cu>>16)&127u)); scc = s6 != 0u;",
        "v9 = scc?v2:v1;",
        "s7 = bfe_i(s0,s1,((s1>>16)&127u)); scc = s7 != 0u;",
        "s10 = scc?s2:s3;",
        "s8 = bfe_u(s0,0xffffffffu,((0xffffffffu>>16)&127u)); scc = s8 != 0u;",
    )
    for shader in (translate("rcas", instructions, code), predecessor("pass25", instructions, b"")):
        for line in expected:
            assert line in shader
        for v_line in expected[:4]:
            assert v_line + " scc" not in shader
        # Vector BFE between s_bfe_u32 and SCC consumers must not clobber SCC.
        zero_field = eval_generated(shader, dict(s0=0x0000000f, s1=0x00040004, v0=0xff, v1=1, v2=4, s2=22, s3=33))
        assert (zero_field["s5"], zero_field["v11"], zero_field["v8"], zero_field["s9"]) == (0, 0xf, 1, 33)
        nonzero_field = eval_generated(shader, dict(s0=0x800000f0, s1=0x00040004, v0=0, v1=0, v2=32, s2=22, s3=33))
        assert (nonzero_field["s5"], nonzero_field["v11"], nonzero_field["v8"], nonzero_field["s9"]) == (0xf, 0, 32, 22)
        assert (nonzero_field["s6"], nonzero_field["v9"]) == ((-8) & 0xffffffff, 32)

    scc_ins = disassemble(scc_code, library, offsets=True)
    scc_hlsl = translate("rcas", scc_ins, scc_code)
    # Zero extract after s_cmp_eq_i32 (scc=1) must clear SCC before consumers run.
    cleared = eval_generated(scc_hlsl, dict(s0=0x0000000f, s11=0x0000000f, s1=0x00040004, v1=101, v2=202, s2=303, s3=404))
    assert (cleared["s4"], cleared["v8"], cleared["s9"]) == (0, 101, 404)
    assert (cleared["s6"], cleared["v9"], cleared["s10"]) == (0, 101, 404)
    # Width 0 after s_cmp_eq_i32 (scc=1) also clears SCC to 0.
    width_zero = eval_generated(scc_hlsl, dict(s0=0xffffffff, s11=0xffffffff, s1=0x00000004, v1=101, v2=202, s2=303, s3=404))
    assert (width_zero["s4"], width_zero["v8"], width_zero["s9"]) == (0, 101, 404)
    # Nonzero signed/unsigned extracts after s_cmp_lg_i32 (scc=0) set SCC to 1.
    set_neg = eval_generated(scc_hlsl, dict(s0=0x8000000f, s11=0x8000000f, s1=0x0008001c, v1=101, v2=202, s2=303, s3=404))
    assert (set_neg["s4"], set_neg["v8"], set_neg["s9"]) == (8, 202, 303)
    assert (set_neg["s6"], set_neg["v9"], set_neg["s10"]) == ((-8) & 0xffffffff, 202, 303)


def check_salu_sopk_and_scc(assembler, objcopy, library):
    hlsli = (Path(__file__).resolve().parent / "ffx_dispatch_io.hlsli").read_text(encoding="ascii")
    for helper in SALU_HELPERS:
        assert f"uint {helper}(" in hlsli

    assert simm16("0") == 0 and simm16("0x7fff") == 0x7fff
    assert simm16("0x8000") == 0xffff8000 and simm16("0xffff") == 0xffffffff
    assert simm16("-1") == 0xffffffff and simm16("-32768") == 0xffff8000
    for bad in ("0x10000", "-32769"):
        try:
            simm16(bad)
            raise AssertionError(f"Accepted out-of-range SOPK immediate {bad}")
        except ValueError:
            pass
    try:
        alu("s_movk_i32", ["s0", "0x10000"], "")
        raise AssertionError("Accepted out-of-range SOPK immediate in alu()")
    except ValueError:
        pass

    edges = (0, 1, 2, 0x0fffffff, 0x10000000, 0x7ffffffe, 0x7fffffff,
             0x80000000, 0x80000001, 0xffff0000, 0xfffffffe, 0xffffffff)
    for a in edges:
        abs_ref = abs(asint(a)) & 0xffffffff
        assert sabs_i_hlsl(a) == (abs_ref, int(abs_ref != 0))
        for b in edges:
            assert sadd_u_hlsl(a, b) == ((a + b) & 0xffffffff, int(a + b >= (1 << 32)))
            wide_shift = (a << 4) + b
            assert slshl4_add_u_hlsl(a, b) == (wide_shift & 0xffffffff, int(wide_shift >= (1 << 32)))
            sum_i = asint(a) + asint(b)
            assert sadd_i_hlsl(a, b) == (sum_i & 0xffffffff, int(not (-0x80000000 <= sum_i <= 0x7fffffff)))
            diff_i = asint(a) - asint(b)
            assert ssub_i_hlsl(a, b) == (diff_i & 0xffffffff, int(not (-0x80000000 <= diff_i <= 0x7fffffff)))
            assert smin_u_hlsl(a, b) == (min(a, b), int(a < b))
            assert smax_u_hlsl(a, b) == (max(a, b), int(a > b))
            assert smin_i_hlsl(a, b) == ((a if asint(a) < asint(b) else b), int(asint(a) < asint(b)))
            assert smax_i_hlsl(a, b) == ((a if asint(a) > asint(b) else b), int(asint(a) > asint(b)))

    def assemble(text):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, obj, out = (root / ("salu." + ext) for ext in ("s", "o", "bin"))
            src.write_text(text, encoding="ascii")
            subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj",
                            src, "-o", obj], check=True)
            subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, out], check=True)
            code = out.read_bytes()
        return code, disassemble(code, library, offsets=True)

    # Non-SCC-writing scalar instructions (including negative SOPK immediates)
    # and vector ALU instructions must preserve both scc=1 and scc=0.
    preserve_code, preserve_ins = assemble(
        "s_cmp_eq_i32 s0, s1\n"
        "s_movk_i32 s4, -1\n"
        "s_movk_i32 s5, -32768\n"
        "s_movk_i32 s6, 0\n"
        "s_mulk_i32 s7, -3\n"
        "s_mov_b32 s10, s2\n"
        "s_mov_b64 s[12:13], s[2:3]\n"
        "s_mul_i32 s16, s2, s3\n"
        "s_mul_hi_u32 s17, s2, s3\n"
        "s_brev_b32 s18, s2\n"
        "v_add_nc_u32 v4, v1, v2\n"
        "v_min_i32 v5, v1, v2\n"
        "v_xor_b32 v6, v1, v1\n"
        "s_cselect_b32 s19, s2, s3\n"
        "v_cndmask_b32_e64 v7, v1, v2, src_scc\n"
        "s_endpgm\n"
    )
    for shader in (translate("rcas", preserve_ins, preserve_code),
                   predecessor("pass25", preserve_ins, b"")):
        assert "s4 = 0xffffffffu;" in shader and "s5 = 0xffff8000u;" in shader
        assert "s7 = s7*0xfffffffdu;" in shader
        kept_one = eval_generated(shader, dict(s0=9, s1=9, s2=0x80000003, s3=2, s7=0x10002, v1=11, v2=22))
        assert (kept_one["s4"], kept_one["s5"], kept_one["s6"]) == (0xffffffff, 0xffff8000, 0)
        assert kept_one["s7"] == (0x10002 * -3) & 0xffffffff
        assert (kept_one["s12"], kept_one["s13"], kept_one["s17"], kept_one["s18"]) == (0x80000003, 2, 1, 0xc0000001)
        assert (kept_one["s19"], kept_one["v7"], kept_one["scc"]) == (0x80000003, 22, 1)
        kept_zero = eval_generated(shader, dict(s0=9, s1=10, s2=0x80000003, s3=2, s7=0, v1=11, v2=22))
        assert (kept_zero["s7"], kept_zero["s19"], kept_zero["v7"], kept_zero["scc"]) == (0, 2, 11, 0)

    # SCC-writing scalar instructions must both clear stale scc=1 and set scc=1
    # according to carry, signed overflow, relational winner, or nonzero result,
    # including when the destination aliases a source SGPR.
    scc_code, scc_ins = assemble(
        "s_cmp_eq_i32 s31, 0\n"
        "s_addk_i32 s4, -2\n"
        "s_cselect_b32 s16, s2, s3\n"
        "s_cmp_eq_i32 s31, 0\n"
        "s_add_u32 s5, s5, s1\n"
        "s_cselect_b32 s17, s2, s3\n"
        "s_cmp_eq_i32 s31, 0\n"
        "s_lshl4_add_u32 s6, s0, s1\n"
        "s_cselect_b32 s18, s2, s3\n"
        "s_cmp_eq_i32 s31, 0\n"
        "s_sub_i32 s7, s7, s1\n"
        "s_cselect_b32 s19, s2, s3\n"
        "s_cmp_eq_i32 s31, 0\n"
        "s_min_u32 s20, s10, s11\n"
        "s_cselect_b32 s21, s2, s3\n"
        "s_cmp_lg_i32 s31, 0\n"
        "s_min_i32 s22, s10, s11\n"
        "s_cselect_b32 s23, s2, s3\n"
        "s_cmp_eq_i32 s31, 0\n"
        "s_max_u32 s24, s10, s10\n"
        "s_cselect_b32 s25, s2, s3\n"
        "s_cmp_eq_i32 s31, 0\n"
        "s_abs_i32 s26, s12\n"
        "s_cselect_b32 s27, s2, s3\n"
        "s_cmp_lg_i32 s31, 0\n"
        "s_lshl_b32 s28, s13, 36\n"
        "v_cndmask_b32_e64 v8, v1, v2, src_scc\n"
        "s_cmp_eq_i32 s31, 0\n"
        "s_and_b32 s29, s13, 0\n"
        "s_cselect_b32 s30, s2, s3\n"
        "s_endpgm\n"
    )
    for shader in (translate("rcas", scc_ins, scc_code),
                   predecessor("pass25", scc_ins, b"")):
        # With s31=0, s_cmp_eq_i32 presets scc=1 and s_cmp_lg_i32 presets scc=0,
        # verifying both 1->0 clearing and 0->1 setting on non-overflowing inputs.
        no_ovf = eval_generated(shader, dict(
            s0=0x01000000, s1=1, s2=111, s3=222,
            s4=0x10001, s5=5, s7=0,
            s10=0xffffffff, s11=1, s12=0, s13=3, s31=0, v1=10, v2=20,
        ))
        assert (no_ovf["s4"], no_ovf["s16"]) == (0xffff, 222)
        assert (no_ovf["s5"], no_ovf["s17"]) == (6, 222)
        assert (no_ovf["s6"], no_ovf["s18"]) == (0x10000001, 222)
        assert (no_ovf["s7"], no_ovf["s19"]) == (0xffffffff, 222)
        assert (no_ovf["s20"], no_ovf["s21"]) == (1, 222)
        assert (no_ovf["s22"], no_ovf["s23"]) == (0xffffffff, 111)
        assert (no_ovf["s24"], no_ovf["s25"]) == (0xffffffff, 222)
        assert (no_ovf["s26"], no_ovf["s27"]) == (0, 222)
        assert (no_ovf["s28"], no_ovf["v8"]) == (48, 20)
        assert (no_ovf["s29"], no_ovf["s30"]) == (0, 222)

        # With s31=1, s_cmp_eq_i32 presets scc=0 and s_cmp_lg_i32 presets scc=1,
        # verifying 0->1 setting on signed/unsigned overflow (including s_lshl4_add_u32
        # shifting a nonzero upper nibble out of 32 bits and s_abs_i32 on INT_MIN)
        # and 1->0 clearing when s_lshl_b32 produces zero.
        ovf = eval_generated(shader, dict(
            s0=0x10000000, s1=1, s2=111, s3=222,
            s4=0x80000000, s5=0xffffffff, s7=0x80000000,
            s10=1, s11=5, s12=0x80000000, s13=0, s31=1, v1=10, v2=20,
        ))
        assert (ovf["s4"], ovf["s16"]) == (0x7ffffffe, 111)
        assert (ovf["s5"], ovf["s17"]) == (0, 111)
        assert (ovf["s6"], ovf["s18"]) == (1, 111)
        assert (ovf["s7"], ovf["s19"]) == (0x7fffffff, 111)
        assert (ovf["s20"], ovf["s21"]) == (1, 111)
        assert (ovf["s22"], ovf["s23"]) == (1, 111)
        assert (ovf["s26"], ovf["s27"]) == (0x80000000, 111)
        assert (ovf["s28"], ovf["v8"]) == (0, 10)

    # Scratch CPU reference must sign-extend SOPK immediates identically to predecessor().
    ref_code, ref_ins = assemble(
        "buffer_load_dwordx4 v[0:3], v4, s[8:11], 0 offen\n"
        "s_movk_i32 s4, -16\n"
        "s_addk_i32 s4, -2\n"
        "s_mulk_i32 s4, -3\n"
        "v_xor_b32 v0, s4, v0\n"
        "s_movk_i32 s5, -1\n"
        "s_addk_i32 s5, 0x7fff\n"
        "v_xor_b32 v1, s5, v1\n"
        "buffer_store_dwordx4 v[0:3], v4, s[8:11], 0 offen\n"
        "s_endpgm\n"
    )
    taps = [[0x10000000, 0xabcdef00, 3, 4]]
    assert network(ref_ins, taps, b"", 24) == [0x10000000 ^ 54, 0xabcdef00 ^ 0x7ffe, 3, 4]


def check_modifiers(assembler, objcopy, library):
    def assemble_and_translate(body):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, obj, binary = (root / ("mod." + ext) for ext in ("s", "o", "bin"))
            source.write_text(f"{body}\ns_endpgm\n", encoding="ascii")
            subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj",
                            source, "-o", obj], check=True)
            subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
            code = binary.read_bytes()
        instructions = disassemble(code, library, offsets=True)
        return translate("consumer", instructions, code)

    mul2 = assemble_and_translate("v_mul_f32_e64 v0, v1, v2 mul:2")
    assert "2.0*(" in mul2
    pk_clamp = assemble_and_translate("v_pk_add_f16 v0, v1, v2 op_sel:[1,0] clamp")
    assert "saturate(" in pk_clamp
    for bad_asm in (
        "v_add_f32_e64 v0, v1, v2 clamp",
        "v_mul_f32_e64 v0, v1, v2 mul:4",
        "v_mul_f32_e64 v0, v1, v2 div:2",
        "v_mul_f32_e64 v0, v1, v2 clamp mul:2",
        "v_add_nc_u32_e64 v0, v1, v2 clamp",
        "v_pk_add_u16 v0, v1, v2 clamp",
    ):
        try:
            assemble_and_translate(bad_asm)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected modifier rejection for: {bad_asm}")
    for bad_line in (
        "v_pk_add_f16 v0, v1, v2 op_sel:[1,0,1]",
        "v_pk_add_f16 v0, v1, v2 mul:2",
        "v_pk_add_f16 v0, v1, v2 clamp clamp",
    ):
        try:
            translate("consumer", [(0, bad_line), (8, "s_endpgm")], b"\0" * 12)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected packed modifier rejection for: {bad_line}")


def main(assembler, objcopy, library):
    # A signed i8 dot product, replicated low half, clamp and byte insert
    # have independent integer answers on these source-owned test operands.
    fixture = ["buffer_load_dwordx4 v[0:3], v4, s[8:11], 0 offen",
               "v_dot4_i32_i8 v0, v0, 0x01010101, 7",
               "v_dot4_i32_i8 v1, v1, -6, 0 op_sel_hi:[1,0,1]",
               "v_cvt_pk_u8_f32 v2, v2, 2, v3",
               "buffer_store_dwordx4 v[0:3], v4, s[8:11], 0 offen"]
    operands = [[0x7f0080ff, 0x01020304, 0x43960000, 0x12345678]]
    assert network(list(enumerate(fixture)), operands, b"", 24) == [5, (-40)&0xffffffff, 0x12ff5678, 0x12345678]
    # Literal low half decrements x; its zero high half must leave y unchanged.
    # LLVM 15 prints this literal as -1 when disassembling a packed add.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source, obj, binary = (root / ("fixture." + ext) for ext in ("s", "o", "bin"))
        source.write_text("v_pk_add_u16 v4, v0, 1\n"
                          "image_load v[5:6], v4, s[24:31] dmask:0x7 dim:SQ_RSRC_IMG_2D unorm a16 d16\n"
                          "v_cvt_u32_f32_e32 v8, v7\nv_cvt_i32_f32_e32 v9, v7\n"
                          "s_endpgm\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj",
                        source, "-o", obj], check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
        assembled = binary.read_bytes()
    # llvm-mc canonicalizes a spelling of 0xffff to the short inline -1
    # form. Select the VOP3P literal source explicitly and append its DWORD.
    operands, = struct.unpack_from("<I", assembled, 4)
    assert (operands >> 9) & 511 == 129
    literal_src1 = (operands & ~(511 << 9)) | (255 << 9)
    code = assembled[:4] + struct.pack("<II", literal_src1, 0xffff) + assembled[8:]
    instructions = disassemble(code, library, offsets=True)
    hlsl = translate("rcas", instructions, code)
    assert "0xffffu >> 16" in hlsl and "0xffffffffu" not in hlsl
    assert "load16(uint2(v4 & 65535u, v4>>16))" in hlsl
    conversions = [(pc, line) for pc, line in instructions if line.startswith(("v_cvt_u32_f32", "v_cvt_i32_f32"))]
    assert len(conversions) == 2
    for shader in (translate("rcas", conversions, code), predecessor("pass25", conversions, b"")):
        for bits, unsigned, signed in CONVERSIONS:
            env = eval_generated(shader, {"v7": bits})
            assert (env["v8"], env["v9"]) == (unsigned, signed), hex(bits)
    check_bfe(assembler, objcopy, library)
    check_salu_sopk_and_scc(assembler, objcopy, library)
    check_modifiers(assembler, objcopy, library)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--immediate"]:
        check_immediate_conversion(*sys.argv[2:])
    elif sys.argv[1:2] == ["--readback"]:
        check_conversion_readback(*sys.argv[2:])
    else:
        main(*sys.argv[1:])
