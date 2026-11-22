# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x3                                                ; bfa10003
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_load_dwordx8 s[16:23], s[2:3], 0x80                       ; f40c0401 fa000080
	s_load_dwordx4 s[24:27], s[2:3], 0xd0                       ; f4080601 fa0000d0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:6], [v3, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220403 00000002
	image_sample  v[7:9], [v3, v2], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00c40703 00000002
	v_interp_p1_f32_e32 v12, v0, attr1.w                        ; c8300700
	v_interp_p1_f32_e32 v13, v0, attr1.y                        ; c8340500
	v_interp_p1_f32_e32 v10, v0, attr1.z                        ; c8280600
	v_interp_p1_f32_e32 v15, v0, attr0.w                        ; c83c0300
	v_interp_p1_f32_e32 v17, v0, attr1.x                        ; c8440400
	v_interp_p1_f32_e32 v18, v0, attr0.z                        ; c8480200
	v_interp_p2_f32_e32 v12, v1, attr1.w                        ; c8310701
	v_interp_p2_f32_e32 v13, v1, attr1.y                        ; c8350501
	v_interp_p2_f32_e32 v10, v1, attr1.z                        ; c8290601
	v_interp_p2_f32_e32 v15, v1, attr0.w                        ; c83d0301
	v_interp_p2_f32_e32 v17, v1, attr1.x                        ; c8450401
	v_interp_p2_f32_e32 v18, v1, attr0.z                        ; c8490201
	v_interp_p1_f32_e32 v19, v0, attr2.y                        ; c84c0900
	v_interp_p2_f32_e32 v19, v1, attr2.y                        ; c84d0901
	v_interp_p1_f32_e32 v21, v0, attr2.z                        ; c8540a00
	v_interp_p2_f32_e32 v21, v1, attr2.z                        ; c8550a01
	v_mul_f32_e32 v11, v10, v10                                 ; 1016150a
	v_mul_f32_e32 v16, v15, v15                                 ; 10201f0f
	v_mul_f32_e32 v20, v19, v19                                 ; 10282713
	v_interp_p1_f32_e32 v0, v0, attr2.x                         ; c8000800
	v_interp_p2_f32_e32 v0, v1, attr2.x                         ; c8010801
	v_mac_f32_e32 v11, v12, v12                                 ; 3e16190c
	v_mac_f32_e32 v16, v17, v17                                 ; 3e202311
	v_mac_f32_e32 v20, v21, v21                                 ; 3e282b15
	v_mac_f32_e32 v11, v13, v13                                 ; 3e161b0d
	v_mac_f32_e32 v16, v18, v18                                 ; 3e202512
	v_mac_f32_e32 v20, v0, v0                                   ; 3e280100
	v_rsq_f32_e32 v14, v11                                      ; 7e1c5d0b
	v_sqrt_f32_e32 v11, v11                                     ; 7e16670b
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_rsq_f32_e32 v20, v20                                      ; 7e285d14
	v_mul_f32_e32 v13, v13, v14                                 ; 101a1d0d
	v_mul_f32_e32 v12, v12, v14                                 ; 10181d0c
	v_mul_f32_e32 v10, v10, v14                                 ; 10141d0a
	v_mad_f32 v11, 0x3cb60b61, -v11, 1.0                        ; d541000b 43ca16ff 3cb60b61
	v_mul_f32_e32 v18, v18, v16                                 ; 10242112
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v15, v15, v16                                 ; 101e210f
	v_max_f32_e64 v11, 0x3e800000, v11 clamp                    ; d510800b 000216ff 3e800000
	v_mul_f32_e32 v19, v19, v20                                 ; 10262913
	v_mul_f32_e32 v0, v0, v20                                   ; 10002900
	v_mul_f32_e32 v21, v21, v20                                 ; 102a2915
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e64 v7, -0.5, v7 mul:2                            ; d5030007 08020ef1
	v_add_f32_e64 v9, -0.5, v9 mul:2                            ; d5030009 080212f1
	v_add_f32_e64 v8, -0.5, v8 mul:2                            ; d5030008 080210f1
	v_mul_f32_e32 v22, v8, v8                                   ; 102c1108
	v_mac_f32_e32 v22, v9, v9                                   ; 3e2c1309
	v_mac_f32_e32 v22, v7, v7                                   ; 3e2c0f07
	v_rsq_f32_e32 v22, v22                                      ; 7e2c5d16
	v_mul_f32_e32 v8, v8, v22                                   ; 10102d08
	v_mul_f32_e32 v9, v9, v22                                   ; 10122d09
	v_mul_f32_e32 v7, v7, v22                                   ; 100e2d07
	v_mul_f32_e32 v23, v17, v9                                  ; 102e1311
	v_mul_f32_e32 v12, v12, v9                                  ; 1018130c
	v_mac_f32_e32 v23, v15, v8                                  ; 3e2e110f
	v_mac_f32_e32 v12, v10, v8                                  ; 3e18110a
	v_mad_f32 v23, v18, v7, v23 mul:2                           ; d5410017 0c5e0f12
	v_mad_f32 v13, v13, v7, v12 clamp                           ; d541800d 04320f0d
	v_mad_f32 v7, v7, -v23, v18                                 ; d5410007 444a2f07
	v_mad_f32 v8, v8, -v23, v15                                 ; d5410008 443e2f08
	v_mad_f32 v9, v9, -v23, v17                                 ; d5410009 44462f09
	v_mul_f32_e32 v23, v4, v13                                  ; 102e1b04
	v_mul_f32_e32 v21, v21, v9                                  ; 102a1315
	v_mac_f32_e32 v21, v19, v8                                  ; 3e2a1113
	v_mac_f32_e32 v21, v0, v7                                   ; 3e2a0f00
	v_mul_f32_e32 v0, v5, v13                                   ; 10001b05
	v_add_f32_e32 v13, v11, v13                                 ; 061a1b0b
	v_max_f32_e32 v21, 0, v21                                   ; 202a2a80
	v_mul_f32_e32 v6, v6, v13                                   ; 100c1b06
	v_mul_f32_e32 v21, v21, v21                                 ; 102a2b15
	v_mul_f32_e32 v6, v6, v11                                   ; 100c1706
	v_mul_f32_e32 v21, v21, v21                                 ; 102a2b15
	v_cvt_pkrtz_f16_f32_e64 v6, v6, 1.0                         ; d52f0006 0001e506
	v_madmk_f32 v23, v21, 0x3ed9999a, v23                       ; 402e2f15 3ed9999a
	v_madmk_f32 v21, v21, 0x3e800000, v0                        ; 402a0115 3e800000
	v_mac_f32_e32 v23, v4, v11                                  ; 3e2e1704
	v_mac_f32_e32 v21, v5, v11                                  ; 3e2a1705
	v_fma_mixlo_f16 v1, v23, v11, neg(0) op_sel_hi:[0,0,1]      ; cc214001 82021717
	v_fma_mixhi_f16 v1, v21, v11, neg(0) op_sel_hi:[0,0,1]      ; cc224001 82021715
	exp mrt0 v1, v1, v6, v6 done compr vm                       ; f8001c0f 80800601
	s_endpgm                                                    ; bf810000
