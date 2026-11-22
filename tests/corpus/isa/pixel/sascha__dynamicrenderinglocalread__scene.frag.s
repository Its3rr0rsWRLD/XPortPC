# Pixel Shader
BB0:
	s_mov_b32 s4, s3                                            ; be840303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x50                       ; f4080401 fa000050
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v3, v0, attr2.z                         ; c80c0a00
	v_interp_p1_f32_e32 v4, v0, attr2.y                         ; c8100900
	v_interp_p2_f32_e32 v3, v1, attr2.z                         ; c80d0a01
	v_interp_p2_f32_e32 v4, v1, attr2.y                         ; c8110901
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v4, v3], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00820404 00000003
	v_interp_p1_f32_e32 v11, v0, attr0.x                        ; c82c0000
	v_interp_p1_f32_e32 v8, v0, attr0.y                         ; c8200100
	v_interp_p1_f32_e32 v10, v0, attr0.z                        ; c8280200
	v_interp_p2_f32_e32 v11, v1, attr0.x                        ; c82d0001
	v_interp_p2_f32_e32 v8, v1, attr0.y                         ; c8210101
	v_interp_p2_f32_e32 v10, v1, attr0.z                        ; c8290201
	v_mul_f32_e32 v9, v8, v8                                    ; 10121108
	v_mac_f32_e32 v9, v10, v10                                  ; 3e12150a
	v_mac_f32_e32 v9, v11, v11                                  ; 3e12170b
	v_rsq_f32_e32 v9, v9                                        ; 7e125d09
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v8, v8, v9                                    ; 10101308
	v_mul_f32_e32 v10, v10, v9                                  ; 1014130a
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_gt_f32_e32 vcc, 0.5, v7                               ; 7c080ef0
	s_andn2_b64 exec, s[0:1], vcc                               ; 8afe6a00
	s_cbranch_execz BB1                                         ; bf88002c
	v_mad_f32 v2, 2.0, v2, -1.0                                 ; d5410002 03ce04f4
	v_interp_p1_f32_e32 v16, v0, attr1.w                        ; c8400700
	v_interp_p1_f32_e32 v12, v0, attr0.w                        ; c8300300
	v_interp_p1_f32_e32 v14, v0, attr1.x                        ; c8380400
	v_interp_p1_f32_e32 v17, v0, attr1.z                        ; c8440600
	v_interp_p1_f32_e32 v15, v0, attr1.y                        ; c83c0500
	v_interp_p1_f32_e32 v0, v0, attr2.x                         ; c8000800
	v_interp_p2_f32_e32 v16, v1, attr1.w                        ; c8410701
	v_interp_p2_f32_e32 v12, v1, attr0.w                        ; c8310301
	v_interp_p2_f32_e32 v14, v1, attr1.x                        ; c8390401
	v_interp_p2_f32_e32 v17, v1, attr1.z                        ; c8450601
	v_interp_p2_f32_e32 v15, v1, attr1.y                        ; c83d0501
	v_interp_p2_f32_e32 v0, v1, attr2.x                         ; c8010801
	s_mov_b32 s5, 0x43800ccd                                    ; be8503ff 43800ccd
	v_cvt_pkrtz_f16_f32_e64 v11, v11, -v8                       ; d52f000b 4002110b
	v_cvt_pkrtz_f16_f32_e64 v10, v10, 1.0                       ; d52f000a 0001e50a
	v_mov_b32_e32 v18, 0                                        ; 7e240280
	v_fma_mixlo_f16 v13, v4, v12, neg(0) op_sel_hi:[0,0,1]      ; cc21400d 82021904
	v_fma_mixhi_f16 v13, v5, v14, neg(0) op_sel_hi:[0,0,1]      ; cc22400d 82021d05
	v_cvt_pkrtz_f16_f32_e32 v17, v17, v16                       ; 5e222111
	v_mad_f32 v2, 0x437fe666, -v2, s5                           ; d5410002 401604ff 437fe666
	v_mul_f32_e32 v6, v6, v15                                   ; 100c1f06
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v7                          ; 5e0c0f06
	v_mul_f32_e32 v2, 0x424ccccd, v2                            ; 100404ff 424ccccd
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v2                          ; 5e000500
	exp mrt0 v18, v18, v18, v18 compr                           ; f800040f 80801212
	exp mrt1 v17, v17, v0, v0 compr                             ; f800041f 80800011
	exp mrt2 v11, v11, v10, v10 compr                           ; f800042f 80800a0b
	exp mrt3 v13, v13, v6, v6 done compr vm                     ; f8001c3f 8080060d
	s_endpgm                                                    ; bf810000
BB1:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
