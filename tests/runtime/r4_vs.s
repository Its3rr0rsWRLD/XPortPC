; R4 vertex program (gfx1013, llvm-mc 15 syntax). Entry: v0 vertex id and v3 instance id, both from 0;
; s[2:3] title GPU address of the vertex buffer (x, y, u, v per vertex, 16-byte stride); s4 base vertex;
; s5 start instance; s6 low word of the descriptor table address (the constant-buffer V# of the draw's
; offset at byte 0); s[8:9] title GPU address of the per-instance depths (16-byte stride).
v_add_nc_u32_e32 v1, s4, v0
v_lshlrev_b32_e32 v1, 4, v1
global_load_dwordx4 v[4:7], v1, s[2:3]
v_add_nc_u32_e32 v2, s5, v3
v_lshlrev_b32_e32 v2, 4, v2
global_load_dword v8, v2, s[8:9]
s_movk_i32 s7, 0x8000
s_load_dwordx4 s[12:15], s[6:7], null
v_mov_b32_e32 v9, 1.0
s_waitcnt lgkmcnt(0)
s_buffer_load_dwordx2 s[16:17], s[12:15], null
s_waitcnt vmcnt(0) lgkmcnt(0)
v_add_f32_e32 v4, s16, v4
v_add_f32_e32 v5, s17, v5
exp param0 v6, v7, v8, v9
exp pos0 v4, v5, v8, v9 done vm
s_endpgm
