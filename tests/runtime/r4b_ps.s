; R4b pixel program: red and green from attribute 0 (flat), blue and alpha from table constant buffers 0 and 1,
; and a typed store of a word from constant buffer 3 at the index from constant buffer 2 through a UAV's V#.
; Entry: s2 the interpolation base; s3 low word of the descriptor table address (the UAV at byte 0x40, the
; constant buffers at 0x60, 0x80, 0xa0 and 0xc0, pixel constant slots 0 to 3).
s_mov_b32 m0, s2
v_interp_mov_f32_e32 v2, p0, attr0.x
v_interp_mov_f32_e32 v3, p0, attr0.y
s_mov_b32 s20, s3
s_movk_i32 s21, 0x8000
s_load_dwordx4 s[24:27], s[20:21], 0x40
s_load_dwordx4 s[28:31], s[20:21], 0x60
s_load_dwordx4 s[32:35], s[20:21], 0x80
s_load_dwordx4 s[36:39], s[20:21], 0xa0
s_load_dwordx4 s[40:43], s[20:21], 0xc0
s_waitcnt lgkmcnt(0)
s_buffer_load_dword s44, s[28:31], null
s_buffer_load_dword s45, s[32:35], 0x4
s_buffer_load_dword s46, s[36:39], 0x8
s_buffer_load_dword s47, s[40:43], 0xc
s_waitcnt lgkmcnt(0)
v_mov_b32_e32 v4, s44
v_mov_b32_e32 v5, s45
v_mov_b32_e32 v6, s46
v_mov_b32_e32 v7, s47
buffer_store_format_x v7, v6, s[24:27], 0 idxen
exp mrt0 v2, v3, v4, v5 done vm
s_endpgm
