"""Draw family `bindings`: pixel_aot_check.py draw --family bindings.

Programs bound by a binding description (lower(bindings=PixelBindings(...)), docs/design/pixel-bindings.md) instead
of the fixed contract: descriptor-set pointers in entry SGPRs completed with a high word, several textures, samplers
and constant buffers at any offset of two sets, samplers loaded from memory and an inline one, a push-constant SGPR.
The harness binds the case's textures and constant buffers by slot ('X2WB' section of --check-pixel-case,
tests/pixel_aot_render.cpp). Every texel's result comes from three textures, two constant buffers and a push word,
so each wrong reference below (a texture read through the wrong slot, two textures swapped, a constant word one
offset off, the wrong constant buffer, the push word dropped) changes some texel and must be reported as a mismatch.
"""
import struct
import subprocess

from pixel_aot_ops.bindings import PixelBindings, SET_STRIDE

from .common import half_rtz, lower, must_reject

BINDINGS_MAGIC = 0x42573258  # 'X2WB'

INTERP = [
    "s_mov_b64 s[50:51], exec",
    "s_wqm_b64 exec, exec",
    "s_mov_b32 m0, {interp}",
    "v_interp_p1_f32_e32 v8, v0, attr0.x",
    "v_interp_p1_f32_e32 v9, v0, attr0.y",
    "v_interp_p2_f32_e32 v9, v1, attr0.y",
    "v_interp_p2_f32_e32 v8, v1, attr0.x",
    "s_and_b64 exec, exec, s[50:51]",
]

# Two descriptor sets as RADV passes them (32-bit pointers in s2 and s3, completed with s_movk_i32 0x8000), a push
# constant in s4 and the interpolation base in s5. Set 0: tex (0x00), samp (0x20), samp1 (0x30), tex1 (0x40), the
# constant-buffer V# params (0x60); set 1: tex2 (0x00), the V# params1 (0x20). One s_load_dwordx16 reads tex, samp and
# samp1; tex is sampled through an NSA address.
SETS = [*(line.format(interp="s5") for line in INTERP),
        "s_mov_b32 s20, s2",
        "s_movk_i32 s21, 0x8000",
        "s_mov_b32 s22, s3",
        "s_movk_i32 s23, 0x8000",
        "s_load_dwordx16 s[24:39], s[20:21], null",
        "s_load_dwordx8 s[40:47], s[20:21], 0x40",
        "s_load_dwordx4 s[52:55], s[20:21], 0x60",
        "s_load_dwordx8 s[56:63], s[22:23], null",
        "s_load_dwordx4 s[64:67], s[22:23], 0x20",
        "s_waitcnt lgkmcnt(0)",
        "image_sample v[12:15], [v8, v9], s[24:31], s[32:35] dmask:0xf dim:SQ_RSRC_IMG_2D",
        "image_sample v[20:23], v[8:9], s[40:47], s[36:39] dmask:0xf dim:SQ_RSRC_IMG_2D",
        "image_sample v[24:27], v[8:9], s[56:63], s[32:35] dmask:0xf dim:SQ_RSRC_IMG_2D",
        "s_buffer_load_dword s68, s[52:55], 0x14",
        "s_buffer_load_dword s69, s[64:67], 0x28",
        "s_waitcnt lgkmcnt(0)",
        "s_xor_b32 s68, s68, s69",
        "s_xor_b32 s68, s68, s4",
        "s_waitcnt vmcnt(0)",
        "v_cvt_f32_ubyte0_e32 v15, s68",
        "v_cvt_pkrtz_f16_f32_e32 v16, v12, v21",
        "v_cvt_pkrtz_f16_f32_e32 v17, v26, v15",
        "exp mrt0 v16, v16, v17, v17 done compr vm",
        "s_endpgm"]
SETS_BINDINGS = PixelBindings(
    sgprs={"s2": "descriptors", "s3": "descriptors.1", "s4": "push:0", "s5": "interp"},
    textures={0x00: 0, 0x40: 1, SET_STRIDE + 0x00: 2}, samplers={0: 0x20, 1: 0x30},
    constant_buffers={0x60: 0, SET_STRIDE + 0x20: 1}, push_constants=2)

# One set at s6 completed with a high word of 0 (the description's descriptor_high), the T# of texture slot 3 (tex3,
# t4) at 0x40 through an SGPR offset, sampled twice (the second time at the transposed coordinate) with an inline
# sampler whose words s_mov sets (sampler slot 2), and the constant buffer of slot 3 (params3, b4) at 0x00.
INLINE = [*(line.format(interp="s7") for line in INTERP),
          "s_mov_b32 s20, s6",
          "s_mov_b32 s21, 0",
          "s_mov_b32 s70, 0x40",
          "s_load_dwordx8 s[28:35], s[20:21], s70",
          "s_load_dwordx4 s[44:47], s[20:21], null",
          "s_mov_b32 s40, 1",
          "s_mov_b32 s41, 2",
          "s_mov_b32 s42, 3",
          "s_mov_b32 s43, 4",
          "s_waitcnt lgkmcnt(0)",
          "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
          "image_sample v[20:23], [v9, v8], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
          "s_buffer_load_dwordx2 s[48:49], s[44:47], 0x8",
          "s_waitcnt lgkmcnt(0)",
          "s_waitcnt vmcnt(0)",
          "v_cvt_f32_ubyte1_e32 v15, s49",
          "v_cvt_pkrtz_f16_f32_e32 v16, v12, v21",
          "v_cvt_pkrtz_f16_f32_e32 v17, v14, v15",
          "exp mrt0 v16, v16, v17, v17 done compr vm",
          "s_endpgm"]
INLINE_BINDINGS = PixelBindings(sgprs={"s6": "descriptors", "s7": "interp"}, textures={0x40: 3},
                                samplers={2: (1, 2, 3, 4)}, constant_buffers={0x00: 3}, descriptor_high=0)


def translate_with(description):
    return lambda program: lower(program, bindings=description)


translate_sets = translate_with(SETS_BINDINGS)
translate_inline = translate_with(INLINE_BINDINGS)


def texel(slot, x, y, channel):
    """Byte `channel` of texel (x, y) of the case's texture `slot`: every slot and channel differs."""
    return (37 * x + 11 * y + 53 * slot + 71 * channel + 5) & 0xff


def constant_words(slot):
    state, words = 0x9e3779b9 + slot, []
    for _ in range(64):
        state = (state * 1103515245 + 12345 + slot) & 0xffffffff
        words.append(state ^ (state >> 13))
    return words


CONSTANTS = [constant_words(k) for k in range(4)]  # params, params1, params2 (the push words), params3


def unorm(slot, x, y, channel):
    return half_rtz(texel(slot, x, y, channel) / 255)


def sets_reference(flaw=None):
    rows = []
    for y in range(8):
        for x in range(8):
            r_slot, g_slot, b_slot = {"swapped": (1, 0, 2), "wrong_slot": (0, 1, 1)}.get(flaw, (0, 1, 2))
            c0 = CONSTANTS[0][4 if flaw == "constant_offset" else 5]
            c1 = CONSTANTS[0 if flaw == "constant_buffer" else 1][10]
            push = 0 if flaw == "no_push" else CONSTANTS[2][0]
            rows.append((unorm(r_slot, x, y, 0), unorm(g_slot, x, y, 1), unorm(b_slot, x, y, 2),
                         float((c0 ^ c1 ^ push) & 0xff)))
    return rows


def inline_reference(flaw=None):
    rows = []
    slot = 0 if flaw == "wrong_slot" else 3
    for y in range(8):
        for x in range(8):
            gx, gy = (x, y) if flaw == "untransposed" else (y, x)
            word = CONSTANTS[0 if flaw == "constant_buffer" else 3][2 if flaw == "constant_offset" else 3]
            rows.append((unorm(slot, x, y, 0), unorm(slot, gx, gy, 1), unorm(slot, x, y, 2), float((word >> 8) & 0xff)))
    return rows


SETS_FLAWS = ("swapped", "wrong_slot", "constant_offset", "constant_buffer", "no_push")
INLINE_FLAWS = ("wrong_slot", "untransposed", "constant_offset", "constant_buffer")


def write_bindings_case(path, rows, textures=4):
    """A --check-pixel-case case: params (b0), the 64 expected colors, then the 'X2WB' section with `textures`
    textures (slots 0..textures-1) and params1..params3."""
    data = bytearray(struct.pack("<64I", *CONSTANTS[0]))
    for row in rows:
        data += struct.pack("<4f", *row)
    data += struct.pack("<4I", BINDINGS_MAGIC, textures, 3, 0)
    for slot in range(textures):
        data += bytes(texel(slot, x, y, c) for y in range(8) for x in range(8) for c in range(4))
    for k in (1, 2, 3):
        data += struct.pack("<64I", *CONSTANTS[k])
    path.write_bytes(data)


DRAWS = (("sets", SETS, translate_sets, sets_reference, SETS_FLAWS),
         ("inline", INLINE, translate_inline, inline_reference, INLINE_FLAWS))


def draw(directory, compiler, renderer, backend):
    case = directory / "bindings.case"
    for name, program, translator, reference, flaws in DRAWS:
        source, shader = directory / f"bindings_{name}.hlsl", directory / f"bindings_{name}.cso"
        source.write_text(translator(program), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        command = [renderer, backend, "--check-pixel-case", shader, case]
        write_bindings_case(case, reference())
        subprocess.run(command, check=True)
        for flaw in flaws:
            assert reference(flaw) != reference(), (name, flaw)
            write_bindings_case(case, reference(flaw))
            wrong = subprocess.run(command, capture_output=True, text=True)
            if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
                raise AssertionError(f"bindings {name}: the {flaw} reference escaped detection")


def refuses(reason, program, description, **kwargs):
    """lower() refuses the program under the description with a message that starts with reason."""
    try:
        lower(program, bindings=description, **kwargs)
    except ValueError as error:
        if not str(error).startswith(reason):
            raise AssertionError(f"Expected refusal {reason!r}, got {error!r}") from error
        return
    raise AssertionError(f"Accepted, expected refusal {reason!r}")


def replaced(program, old, new):
    assert old in program, old
    return [new if line == old else line for line in program]


def described(base, **changes):
    fields = {name: getattr(base, name) for name in ("sgprs", "textures", "samplers", "constant_buffers",
                                                        "push_constants", "buffers", "storage_images",
                                                        "descriptor_high")}
    return PixelBindings(**{**fields, **changes})


def controls(directory):
    import corpus_translate

    sets, inline = translate_sets(SETS), translate_inline(INLINE)
    for text in ("tex.Sample(samp, float2(uv.x, uv.y))", "tex1.Sample(samp1, float2(uv.x, uv.y))",
                 "tex2.Sample(samp, float2(uv.x, uv.y))", "params[1].y", "params1[2].z", "params2[0].x",
                 "Texture2D<float4> tex2 : register(t3);", "SamplerState samp1 : register(s1);",
                 "cbuffer Constants2 : register(b3) { uint4 params2[16]; };"):
        assert text in sets, text
    for text in ("tex3.Sample(samp2, float2(uv.x, uv.y))", "tex3.Sample(samp2, float2(uv.y, uv.x))", "params3[0].w",
                 "Texture2D<float4> tex3 : register(t4);", "SamplerState samp2 : register(s2);"):
        assert text in inline, text
    assert "register(t0)" not in inline and "register(s0)" not in inline
    # The corpus derivation (tools/corpus_translate.py) reads the same description off the RADV-shaped program.
    assert corpus_translate.derive_bindings(SETS) == SETS_BINDINGS, corpus_translate.derive_bindings(SETS).names()
    assert SETS_BINDINGS.names()[:4] == ["s2: descriptors", "s3: descriptors.1", "s4: push:0", "s5: interp"]
    # A descriptor word the description does not declare is refused, wherever the load reaches it.
    refuses("Descriptor table word is not a tracked descriptor", SETS, described(SETS_BINDINGS, samplers={0: 0x20}))
    refuses("Descriptor table word is not a tracked descriptor", SETS,
            described(SETS_BINDINGS, textures={0x00: 0, SET_STRIDE: 2}))
    refuses("Descriptor table word is not a tracked descriptor",
            replaced(SETS, "s_load_dwordx4 s[64:67], s[22:23], 0x20", "s_load_dwordx4 s[64:67], s[22:23], 0x30"),
            SETS_BINDINGS)
    # A pointer completed with another high word, or a set the description does not name.
    refuses("Unresolved descriptor-list pointer", replaced(SETS, "s_movk_i32 s21, 0x8000", "s_movk_i32 s21, 0x7fff"),
            SETS_BINDINGS)
    refuses("Unresolved descriptor-list pointer", SETS, described(SETS_BINDINGS, descriptor_high=0))
    refuses("Unresolved descriptor-list pointer", INLINE, described(INLINE_BINDINGS, descriptor_high=0xffff8000))
    refuses("Unresolved descriptor-list pointer", replaced(SETS, "s_mov_b32 s22, s3", "s_mov_b32 s22, s4"),
            SETS_BINDINGS)
    # An entry SGPR with no role.
    refuses("Read of unset scalar register s4", SETS,
            described(SETS_BINDINGS, sgprs={"s2": "descriptors", "s3": "descriptors.1", "s5": "interp"}))
    # A sampler that is not a declared S#, a constant read through a T#, a read before the loads complete.
    refuses("Unsupported image or sampler binding",
            replaced(SETS, "image_sample v[20:23], v[8:9], s[40:47], s[36:39] dmask:0xf dim:SQ_RSRC_IMG_2D",
                     "image_sample v[20:23], v[8:9], s[40:47], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D"), SETS_BINDINGS)
    refuses("Unresolved constant buffer binding",
            replaced(SETS, "s_buffer_load_dword s69, s[64:67], 0x28", "s_buffer_load_dword s69, s[24:27], 0x28"),
            SETS_BINDINGS)
    refuses("Unsupported image or sampler binding", [line for line in SETS if line != "s_waitcnt lgkmcnt(0)"],
            SETS_BINDINGS)
    refuses("Constant read exceeds binding",
            replaced(SETS, "s_buffer_load_dword s69, s[64:67], 0x28", "s_buffer_load_dword s69, s[64:67], 0x100"),
            SETS_BINDINGS)
    # An SGPR offset that is not a translation-time constant, and inline sampler words that differ.
    refuses("Scalar load offset register must hold a known constant",
            replaced(INLINE, "s_mov_b32 s70, 0x40", "s_mov_b32 s70, s7"), INLINE_BINDINGS)
    refuses("Unsupported image or sampler binding", INLINE, described(INLINE_BINDINGS, samplers={2: (1, 2, 3, 5)}))
    refuses("Unsupported image or sampler binding", INLINE, described(INLINE_BINDINGS, samplers={2: 0x20}))
    # Malformed descriptions.
    refuses("Descriptor-table entries overlap", SETS, described(SETS_BINDINGS, samplers={0: 0x10, 1: 0x30}))
    refuses("Descriptor-table entries overlap", SETS, described(SETS_BINDINGS, constant_buffers={0x60: 0, 0x40: 1}))
    refuses("Invalid texture key or slot", SETS, described(SETS_BINDINGS, textures={0x00: 0, 0x40: 0}))
    refuses("Invalid texture key or slot", SETS, described(SETS_BINDINGS, textures={0x08: 0}))
    refuses("Invalid constant-buffer key or slot", SETS, described(SETS_BINDINGS, push_constants=1))
    refuses("A push-constant SGPR needs a push-constant slot", SETS, described(SETS_BINDINGS, push_constants=None))
    refuses("Unknown entry SGPR role", SETS, described(SETS_BINDINGS, sgprs={"s2": "descriptors.9"}))
    refuses("Entry SGPR role interp is given twice", SETS,
            described(SETS_BINDINGS, sgprs={"s2": "descriptors", "s5": "interp", "s6": "interp"}))
    refuses("A sampler is a descriptor key or four constant words", INLINE,
            described(INLINE_BINDINGS, samplers={2: (1, 2, 3)}))
    refuses("Invalid sampler slot", INLINE, described(INLINE_BINDINGS, samplers={4: (1, 2, 3, 4)}))
    refuses("A binding description replaces the fixed-contract arguments", SETS, SETS_BINDINGS, constant_descriptor=64)
    must_reject(lambda: lower(SETS, bindings={"s2": "descriptors"}))


def binary_fixtures():
    return [(SETS, translate_sets), (INLINE, translate_inline)]
