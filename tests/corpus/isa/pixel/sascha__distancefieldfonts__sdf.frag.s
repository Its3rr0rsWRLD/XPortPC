# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_load_dwordx4 s[16:19], s[2:3], null                       ; f4080401 fa000000
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v2], s[8:15], s[4:7] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f080080a 00220000 00000002
	s_buffer_load_dword s1, s[16:19], 0x94                      ; f4200048 fa000094
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cmp_lt_f32_e64 vcc, 0, s1                                 ; d401006a 00000280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_subrev_f32_dpp v3, v0, v0 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a0600fa ff0c0000
	v_mov_b32_dpp v4, v3 quad_perm:[2,2,2,2] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e0802fa ff0caa03
	v_add_f32_dpp v3, |v3|, |v4| quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 060608fa ffac5503
	v_add_f32_e32 v5, 0.5, v3                                   ; 060a06f0
	v_sub_f32_e32 v6, 0.5, v3                                   ; 080c06f0
	v_sub_f32_e32 v5, v5, v6                                    ; 080a0d05
	v_sub_f32_e32 v6, v0, v6                                    ; 080c0d00
	v_rcp_f32_e32 v5, v5                                        ; 7e0a5505
	v_mul_f32_e64 v6, v6, v5 clamp                              ; d5088006 00020b06
	v_madak_f32 v7, -2.0, v6, 0x40400000                        ; 420e0cf5 40400000
	v_mul_f32_e32 v7, v6, v7                                    ; 100e0f06
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	s_cbranch_vccz BB2                                          ; bf86001d
BB1:
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dword s0, s[16:19], 0x90                      ; f4200008 fa000090
	s_buffer_load_dwordx4 s[4:7], s[16:19], 0x80                ; f4280108 fa000080
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e64 v1, 1.0, s0                                   ; d5040001 000000f2
	v_sub_f32_e32 v2, v1, v3                                    ; 08040701
	v_add_f32_e32 v1, v1, v3                                    ; 06020701
	v_sub_f32_e32 v0, v0, v2                                    ; 08000500
	v_sub_f32_e32 v1, v1, v2                                    ; 08020501
	v_rcp_f32_e32 v1, v1                                        ; 7e025501
	v_mul_f32_e64 v0, v0, v1 clamp                              ; d5088000 00020300
	v_madak_f32 v3, -2.0, v0, 0x40400000                        ; 420600f5 40400000
	v_mul_f32_e32 v3, v0, v3                                    ; 10060700
	v_mul_f32_e32 v0, v0, v3                                    ; 10000700
	v_sub_f32_e32 v4, 1.0, v0                                   ; 080800f2
	v_add_f32_e32 v5, s4, v4                                    ; 060a0804
	v_add_f32_e32 v7, s5, v4                                    ; 060e0805
	v_add_f32_e32 v4, s6, v4                                    ; 06080806
	v_mad_f32 v5, v0, v5, v6                                    ; d5410005 041a0b00
	v_mad_f32 v7, v0, v7, v6                                    ; d5410007 041a0f00
	v_mac_f32_e32 v6, v0, v4                                    ; 3e0c0900
	s_branch BB3                                                ; bf820003
BB2:
	v_mov_b32_e32 v0, v6                                        ; 7e000306
	v_mov_b32_e32 v5, v6                                        ; 7e0a0306
	v_mov_b32_e32 v7, v6                                        ; 7e0e0306
BB3:
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v0                          ; 5e0c0106
	v_cvt_pkrtz_f16_f32_e32 v5, v5, v7                          ; 5e0a0f05
	exp mrt0 v5, v5, v6, v6 done compr vm                       ; f8001c0f 80800605
	s_endpgm                                                    ; bf810000
