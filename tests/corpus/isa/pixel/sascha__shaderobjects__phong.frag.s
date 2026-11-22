# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v4, v0, attr1.y                         ; c8100500
	v_interp_p1_f32_e32 v5, v0, attr0.w                         ; c8140300
	v_interp_p1_f32_e32 v6, v0, attr0.y                         ; c8180100
	v_interp_p1_f32_e32 v8, v0, attr0.z                         ; c8200200
	v_interp_p1_f32_e32 v9, v0, attr0.x                         ; c8240000
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v4, v1, attr1.y                         ; c8110501
	v_interp_p2_f32_e32 v5, v1, attr0.w                         ; c8150301
	v_interp_p2_f32_e32 v6, v1, attr0.y                         ; c8190101
	v_interp_p2_f32_e32 v8, v1, attr0.z                         ; c8210201
	v_interp_p2_f32_e32 v9, v1, attr0.x                         ; c8250001
	v_interp_p1_f32_e32 v10, v0, attr2.z                        ; c8280a00
	v_interp_p2_f32_e32 v10, v1, attr2.z                        ; c8290a01
	v_interp_p1_f32_e32 v12, v0, attr2.w                        ; c8300b00
	v_interp_p2_f32_e32 v12, v1, attr2.w                        ; c8310b01
	v_mul_f32_e32 v3, 0x3f371759, v2                            ; 100604ff 3f371759
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mul_f32_e32 v11, v10, v10                                 ; 1016150a
	v_interp_p1_f32_e32 v13, v0, attr2.y                        ; c8340900
	v_interp_p2_f32_e32 v13, v1, attr2.y                        ; c8350901
	v_madmk_f32 v3, v4, 0x3d93dd98, v3                          ; 40060704 3d93dd98
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v11, v12, v12                                 ; 3e16190c
	v_interp_p1_f32_e32 v14, v0, attr1.w                        ; c8380700
	v_interp_p2_f32_e32 v14, v1, attr1.w                        ; c8390701
	v_madmk_f32 v3, v5, 0x3e59b3d0, v3                          ; 40060705 3e59b3d0
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_mac_f32_e32 v11, v13, v13                                 ; 3e161b0d
	v_interp_p1_f32_e32 v16, v0, attr2.x                        ; c8400800
	v_interp_p1_f32_e32 v0, v0, attr1.z                         ; c8000600
	v_interp_p2_f32_e32 v16, v1, attr2.x                        ; c8410801
	v_interp_p2_f32_e32 v0, v1, attr1.z                         ; c8010601
	v_mul_f32_e32 v15, v14, v14                                 ; 101e1d0e
	v_mul_f32_e32 v3, 0x3f266666, v3                            ; 100606ff 3f266666
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_mac_f32_e32 v15, v16, v16                                 ; 3e1e2110
	v_madmk_f32 v5, v5, 0x3eb33334, v3                          ; 400a0705 3eb33334
	v_madmk_f32 v2, v2, 0x3eb33334, v3                          ; 40040702 3eb33334
	v_madmk_f32 v4, v4, 0x3eb33334, v3                          ; 40080704 3eb33334
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mac_f32_e32 v15, v0, v0                                   ; 3e1e0100
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v13, v13, v11                                 ; 101a170d
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_mul_f32_e32 v21, 0x3fe00000, v5                           ; 102a0aff 3fe00000
	v_rsq_f32_e32 v15, v15                                      ; 7e1e5d0f
	v_mul_f32_e32 v17, v12, v8                                  ; 1022110c
	v_mul_f32_e32 v22, 0x3fe00000, v2                           ; 102c04ff 3fe00000
	v_mul_f32_e32 v23, 0x3fe00000, v4                           ; 102e08ff 3fe00000
	v_mad_f32 v18, v10, -v6, -v17                               ; d5410012 c4460d0a
	v_mac_f32_e32 v17, v10, v6                                  ; 3e220d0a
	v_mul_f32_e32 v0, v0, v15                                   ; 10001f00
	v_mul_f32_e32 v16, v16, v15                                 ; 10201f10
	v_mul_f32_e32 v14, v14, v15                                 ; 101c1f0e
	v_mad_f32 v18, v13, -v9, v18 mul:2                          ; d5410012 4c4a130d
	v_mac_f32_e32 v17, v13, v9                                  ; 3e22130d
	v_mad_f32 v8, v8, -v18, -v12                                ; d5410008 c4322508
	v_mad_f32 v19, v9, -v18, -v13                               ; d5410013 c4362509
	v_mad_f32 v20, v6, -v18, -v10                               ; d5410014 c42a2506
	v_max_f32_e32 v17, 0, v17                                   ; 20222280
	v_mul_f32_e32 v8, v8, v16                                   ; 10102108
	v_mac_f32_e32 v2, v22, v17                                  ; 3e042316
	v_mac_f32_e32 v4, v23, v17                                  ; 3e082317
	v_mac_f32_e32 v5, v21, v17                                  ; 3e0a2315
	v_mac_f32_e32 v8, v20, v14                                  ; 3e101d14
	v_mac_f32_e32 v8, v19, v0                                   ; 3e100113
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_log_f32_e32 v8, v8                                        ; 7e104f08
	v_mul_f32_e32 v8, 0x42000000, v8                            ; 101010ff 42000000
	v_exp_f32_e32 v8, v8                                        ; 7e104b08
	v_fma_mixlo_f16 v23, 0x3333, v8, v5                         ; cc210017 041610ff 3eb33333
	v_fma_mixhi_f16 v23, 0x3333, v8, v2                         ; cc220017 040a10ff 3eb33333
	v_madmk_f32 v8, v8, 0x3eb33333, v4                          ; 40100908 3eb33333
	v_cvt_pkrtz_f16_f32_e64 v8, v8, 1.0                         ; d52f0008 0001e508
	exp mrt0 v23, v23, v8, v8 done compr vm                     ; f8001c0f 80800817
	s_endpgm                                                    ; bf810000
