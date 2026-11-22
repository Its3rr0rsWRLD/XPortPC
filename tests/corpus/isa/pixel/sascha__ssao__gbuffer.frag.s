# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[0:1], null                        ; f40c0200 fa000000
	s_load_dwordx4 s[16:19], s[0:1], 0x50                       ; f4080400 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_p1_f32_e32 v4, v0, attr0.w                         ; c8100300
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	v_interp_p2_f32_e32 v4, v1, attr0.w                         ; c8110301
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v4, v3], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00820404 00000003
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[0:3], s[2:3], null                         ; f4080001 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx2 s[0:1], s[0:3], 0xc0                  ; f4240000 fa0000c0
	v_mad_f32 v2, 2.0, v2, -1.0                                 ; d5410002 03ce04f4
	v_interp_p1_f32_e32 v10, v0, attr0.z                        ; c8280200
	v_interp_p1_f32_e32 v11, v0, attr0.x                        ; c82c0000
	v_interp_p1_f32_e32 v8, v0, attr0.y                         ; c8200100
	v_interp_p1_f32_e32 v12, v0, attr1.y                        ; c8300500
	v_interp_p1_f32_e32 v13, v0, attr1.z                        ; c8340600
	v_interp_p1_f32_e32 v14, v0, attr1.w                        ; c8380700
	v_interp_p1_f32_e32 v15, v0, attr2.y                        ; c83c0900
	v_interp_p2_f32_e32 v10, v1, attr0.z                        ; c8290201
	v_interp_p1_f32_e32 v16, v0, attr2.x                        ; c8400800
	v_interp_p2_f32_e32 v11, v1, attr0.x                        ; c82d0001
	v_interp_p2_f32_e32 v8, v1, attr0.y                         ; c8210101
	v_interp_p1_f32_e32 v0, v0, attr2.z                         ; c8000a00
	v_interp_p2_f32_e32 v12, v1, attr1.y                        ; c8310501
	v_interp_p2_f32_e32 v13, v1, attr1.z                        ; c8350601
	v_interp_p2_f32_e32 v14, v1, attr1.w                        ; c8390701
	v_interp_p2_f32_e32 v15, v1, attr2.y                        ; c83d0901
	v_interp_p2_f32_e32 v16, v1, attr2.x                        ; c8410801
	v_interp_p2_f32_e32 v0, v1, attr2.z                         ; c8010a01
	v_mul_f32_e32 v9, v8, v8                                    ; 10121108
	v_mul_f32_e32 v8, 0.5, v8                                   ; 101010f0
	v_cvt_pkrtz_f16_f32_e32 v16, v16, v15                       ; 5e201f10
	v_mac_f32_e32 v9, v10, v10                                  ; 3e12150a
	v_mul_f32_e32 v10, 0.5, v10                                 ; 101414f0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e64 v21, s1, s0                                   ; d5040015 00000001
	v_mul_f32_e64 v19, 2.0, s0                                  ; d5080013 000000f4
	v_add_f32_e64 v20, s1, s0                                   ; d5030014 00000001
	v_mac_f32_e32 v9, v11, v11                                  ; 3e12170b
	v_mul_f32_e32 v11, 0.5, v11                                 ; 101616f0
	v_mul_f32_e32 v19, s1, v19                                  ; 10262601
	v_mad_f32 v2, v2, -v21, v20                                 ; d5410002 44522b02
	v_rsq_f32_e32 v9, v9                                        ; 7e125d09
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_fma_mixlo_f16 v17, v11, v9, 0.5 op_sel_hi:[0,0,1]         ; cc214011 03c2130b
	v_fma_mixhi_f16 v17, v8, v9, 0.5 op_sel_hi:[0,0,1]          ; cc224011 03c21308
	v_mad_f32 v10, v10, v9, 0.5                                 ; d541000a 03c2130a
	v_mul_f32_e32 v19, v19, v2                                  ; 10260513
	v_cvt_pkrtz_f16_f32_e64 v10, v10, 1.0                       ; d52f000a 0001e50a
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v19                         ; 5e002700
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v6, v6, v14                                   ; 100c1d06
	v_fma_mixlo_f16 v18, v4, v12, neg(0) op_sel_hi:[0,0,1]      ; cc214012 82021904
	v_fma_mixhi_f16 v18, v5, v13, neg(0) op_sel_hi:[0,0,1]      ; cc224012 82021b05
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v7                          ; 5e0c0f06
	exp mrt0 v16, v16, v0, v0 compr                             ; f800040f 80800010
	exp mrt1 v17, v17, v10, v10 compr                           ; f800041f 80800a11
	exp mrt2 v18, v18, v6, v6 done compr vm                     ; f8001c2f 80800612
	s_endpgm                                                    ; bf810000
