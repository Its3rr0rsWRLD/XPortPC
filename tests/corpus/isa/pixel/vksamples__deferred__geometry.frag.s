# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.w                         ; c8080300
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v5, v0, attr0.y                         ; c8140100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v5, v1, attr0.y                         ; c8150101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[8:11], [v0, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220800 00000005
	v_interp_p2_f32_e32 v2, v1, attr0.w                         ; c8090301
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_mul_f32_e32 v6, v2, v2                                    ; 100c0502
	v_mul_f32_e32 v2, 0.5, v2                                   ; 100404f0
	v_mac_f32_e32 v6, v3, v3                                    ; 3e0c0703
	v_mul_f32_e32 v3, 0.5, v3                                   ; 100606f0
	v_mac_f32_e32 v6, v4, v4                                    ; 3e0c0904
	v_mul_f32_e32 v4, 0.5, v4                                   ; 100808f0
	v_rsq_f32_e32 v6, v6                                        ; 7e0c5d06
	v_fma_mixlo_f16 v7, v4, v6, 0.5 op_sel_hi:[0,0,1]           ; cc214007 03c20d04
	v_fma_mixhi_f16 v7, v2, v6, 0.5 op_sel_hi:[0,0,1]           ; cc224007 03c20d02
	v_mad_f32 v3, v3, v6, 0.5                                   ; d5410003 03c20d03
	v_cvt_pkrtz_f16_f32_e64 v3, v3, 1.0                         ; d52f0003 0001e503
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v10, v10, v11                       ; 5e14170a
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v9                          ; 5e101308
	exp mrt0 v8, v8, v10, v10 compr                             ; f800040f 80800a08
	exp mrt1 v7, v7, v3, v3 done compr vm                       ; f8001c1f 80800307
	s_endpgm                                                    ; bf810000
