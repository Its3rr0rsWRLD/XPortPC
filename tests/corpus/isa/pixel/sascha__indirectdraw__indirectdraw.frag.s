# Pixel Shader
BB0:
	s_mov_b32 s4, s3                                            ; be840303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[16:19], s[2:3], 0x70                       ; f4080401 fa000070
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v2, v0, attr1.z                         ; c8080600
	v_interp_p1_f32_e32 v3, v0, attr1.w                         ; c80c0700
	v_interp_p1_f32_e32 v4, v0, attr2.x                         ; c8100800
	v_interp_p2_f32_e32 v2, v1, attr1.z                         ; c8090601
	v_interp_p2_f32_e32 v3, v1, attr1.w                         ; c80d0701
	v_interp_p2_f32_e32 v4, v1, attr2.x                         ; c8110801
	v_rndne_f32_e32 v4, v4                                      ; 7e084704
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[4:7], v[2:4], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D_ARRAY ; f0800f28 00820402
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_gt_f32_e32 vcc, 0.5, v7                               ; 7c080ef0
	s_andn2_b64 exec, s[0:1], vcc                               ; 8afe6a00
	s_cbranch_execz BB1                                         ; bf880034
	v_interp_p1_f32_e32 v9, v0, attr0.z                         ; c8240200
	v_interp_p1_f32_e32 v7, v0, attr0.y                         ; c81c0100
	v_interp_p1_f32_e32 v10, v0, attr0.x                        ; c8280000
	v_interp_p1_f32_e32 v11, v0, attr2.z                        ; c82c0a00
	v_interp_p1_f32_e32 v13, v0, attr2.w                        ; c8340b00
	v_interp_p1_f32_e32 v14, v0, attr2.y                        ; c8380900
	v_interp_p2_f32_e32 v9, v1, attr0.z                         ; c8250201
	v_interp_p2_f32_e32 v7, v1, attr0.y                         ; c81d0101
	v_interp_p2_f32_e32 v10, v1, attr0.x                        ; c8290001
	v_interp_p2_f32_e32 v11, v1, attr2.z                        ; c82d0a01
	v_interp_p2_f32_e32 v13, v1, attr2.w                        ; c8350b01
	v_interp_p2_f32_e32 v14, v1, attr2.y                        ; c8390901
	v_mul_f32_e32 v8, v7, v7                                    ; 10100f07
	v_mul_f32_e32 v12, v11, v11                                 ; 1018170b
	v_interp_p1_f32_e32 v15, v0, attr0.w                        ; c83c0300
	v_interp_p2_f32_e32 v15, v1, attr0.w                        ; c83d0301
	v_mac_f32_e32 v8, v9, v9                                    ; 3e101309
	v_mac_f32_e32 v12, v13, v13                                 ; 3e181b0d
	v_interp_p1_f32_e32 v16, v0, attr1.x                        ; c8400400
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v16, v1, attr1.x                        ; c8410401
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mac_f32_e32 v8, v10, v10                                  ; 3e10150a
	v_mac_f32_e32 v12, v14, v14                                 ; 3e181d0e
	v_rsq_f32_e32 v8, v8                                        ; 7e105d08
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_mul_f32_e32 v10, v10, v8                                  ; 1014110a
	v_mul_f32_e32 v7, v7, v8                                    ; 100e1107
	v_mul_f32_e32 v9, v9, v8                                    ; 10121109
	v_mul_f32_e32 v13, v13, v12                                 ; 101a190d
	v_mul_f32_e32 v14, v14, v12                                 ; 101c190e
	v_mul_f32_e32 v11, v11, v12                                 ; 1016190b
	v_mul_f32_e32 v9, v9, v13                                   ; 10121b09
	v_mac_f32_e32 v9, v7, v11                                   ; 3e121707
	v_mac_f32_e32 v9, v10, v14                                  ; 3e121d0a
	v_max_f32_e32 v9, 0, v9                                     ; 20121280
	v_madak_f32 v16, v16, v9, 0x3f266666                        ; 42201310 3f266666
	v_madak_f32 v15, v15, v9, 0x3f266666                        ; 421e130f 3f266666
	v_madak_f32 v0, v0, v9, 0x3f266666                          ; 42001300 3f266666
	v_fma_mixlo_f16 v17, v15, v4, neg(0) op_sel_hi:[0,0,1]      ; cc214011 8202090f
	v_fma_mixhi_f16 v17, v16, v5, neg(0) op_sel_hi:[0,0,1]      ; cc224011 82020b10
	v_mul_f32_e32 v0, v0, v6                                    ; 10000d00
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 1.0                         ; d52f0000 0001e500
	exp mrt0 v17, v17, v0, v0 done compr vm                     ; f8001c0f 80800011
	s_endpgm                                                    ; bf810000
BB1:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
