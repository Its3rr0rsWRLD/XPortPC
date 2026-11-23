; R6 compute program (gfx1013, llvm-mc 15 syntax): reads a T#, an S# and a buffer V# from descriptor tables in
; title heaps, as hardware words the title wrote. One lane per texel of an 8x8 texture (workgroup 8x8x1, wave32,
; local ids v0 = x, v1 = y). Entry: s2 low word of the CBV/SRV/UAV table address (T# at 0x00, the output's V# at
; 0x20); s3 low word of the sampler table address (S# at 0); s4 a root constant: an offset (binary32) added to the
; sample's u. Each lane writes 32 bytes at 32 * (8 y + x) through the V#: image_load of its texel, then
; image_sample_lz at the texel's centre with u moved by the offset (through the S#'s address mode).
s_mov_b32 s20, s2
s_movk_i32 s21, 0x8000
s_mov_b32 s22, s3
s_movk_i32 s23, 0x8000
s_load_dwordx8 s[24:31], s[20:21], null
s_load_dwordx4 s[32:35], s[20:21], 0x20
s_load_dwordx4 s[36:39], s[22:23], null
v_cvt_f32_u32_e32 v2, v0
v_cvt_f32_u32_e32 v3, v1
v_add_f32_e32 v2, 0.5, v2
v_add_f32_e32 v3, 0.5, v3
v_mul_f32_e32 v2, 0x3e000000, v2
v_mul_f32_e32 v3, 0x3e000000, v3
v_add_f32_e32 v2, s4, v2
v_lshlrev_b32_e32 v12, 3, v1
v_add_nc_u32_e32 v12, v12, v0
v_lshlrev_b32_e32 v12, 5, v12
s_waitcnt lgkmcnt(0)
image_load v[4:7], v[0:1], s[24:31] dmask:0xf dim:SQ_RSRC_IMG_2D unorm
image_sample_lz v[8:11], v[2:3], s[24:31], s[36:39] dmask:0xf dim:SQ_RSRC_IMG_2D
s_waitcnt vmcnt(0)
buffer_store_dwordx4 v[4:7], v12, s[32:35], 0 offen
buffer_store_dwordx4 v[8:11], v12, s[32:35], 0 offen offset:16
s_endpgm
