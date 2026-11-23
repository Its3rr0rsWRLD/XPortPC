; R5 refusal control: r5_cs.s with an s_barrier after the state load, which tools/compute_aot.py refuses
; (card C-6).
s_mov_b32 s8, s2
s_mov_b32 s9, s3
s_movk_i32 s10, 0x80
s_mov_b32 s11, 0x30000000
s_mov_b32 s12, s4
s_mov_b32 s13, s5
s_movk_i32 s14, 0x400
s_mov_b32 s15, 0x30000000
s_lshl_b32 s0, s7, 2
v_add_nc_u32_e32 v1, s0, v0
v_lshlrev_b32_e32 v2, 4, v1
buffer_load_dwordx4 v[4:7], v2, s[8:11], 0 offen
v_lshlrev_b32_e32 v3, 7, v1
s_waitcnt vmcnt(0)
s_barrier
v_add_f32_e32 v4, v4, v6
v_add_f32_e32 v5, v5, v7
buffer_store_dwordx4 v[4:7], v2, s[8:11], 0 offen
v_subrev_f32_e32 v8, s6, v4
v_subrev_f32_e32 v9, s6, v5
v_add_f32_e32 v10, s6, v4
v_add_f32_e32 v11, s6, v5
v_mov_b32_e32 v12, v10
v_mov_b32_e32 v13, v9
v_mov_b32_e32 v14, v8
v_mov_b32_e32 v15, v11
buffer_store_dwordx2 v[8:9], v3, s[12:15], 0 offen
buffer_store_dwordx2 v[12:13], v3, s[12:15], 0 offen offset:16
buffer_store_dwordx2 v[14:15], v3, s[12:15], 0 offen offset:32
buffer_store_dwordx2 v[12:13], v3, s[12:15], 0 offen offset:48
buffer_store_dwordx2 v[10:11], v3, s[12:15], 0 offen offset:64
buffer_store_dwordx2 v[14:15], v3, s[12:15], 0 offen offset:80
s_endpgm
