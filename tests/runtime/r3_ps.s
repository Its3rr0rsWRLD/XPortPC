; R3 pixel program: the provoking vertex's attribute 0 (flat, v_interp_mov p0), exported as a 32-bit colour.
; Entry: s2 the interpolation base (copied into m0).
s_mov_b32 m0, s2
v_interp_mov_f32_e32 v2, p0, attr0.x
v_interp_mov_f32_e32 v3, p0, attr0.y
v_interp_mov_f32_e32 v4, p0, attr0.z
v_interp_mov_f32_e32 v5, p0, attr0.w
exp mrt0 v2, v3, v4, v5 done vm
s_endpgm
