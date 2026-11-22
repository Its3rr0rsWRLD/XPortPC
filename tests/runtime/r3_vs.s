; R3 vertex program (gfx1013, llvm-mc 15 syntax). Entry: v0 vertex id; s[2:3] title GPU address of the vertex
; buffer (float4 clip-space positions, 16-byte stride); s[4:5] title GPU address of the constants (float4 colour).
v_lshlrev_b32_e32 v1, 4, v0
global_load_dwordx4 v[2:5], v1, s[2:3]
s_load_dwordx4 s[8:11], s[4:5], null
s_waitcnt lgkmcnt(0)
v_mov_b32_e32 v6, s8
v_mov_b32_e32 v7, s9
v_mov_b32_e32 v8, s10
v_mov_b32_e32 v9, s11
s_waitcnt vmcnt(0)
exp param0 v6, v7, v8, v9
exp pos0 v2, v3, v4, v5 done vm
s_endpgm
