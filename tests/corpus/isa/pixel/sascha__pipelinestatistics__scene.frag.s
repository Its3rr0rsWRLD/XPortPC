# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v5, v0, attr0.x                         ; c8140000
	v_interp_p1_f32_e32 v6, v0, attr2.z                         ; c8180a00
	v_interp_p1_f32_e32 v8, v0, attr2.w                         ; c8200b00
	v_interp_p1_f32_e32 v9, v0, attr2.y                         ; c8240900
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v5, v1, attr0.x                         ; c8150001
	v_interp_p2_f32_e32 v6, v1, attr2.z                         ; c8190a01
	v_interp_p2_f32_e32 v8, v1, attr2.w                         ; c8210b01
	v_interp_p2_f32_e32 v9, v1, attr2.y                         ; c8250901
	v_interp_p1_f32_e32 v10, v0, attr1.w                        ; c8280700
	v_interp_p2_f32_e32 v10, v1, attr1.w                        ; c8290701
	v_interp_p1_f32_e32 v12, v0, attr2.x                        ; c8300800
	v_interp_p2_f32_e32 v12, v1, attr2.x                        ; c8310801
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mul_f32_e32 v11, v10, v10                                 ; 1016150a
	v_interp_p1_f32_e32 v13, v0, attr1.z                        ; c8340600
	v_interp_p2_f32_e32 v13, v1, attr1.z                        ; c8350601
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v11, v12, v12                                 ; 3e16190c
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_mac_f32_e32 v11, v13, v13                                 ; 3e161b0d
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_interp_p1_f32_e32 v18, v0, attr0.w                        ; c8480300
	v_interp_p2_f32_e32 v18, v1, attr0.w                        ; c8490301
	v_interp_p1_f32_e32 v19, v0, attr1.x                        ; c84c0400
	v_interp_p2_f32_e32 v19, v1, attr1.x                        ; c84d0401
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v13, v13, v11                                 ; 101a170d
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_mul_f32_e32 v14, v8, v4                                   ; 101c0908
	v_mad_f32 v15, v6, -v2, -v14                                ; d541000f c43a0506
	v_mac_f32_e32 v14, v6, v2                                   ; 3e1c0506
	v_mad_f32 v15, v9, -v5, v15 mul:2                           ; d541000f 4c3e0b09
	v_mac_f32_e32 v14, v9, v5                                   ; 3e1c0b09
	v_mad_f32 v4, v4, -v15, -v8                                 ; d5410004 c4221f04
	v_mad_f32 v16, v5, -v15, -v9                                ; d5410010 c4261f05
	v_mad_f32 v17, v2, -v15, -v6                                ; d5410011 c41a1f02
	v_max_f32_e32 v14, 0, v14                                   ; 201c1c80
	v_mul_f32_e32 v4, v4, v12                                   ; 10081904
	v_mac_f32_e32 v4, v17, v10                                  ; 3e081511
	v_mac_f32_e32 v4, v16, v13                                  ; 3e081b10
	v_max_f32_e32 v4, 0, v4                                     ; 20080880
	v_mul_f32_e32 v4, v4, v4                                    ; 10080904
	(then repeated 2 times)
	v_mul_f32_e32 v4, 0x3f400000, v4                            ; 100808ff 3f400000
	v_fma_mixlo_f16 v20, v18, v14, v4                           ; cc210014 04121d12
	v_fma_mixhi_f16 v20, v19, v14, v4                           ; cc220014 04121d13
	v_mac_f32_e32 v4, v0, v14                                   ; 3e081d00
	v_cvt_pkrtz_f16_f32_e64 v4, v4, 0.5                         ; d52f0004 0001e104
	exp mrt0 v20, v20, v4, v4 done compr vm                     ; f8001c0f 80800414
	s_endpgm                                                    ; bf810000
