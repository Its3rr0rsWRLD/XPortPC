# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.w                         ; c8080300
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_p1_f32_e32 v4, v0, attr1.y                         ; c8100500
	v_interp_p1_f32_e32 v9, v0, attr0.y                         ; c8240100
	v_interp_p1_f32_e32 v11, v0, attr0.z                        ; c82c0200
	v_interp_p1_f32_e32 v12, v0, attr0.x                        ; c8300000
	v_interp_p2_f32_e32 v2, v1, attr0.w                         ; c8090301
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	v_interp_p2_f32_e32 v4, v1, attr1.y                         ; c8110501
	v_interp_p2_f32_e32 v9, v1, attr0.y                         ; c8250101
	v_interp_p2_f32_e32 v11, v1, attr0.z                        ; c82d0201
	v_interp_p2_f32_e32 v12, v1, attr0.x                        ; c8310001
	v_interp_p1_f32_e32 v13, v0, attr2.z                        ; c8340a00
	v_interp_p2_f32_e32 v13, v1, attr2.z                        ; c8350a01
	v_interp_p1_f32_e32 v14, v0, attr2.x                        ; c8380800
	v_interp_p2_f32_e32 v14, v1, attr2.x                        ; c8390801
	v_mul_f32_e32 v6, 0x3e800000, v2                            ; 100c04ff 3e800000
	v_mul_f32_e32 v7, 0x3e800000, v3                            ; 100e06ff 3e800000
	v_max3_f32 v5, v2, v3, v4                                   ; d5540005 04120702
	v_mul_f32_e32 v8, 0x3e800000, v4                            ; 101008ff 3e800000
	v_mul_f32_e32 v10, v9, v9                                   ; 10141309
	v_interp_p1_f32_e32 v17, v0, attr2.y                        ; c8440900
	v_interp_p2_f32_e32 v17, v1, attr2.y                        ; c8450901
	v_mul_f32_e32 v15, v14, v14                                 ; 101e1d0e
	v_cmp_le_f32_e32 vcc, 0x3f666666, v5                        ; 7c060aff 3f666666
	v_mac_f32_e32 v10, v11, v11                                 ; 3e14170b
	v_interp_p1_f32_e32 v18, v0, attr1.w                        ; c8480700
	v_interp_p2_f32_e32 v18, v1, attr1.w                        ; c8490701
	v_interp_p1_f32_e32 v0, v0, attr1.z                         ; c8000600
	v_interp_p2_f32_e32 v0, v1, attr1.z                         ; c8010601
	v_mad_f32 v16, v13, v13, v15                                ; d5410010 043e1b0d
	v_cndmask_b32_e32 v6, 0, v6, vcc                            ; 020c0c80
	v_cndmask_b32_e32 v7, 0, v7, vcc                            ; 020e0e80
	v_cndmask_b32_e32 v8, 0, v8, vcc                            ; 02101080
	v_mac_f32_e32 v10, v12, v12                                 ; 3e14190c
	v_mac_f32_e32 v15, v18, v18                                 ; 3e1e2512
	v_mac_f32_e32 v16, v17, v17                                 ; 3e202311
	v_rsq_f32_e32 v10, v10                                      ; 7e145d0a
	v_mac_f32_e32 v15, v0, v0                                   ; 3e1e0100
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_rsq_f32_e32 v15, v15                                      ; 7e1e5d0f
	v_mul_f32_e32 v9, v9, v10                                   ; 10121509
	v_mul_f32_e32 v11, v11, v10                                 ; 1016150b
	v_mul_f32_e32 v12, v12, v10                                 ; 1018150c
	v_mul_f32_e32 v13, v13, v16                                 ; 101a210d
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v16, v14, v16                                 ; 1020210e
	v_mul_f32_e32 v0, v0, v15                                   ; 10001f00
	v_mul_f32_e32 v18, v18, v15                                 ; 10241f12
	v_mul_f32_e32 v14, v14, v15                                 ; 101c1f0e
	v_mul_f32_e32 v19, v16, v11                                 ; 10261710
	v_mad_f32 v20, v13, -v9, -v19                               ; d5410014 c44e130d
	v_mac_f32_e32 v19, v13, v9                                  ; 3e26130d
	v_mad_f32 v20, v17, -v12, v20 mul:2                         ; d5410014 4c521911
	v_mac_f32_e32 v19, v17, v12                                 ; 3e261911
	v_mad_f32 v11, v11, -v20, -v16                              ; d541000b c442290b
	v_mad_f32 v21, v12, -v20, -v17                              ; d5410015 c446290c
	v_mad_f32 v22, v9, -v20, -v13                               ; d5410016 c4362909
	v_max_f32_e32 v19, 0, v19                                   ; 20262680
	v_mul_f32_e32 v11, v11, v14                                 ; 10161d0b
	v_mac_f32_e32 v6, v2, v19                                   ; 3e0c2702
	v_mac_f32_e32 v7, v3, v19                                   ; 3e0e2703
	v_mac_f32_e32 v8, v4, v19                                   ; 3e102704
	v_mac_f32_e32 v11, v22, v18                                 ; 3e162516
	v_mac_f32_e32 v11, v21, v0                                  ; 3e160115
	v_max_f32_e32 v11, 0, v11                                   ; 20161680
	v_mul_f32_e32 v11, v11, v11                                 ; 1016170b
	(then repeated 2 times)
	v_fma_mixlo_f16 v23, 0, v11, v6                             ; cc210017 041a16ff 3f400000
	v_fma_mixhi_f16 v23, 0, v11, v7                             ; cc220017 041e16ff 3f400000
	v_madmk_f32 v11, v11, 0x3f400000, v8                        ; 4016110b 3f400000
	v_cvt_pkrtz_f16_f32_e64 v11, v11, 1.0                       ; d52f000b 0001e50b
	exp mrt0 v23, v23, v11, v11 done compr vm                   ; f8001c0f 80800b17
	s_endpgm                                                    ; bf810000
