# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_lshrrev_b64 v[6:7], 0, 0                                  ; d7000006 00010080
	v_lshrrev_b64 v[8:9], 0, 0                                  ; d7000008 00010080
	v_mov_b32_e32 v10, 0                                        ; 7e140280
	v_interp_mov_f32_e32 v2, p0, attr0.z                        ; c80a0202
	v_interp_p1_f32_e32 v5, v0, attr0.x                         ; c8140000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v5, v1, attr0.x                         ; c8150001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_b  v[6:10], [v2, v5, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D tfe ; f0950f0a 00220602 00000005
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_eq_i32_e32 vcc, 0, v10                                ; 7d041480
	v_cndmask_b32_e32 v6, 0, v6, vcc                            ; 020c0c80
	v_cndmask_b32_e32 v7, 0, v7, vcc                            ; 020e0e80
	v_cndmask_b32_e32 v8, 0, v8, vcc                            ; 02101080
	v_cndmask_b32_e32 v9, 0, v9, vcc                            ; 02121280
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v7                          ; 5e0c0f06
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v9                          ; 5e101308
	exp mrt0 v6, v6, v8, v8 done compr vm                       ; f8001c0f 80800806
	s_endpgm                                                    ; bf810000
