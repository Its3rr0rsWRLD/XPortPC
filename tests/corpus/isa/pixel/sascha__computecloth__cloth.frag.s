# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:6], [v3, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220403 00000002
	v_interp_p1_f32_e32 v10, v0, attr0.z                        ; c8280200
	v_interp_p1_f32_e32 v7, v0, attr0.w                         ; c81c0300
	v_interp_p1_f32_e32 v9, v0, attr1.x                         ; c8240400
	v_interp_p1_f32_e32 v11, v0, attr2.y                        ; c82c0900
	v_interp_p1_f32_e32 v13, v0, attr2.z                        ; c8340a00
	v_interp_p1_f32_e32 v14, v0, attr2.x                        ; c8380800
	v_interp_p2_f32_e32 v10, v1, attr0.z                        ; c8290201
	v_interp_p2_f32_e32 v7, v1, attr0.w                         ; c81d0301
	v_interp_p2_f32_e32 v9, v1, attr1.x                         ; c8250401
	v_interp_p2_f32_e32 v11, v1, attr2.y                        ; c82d0901
	v_interp_p2_f32_e32 v13, v1, attr2.z                        ; c8350a01
	v_interp_p2_f32_e32 v14, v1, attr2.x                        ; c8390801
	v_interp_p1_f32_e32 v15, v0, attr1.z                        ; c83c0600
	v_interp_p2_f32_e32 v15, v1, attr1.z                        ; c83d0601
	v_interp_p1_f32_e32 v17, v0, attr1.w                        ; c8440700
	v_interp_p2_f32_e32 v17, v1, attr1.w                        ; c8450701
	v_mul_f32_e32 v8, v7, v7                                    ; 10100f07
	v_mul_f32_e32 v12, v11, v11                                 ; 1018170b
	v_mul_f32_e32 v16, v15, v15                                 ; 10201f0f
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mac_f32_e32 v8, v9, v9                                    ; 3e101309
	v_mac_f32_e32 v12, v13, v13                                 ; 3e181b0d
	v_mac_f32_e32 v16, v17, v17                                 ; 3e202311
	v_mac_f32_e32 v8, v10, v10                                  ; 3e10150a
	v_mac_f32_e32 v12, v14, v14                                 ; 3e181d0e
	v_mac_f32_e32 v16, v0, v0                                   ; 3e200100
	v_rsq_f32_e32 v8, v8                                        ; 7e105d08
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_mul_f32_e32 v10, v10, v8                                  ; 1014110a
	v_mul_f32_e32 v7, v7, v8                                    ; 100e1107
	v_mul_f32_e32 v9, v9, v8                                    ; 10121109
	v_mul_f32_e32 v13, v13, v12                                 ; 101a190d
	v_mul_f32_e32 v14, v14, v12                                 ; 101c190e
	v_mul_f32_e32 v11, v11, v12                                 ; 1016190b
	v_mul_f32_e32 v15, v15, v16                                 ; 101e210f
	v_mul_f32_e32 v0, v0, v16                                   ; 10002100
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v18, v13, v9                                  ; 1024130d
	v_mad_f32 v19, v11, -v7, -v18                               ; d5410013 c44a0f0b
	v_mac_f32_e32 v18, v11, v7                                  ; 3e240f0b
	v_mad_f32 v19, v14, -v10, v19 mul:2                         ; d5410013 4c4e150e
	v_mac_f32_e32 v18, v14, v10                                 ; 3e24150e
	v_mad_f32 v21, v7, -v19, -v11                               ; d5410015 c42e2707
	v_mad_f32 v9, v9, -v19, -v13                                ; d5410009 c4362709
	v_mad_f32 v20, v10, -v19, -v14                              ; d5410014 c43a270a
	v_max_f32_e32 v18, 0x3e19999a, v18                          ; 202424ff 3e19999a
	v_mul_f32_e32 v9, v9, v17                                   ; 10122309
	v_mac_f32_e32 v9, v21, v15                                  ; 3e121f15
	v_mac_f32_e32 v9, v20, v0                                   ; 3e120114
	v_max_f32_e32 v9, 0, v9                                     ; 20121280
	v_mul_f32_e32 v9, v9, v9                                    ; 10121309
	(then repeated 2 times)
	v_mul_f32_e32 v9, 0x3e4ccccd, v9                            ; 101212ff 3e4ccccd
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v22, v18, v4, v9                            ; cc210016 04260912
	v_fma_mixhi_f16 v22, v18, v5, v9                            ; cc220016 04260b12
	v_mac_f32_e32 v9, v18, v6                                   ; 3e120d12
	v_cvt_pkrtz_f16_f32_e64 v9, v9, 1.0                         ; d52f0009 0001e509
	exp mrt0 v22, v22, v9, v9 done compr vm                     ; f8001c0f 80800916
	s_endpgm                                                    ; bf810000
