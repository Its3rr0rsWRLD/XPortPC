; R6 pixel program with an inline sampler: r4_ps.s with the S# set by s_mov in place of the sampler table's load
; (an immutable sampler a console compiler inlines). S# words: CLAMP_X MIRROR, CLAMP_Y and CLAMP_Z
; CLAMP_LAST_TEXEL (0x91); MAX_LOD 15.0 (0xf00000); point filters, MIP_FILTER_POINT (0x4000000); transparent black
; border. Entry: s2 the interpolation base; s3 low word of the CBV/SRV/UAV table address (T# at 0x20, the tint's
; V# at 0x40); s5 a root constant (alpha as binary32).
s_mov_b64 s[50:51], exec
s_wqm_b64 exec, exec
s_mov_b32 m0, s2
v_interp_p1_f32_e32 v8, v0, attr0.x
v_interp_p1_f32_e32 v9, v0, attr0.y
v_interp_p2_f32_e32 v9, v1, attr0.y
v_interp_p2_f32_e32 v8, v1, attr0.x
s_and_b64 exec, exec, s[50:51]
s_mov_b32 s20, s3
s_movk_i32 s21, 0x8000
s_load_dwordx8 s[24:31], s[20:21], 0x20
s_mov_b32 s32, 0x91
s_mov_b32 s33, 0xf00000
s_mov_b32 s34, 0x4000000
s_mov_b32 s35, 0
s_load_dwordx4 s[36:39], s[20:21], 0x40
s_waitcnt lgkmcnt(0)
image_sample v[12:15], v[8:9], s[24:31], s[32:35] dmask:0xf dim:SQ_RSRC_IMG_2D
s_buffer_load_dwordx4 s[40:43], s[36:39], null
s_waitcnt vmcnt(0) lgkmcnt(0)
v_mul_f32_e32 v12, s40, v12
v_mul_f32_e32 v13, s41, v13
v_mul_f32_e32 v14, s42, v14
v_mov_b32_e32 v15, s5
exp mrt0 v12, v13, v14, v15 done vm
s_endpgm
