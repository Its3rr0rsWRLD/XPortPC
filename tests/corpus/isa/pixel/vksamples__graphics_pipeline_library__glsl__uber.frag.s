# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v5, v0, attr0.x                         ; c8140000
	v_interp_p1_f32_e32 v6, v0, attr1.w                         ; c8180700
	v_interp_p1_f32_e32 v8, v0, attr2.x                         ; c8200800
	v_interp_p1_f32_e32 v9, v0, attr1.z                         ; c8240600
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v5, v1, attr0.x                         ; c8150001
	v_interp_p2_f32_e32 v6, v1, attr1.w                         ; c8190701
	v_interp_p2_f32_e32 v8, v1, attr2.x                         ; c8210801
	v_interp_p2_f32_e32 v9, v1, attr1.z                         ; c8250601
	v_interp_p1_f32_e32 v10, v0, attr1.x                        ; c8280400
	v_interp_p2_f32_e32 v10, v1, attr1.x                        ; c8290401
	v_interp_p1_f32_e32 v12, v0, attr1.y                        ; c8300500
	v_interp_p2_f32_e32 v12, v1, attr1.y                        ; c8310501
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mul_f32_e32 v11, v10, v10                                 ; 1016150a
	v_interp_p1_f32_e32 v0, v0, attr0.w                         ; c8000300
	v_interp_p2_f32_e32 v0, v1, attr0.w                         ; c8010301
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v11, v12, v12                                 ; 3e16190c
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_mac_f32_e32 v11, v0, v0                                   ; 3e160100
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_interp_mov_f32_e32 v17, p0, attr2.y                       ; c8460902
	v_mul_f32_e32 v0, v0, v11                                   ; 10001700
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_interp_mov_f32_e32 v19, p0, attr2.z                       ; c84e0a02
	v_mul_f32_e32 v13, v8, v4                                   ; 101a0908
	v_interp_mov_f32_e32 v21, p0, attr2.w                       ; c8560b02
	v_mul_f32_e32 v18, 0x3fe00000, v17                          ; 102422ff 3fe00000
	v_mul_f32_e32 v20, 0x3fe00000, v19                          ; 102826ff 3fe00000
	v_mad_f32 v14, v6, -v2, -v13                                ; d541000e c4360506
	v_mac_f32_e32 v13, v6, v2                                   ; 3e1a0506
	v_mul_f32_e32 v22, 0x3fe00000, v21                          ; 102c2aff 3fe00000
	v_mad_f32 v14, v9, -v5, v14 mul:2                           ; d541000e 4c3a0b09
	v_mac_f32_e32 v13, v9, v5                                   ; 3e1a0b09
	v_mad_f32 v4, v4, -v14, -v8                                 ; d5410004 c4221d04
	v_mad_f32 v15, v5, -v14, -v9                                ; d541000f c4261d05
	v_mad_f32 v16, v2, -v14, -v6                                ; d5410010 c41a1d02
	v_max_f32_e32 v13, 0, v13                                   ; 201a1a80
	v_mul_f32_e32 v4, v4, v12                                   ; 10081904
	v_mul_f32_e32 v18, v18, v13                                 ; 10241b12
	v_mul_f32_e32 v20, v20, v13                                 ; 10281b14
	v_mul_f32_e32 v22, v22, v13                                 ; 102c1b16
	v_mac_f32_e32 v4, v16, v10                                  ; 3e081510
	v_madmk_f32 v17, v17, 0x3e800000, v18                       ; 40222511 3e800000
	v_madmk_f32 v19, v19, 0x3e800000, v20                       ; 40262913 3e800000
	v_madmk_f32 v21, v21, 0x3e800000, v22                       ; 402a2d15 3e800000
	v_mac_f32_e32 v4, v15, v0                                   ; 3e08010f
	v_max_f32_e32 v4, 0, v4                                     ; 20080880
	v_log_f32_e32 v4, v4                                        ; 7e084f04
	v_mul_f32_e32 v4, 0x42000000, v4                            ; 100808ff 42000000
	v_exp_f32_e32 v4, v4                                        ; 7e084b04
	v_fma_mixlo_f16 v23, 0, v4, v17                             ; cc210017 044608ff 3f400000
	v_fma_mixhi_f16 v23, 0, v4, v19                             ; cc220017 044e08ff 3f400000
	v_madmk_f32 v4, v4, 0x3f400000, v21                         ; 40082b04 3f400000
	v_cvt_pkrtz_f16_f32_e64 v4, v4, 1.0                         ; d52f0004 0001e504
	exp mrt0 v23, v23, v4, v4 done compr vm                     ; f8001c0f 80800417
	s_endpgm                                                    ; bf810000
