"""Draw family `unsampled`: programs bound without a texture or sampler (lower(sampler=None)).

A constant-buffer color with an RG or RGBA compressed export (from R0Y00/Xbox2Windows#480 by Royoo), and attr0
interpolated at the entry mask in all four components (from R0Y00/Xbox2Windows#484 by Royoo).
"""
import struct
import subprocess

from .common import assembly, lower, must_reject


def buffer_color(rg):
    # A copied low table address and an explicit zero high word.
    tail = "off, off" if rg else "v26, v26"
    return [
        "s_mov_b32 s30, s9", "s_mov_b32 s31, 0",
        "s_load_dwordx4 s[12:15], s[30:31], null", "s_waitcnt lgkmcnt(0)",
        "s_buffer_load_dwordx4 s[4:7], s[12:15], 0x10", "s_waitcnt lgkmcnt(0)",
        "v_mov_b32_e32 v20, s7", "v_mov_b32_e32 v21, s4",
        "v_cvt_pkrtz_f16_f32_e32 v25, v20, v21",
        "v_cvt_pkrtz_f16_f32_e32 v26, v21, v20",
        f"exp mrt0 v25, v25, {tail} done compr vm", "s_endpgm",
    ]


def translate_buffer_color(instructions):
    return lower(instructions, 9, 24, None, 0)


def attribute_color(rg):
    code = ["s_mov_b32 s30, s14", "s_mov_b32 m0, s30"]
    for phase in (1, 2):
        for i, channel in enumerate("wzxy"):
            code.append(f"v_interp_p{phase}_f32_e32 v{8+i}, v{phase-1}, attr0.{channel}")
    code.extend(["v_cvt_pkrtz_f16_f32_e32 v12, v8, v9", "v_cvt_pkrtz_f16_f32_e32 v13, v10, v11"])
    tail = "off, off" if rg else "v13, v13"
    return code + [f"exp mrt0 v12, v12, {tail} done compr vm", "s_endpgm"]


def translate_attribute(code):
    return lower(code, 8, 14, None)


def controls(directory):
    program = buffer_color(True)
    source = translate_buffer_color(program)
    assert "SamplerState" not in source and "Texture2D" not in source, source
    # The RG export is a two-component SV_Target0 under a write mask of R and G (forms/exp.py).
    assert "float2 target0 : SV_Target0" in source and "SV_Target0 0x3" in source, source
    assert "float4 main(" in translate_buffer_color(buffer_color(False))
    must_reject(lambda p: lower(p, 8, 24, None, 0), program)  # table address in another SGPR
    must_reject(lambda p: lower(p, 9, 24, None, 32), program)  # constant descriptor elsewhere
    must_reject(lambda p: lower(p, 9, 24, None, 0, second_texture_offset=32), program)
    must_reject(lambda p: lower(p, 9, 24, [0] * 4, 0), program)  # a sampler bound: a texture at 0 overlaps
    must_reject(lambda p: lower(p, 20, 24, None), assembly(False))  # a sample without a sampler
    must_reject(translate_buffer_color, [s for s in program if s != "s_waitcnt lgkmcnt(0)"])
    must_reject(translate_buffer_color, [s.replace("off, off", "off, v26") for s in program])
    for rg in (False, True):
        code = attribute_color(rg)
        source = translate_attribute(code)
        assert "main(float4 uv : TEXCOORD0" in source and "SamplerState" not in source, source
        must_reject(lambda: lower(code, 14, 8, None))  # m0 holds another register than the interpolation base
        must_reject(lambda: lower(code, 8, 14, [1, 2, 3, 4]))  # a sampler bound and no sample taken
        must_reject(translate_attribute, [s.replace("v8, v1, attr0.w", "v8, v1, attr0.z") for s in code])
        must_reject(translate_attribute, [s.replace("v9, v0, attr0.z", "v9, v1, attr0.z") for s in code])
        # p2 of another attribute than its p1 (attr1 itself is interpolated as any other: family interp_attrs).
        must_reject(translate_attribute, [s.replace("v1, attr0.z", "v1, attr1.z") for s in code])
        # p1 at the entry mask cannot pair with p2 in whole-quad mode.
        p2 = next(n for n, s in enumerate(code) if s.startswith("v_interp_p2"))
        must_reject(translate_attribute, code[:p2] + ["s_wqm_b64 exec, exec"] + code[p2:])
    # In whole-quad mode every component is a helper-lane value an implicit-level sample may read (family
    # interp_attrs): TEXCOORD0 is then float4.
    wqm = assembly(False)
    source = lower([s.replace("attr0.y", "attr0.z") for s in wqm], 20, 24, [1, 2, 3, 4])
    assert "main(float4 uv : TEXCOORD0" in source and ".Sample(samp, float2(uv.x, alu" in source, source


def binary_fixtures():
    return ([(buffer_color(rg), translate_buffer_color) for rg in (False, True)]
            + [(attribute_color(rg), translate_attribute) for rg in (False, True)])


def check_buffer_color_draw(directory, compiler, renderer, backend):
    source, shader, case = (directory / name for name in ("buffer.hlsl", "buffer.cso", "buffer.case"))
    for rg in (False, True):
        source.write_text(translate_buffer_color(buffer_color(rg)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case-rg" if rg else "--check-pixel-case", shader, case]
        for red, green in ((0.25, 0.75), (-0.5, 0.125)):
            constants = bytearray(256)
            struct.pack_into("<4f", constants, 16, green, 2, 3, red)
            blue, alpha = (-1, -1) if rg else (green, red)
            expected = struct.pack("<4f", red, green, blue, alpha) * 64
            case.write_bytes(constants + expected)
            result = subprocess.run(draw)
            if result.returncode:
                return result.returncode
        struct.pack_into("<f", constants, 28, green)
        case.write_bytes(constants + expected)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError("Wrong buffer color escaped detection")
    return 0


def check_attribute_draw(directory, compiler, renderer, backend):
    for rg in (False, True):
        code = attribute_color(rg)
        src, cso, case = [directory / name for name in ("color.hlsl", "color.cso", "color.case")]
        src.write_text(translate_attribute(code), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", cso, src], check=True)
        cmd = [renderer, backend, "--check-pixel-attribute-rg" if rg else "--check-pixel-attribute", cso, case]
        data = bytearray(256)
        for y in range(32):
            for x in range(32):
                u, v = (x + 0.5) / 32, (y + 0.5) / 32
                data += struct.pack("<4f", 1-v, 0.25 + 0.5*u, -1 if rg else u, -1 if rg else v)
        case.write_bytes(data)
        result = subprocess.run(cmd)
        if result.returncode:
            return result.returncode
        # A wrong channel at an interior pixel must be detected.
        struct.pack_into("<f", data, 256 + (9 * 32 + 17) * 16, 0)
        case.write_bytes(data)
        wrong = subprocess.run(cmd, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch x=17 y=9" not in wrong.stderr:
            raise AssertionError("Wrong interpolated channel escaped detection")
    return 0


def draw(directory, compiler, renderer, backend):
    return check_buffer_color_draw(directory, compiler, renderer, backend) or \
        check_attribute_draw(directory, compiler, renderer, backend)
