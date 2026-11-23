; R4 pixel program: attribute 0 (u, v) interpolated, the texture sampled through a T# and an S#, scaled by
; the constant buffer's tint, alpha from a push word. Entry: s2 the interpolation base; s3 low word of the
; CBV/SRV/UAV table address (T# at byte 0x20, the tint's V# at 0x40); s4 low word of the sampler table
; address (S# at 0); s5 a root constant (alpha as binary32). The tint is at byte 0x110 of its 512-byte constant
; buffer, past the first 256 bytes: the translation declares a 288-byte window, which the shim's root CBV covers.
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
s_mov_b32 s22, s4
s_movk_i32 s23, 0x8000
s_load_dwordx8 s[24:31], s[20:21], 0x20
s_load_dwordx4 s[32:35], s[22:23], null
s_load_dwordx4 s[36:39], s[20:21], 0x40
s_waitcnt lgkmcnt(0)
image_sample v[12:15], v[8:9], s[24:31], s[32:35] dmask:0xf dim:SQ_RSRC_IMG_2D
s_buffer_load_dwordx4 s[40:43], s[36:39], 0x110
s_waitcnt vmcnt(0) lgkmcnt(0)
v_mul_f32_e32 v12, s40, v12
v_mul_f32_e32 v13, s41, v13
v_mul_f32_e32 v14, s42, v14
v_mov_b32_e32 v15, s5
exp mrt0 v12, v13, v14, v15 done vm
s_endpgm
