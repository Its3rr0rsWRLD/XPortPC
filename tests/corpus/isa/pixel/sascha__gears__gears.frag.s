# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v7, v0, attr2.w                         ; c81c0b00
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v4, v0, attr2.x                         ; c8100800
	v_interp_p1_f32_e32 v5, v0, attr1.z                         ; c8140600
	v_interp_p1_f32_e32 v6, v0, attr0.z                         ; c8180200
	v_interp_p1_f32_e32 v9, v0, attr0.y                         ; c8240100
	v_interp_p1_f32_e32 v10, v0, attr2.z                        ; c8280a00
	v_interp_p2_f32_e32 v7, v1, attr2.w                         ; c81d0b01
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p1_f32_e32 v12, v0, attr0.x                        ; c8300000
	v_interp_p2_f32_e32 v4, v1, attr2.x                         ; c8110801
	v_interp_p2_f32_e32 v5, v1, attr1.z                         ; c8150601
	v_interp_p1_f32_e32 v13, v0, attr2.y                        ; c8340900
	v_interp_p2_f32_e32 v6, v1, attr0.z                         ; c8190201
	v_interp_p2_f32_e32 v9, v1, attr0.y                         ; c8250101
	v_interp_p2_f32_e32 v10, v1, attr2.z                        ; c8290a01
	v_interp_p2_f32_e32 v12, v1, attr0.x                        ; c8310001
	v_interp_p2_f32_e32 v13, v1, attr2.y                        ; c8350901
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v8, v7, v6                                    ; 10100d07
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mad_f32 v11, v10, -v9, -v8                                ; d541000b c422130a
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mad_f32 v11, v13, -v12, v11 mul:2                         ; d541000b 4c2e190d
	v_mac_f32_e32 v8, v10, v9                                   ; 3e10130a
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mad_f32 v14, v12, -v11, -v13                              ; d541000e c436170c
	v_mad_f32 v6, v6, -v11, -v7                                 ; d5410006 c41e1706
	v_mad_f32 v15, v9, -v11, -v10                               ; d541000f c42a1709
	v_mac_f32_e32 v8, v13, v12                                  ; 3e10190d
	v_interp_p1_f32_e32 v17, v0, attr0.w                        ; c8440300
	v_interp_p2_f32_e32 v17, v1, attr0.w                        ; c8450301
	v_interp_p1_f32_e32 v19, v0, attr1.x                        ; c84c0400
	v_interp_p2_f32_e32 v19, v1, attr1.x                        ; c84d0401
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mul_f32_e32 v16, v15, v15                                 ; 10201f0f
	v_max_f32_e64 v8, 0, v8 div:2                               ; d5100008 18021080
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mac_f32_e32 v16, v6, v6                                   ; 3e200d06
	v_add_f32_e32 v18, 0x3e4ccccd, v8                           ; 062410ff 3e4ccccd
	v_mac_f32_e32 v16, v14, v14                                 ; 3e201d0e
	v_add_f32_e32 v8, 1.0, v8                                   ; 061010f2
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_mul_f32_e32 v14, v14, v16                                 ; 101c210e
	v_mul_f32_e32 v15, v15, v16                                 ; 101e210f
	v_mul_f32_e32 v6, v6, v16                                   ; 100c2106
	v_mul_f32_e32 v4, v4, v6                                    ; 10080d04
	v_mad_f32 v2, v2, -v15, -v4                                 ; d5410002 c4121f02
	v_mad_f32 v5, v5, -v14, v2                                  ; d5410005 440a1d05
	v_max_f32_e32 v5, 0, v5                                     ; 200a0a80
	v_log_f32_e32 v5, v5                                        ; 7e0a4f05
	v_mul_f32_e32 v5, 0x3f4ccccd, v5                            ; 100a0aff 3f4ccccd
	v_exp_f32_e32 v5, v5                                        ; 7e0a4b05
	v_mul_f32_e32 v20, 0x3e000000, v5                           ; 10280aff 3e000000
	v_fma_mixlo_f16 v22, v18, v0, v20                           ; cc210016 04520112
	v_fma_mixhi_f16 v22, 0, v5, v8                              ; cc220016 04220aff 3e800000
	v_fma_mixlo_f16 v21, v18, v17, v20                          ; cc210015 04522312
	v_fma_mixhi_f16 v21, v18, v19, v20                          ; cc220015 04522712
	exp mrt0 v21, v21, v22, v22 done compr vm                   ; f8001c0f 80801615
	s_endpgm                                                    ; bf810000
