# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.z                         ; c80c0200
	v_interp_p1_f32_e32 v4, v0, attr0.x                         ; c8100000
	v_interp_p1_f32_e32 v5, v0, attr1.x                         ; c8140400
	v_interp_p1_f32_e32 v0, v0, attr0.w                         ; c8000300
	v_interp_p2_f32_e32 v5, v1, attr1.x                         ; c8150401
	v_interp_p2_f32_e32 v0, v1, attr0.w                         ; c8010301
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[6:8], [v0, v5], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220600 00000005
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.z                         ; c80d0201
	v_interp_p2_f32_e32 v4, v1, attr0.x                         ; c8110001
	v_mul_f32_e32 v9, v2, v2                                    ; 10120502
	v_add_f32_e32 v2, v2, v4                                    ; 06040902
	v_mac_f32_e32 v9, v3, v3                                    ; 3e120703
	v_mul_f32_e32 v2, 0xbf3504f3, v2                            ; 100404ff bf3504f3
	v_mac_f32_e32 v9, v4, v4                                    ; 3e120904
	v_rsq_f32_e32 v9, v9                                        ; 7e125d09
	v_mul_f32_e32 v9, v9, v2                                    ; 10120509
	v_max3_f32 v9, 0, v9, 0x3e4ccccd clamp                      ; d5548009 03fe1280 3e4ccccd
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v10, v9, v6, neg(0) op_sel_hi:[0,0,1]       ; cc21400a 82020d09
	v_fma_mixhi_f16 v10, v9, v7, neg(0) op_sel_hi:[0,0,1]       ; cc22400a 82020f09
	v_mul_f32_e32 v9, v9, v8                                    ; 10121109
	v_cvt_pkrtz_f16_f32_e64 v9, v9, 0                           ; d52f0009 00010109
	exp mrt0 v10, v10, v9, v9 done compr vm                     ; f8001c0f 8080090a
	s_endpgm                                                    ; bf810000
