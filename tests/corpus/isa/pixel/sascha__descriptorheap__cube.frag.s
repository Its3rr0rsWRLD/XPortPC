# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_lshl_b32 s4, s4, 4                                        ; 8f048404
	s_load_dwordx4 s[8:11], s[0:1], s4                          ; f4080200 08000000
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_mov_b32 m0, s5                                            ; befc0305
	v_interp_mov_f32_e32 v2, p0, attr1.y                        ; c80a0502
	v_lshlrev_b32_e32 v2, 6, v2                                 ; 34040486
	v_readfirstlane_b32 s0, v2                                  ; 7e000502
	s_load_dwordx8 s[0:7], s[2:3], s0                           ; f40c0001 00000000
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_p1_f32_e32 v4, v0, attr0.w                         ; c8100300
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	v_interp_p2_f32_e32 v4, v1, attr0.w                         ; c8110301
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v4, v3], s[0:7], s[8:11] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00400404 00000003
	v_interp_p1_f32_e32 v8, v0, attr0.x                         ; c8200000
	v_interp_p1_f32_e32 v9, v0, attr0.y                         ; c8240100
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v8, v1, attr0.x                         ; c8210001
	v_interp_p2_f32_e32 v9, v1, attr0.y                         ; c8250101
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v10, v4, v8, neg(0) op_sel_hi:[0,0,1]       ; cc21400a 82021104
	v_fma_mixhi_f16 v10, v5, v9, neg(0) op_sel_hi:[0,0,1]       ; cc22400a 82021305
	v_mul_f32_e32 v6, v6, v0                                    ; 100c0106
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v7                          ; 5e0c0f06
	exp mrt0 v10, v10, v6, v6 done compr vm                     ; f8001c0f 8080060a
	s_endpgm                                                    ; bf810000
