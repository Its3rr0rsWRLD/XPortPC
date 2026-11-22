# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v9, v0, attr0.x                         ; c8240000
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v4, v0, attr1.y                         ; c8100500
	v_interp_p1_f32_e32 v5, v0, attr0.w                         ; c8140300
	v_interp_p1_f32_e32 v6, v0, attr0.y                         ; c8180100
	v_interp_p1_f32_e32 v8, v0, attr0.z                         ; c8200200
	v_interp_p2_f32_e32 v9, v1, attr0.x                         ; c8250001
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v4, v1, attr1.y                         ; c8110501
	v_interp_p2_f32_e32 v5, v1, attr0.w                         ; c8150301
	v_interp_p2_f32_e32 v6, v1, attr0.y                         ; c8190101
	v_interp_p1_f32_e32 v11, v0, attr1.w                        ; c82c0700
	v_interp_p2_f32_e32 v8, v1, attr0.z                         ; c8210201
	v_interp_p2_f32_e32 v11, v1, attr1.w                        ; c82d0701
	v_interp_p1_f32_e32 v13, v0, attr2.x                        ; c8340800
	v_interp_p2_f32_e32 v13, v1, attr2.x                        ; c8350801
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mul_f32_e32 v12, v11, v11                                 ; 1018170b
	v_interp_p1_f32_e32 v0, v0, attr1.z                         ; c8000600
	v_interp_p2_f32_e32 v0, v1, attr1.z                         ; c8010601
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v12, v13, v13                                 ; 3e181b0d
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_mac_f32_e32 v12, v0, v0                                   ; 3e180100
	v_rsq_f32_e32 v10, v3                                       ; 7e145d03
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_interp_mov_f32_e32 v18, p0, attr3.y                       ; c84a0d02
	v_rcp_f32_e32 v3, v3                                        ; 7e065503
	v_mul_f32_e32 v5, v5, v10                                   ; 100a1505
	v_mul_f32_e32 v2, v2, v10                                   ; 10041502
	v_mul_f32_e32 v4, v4, v10                                   ; 10081504
	v_interp_mov_f32_e32 v19, p0, attr3.z                       ; c84e0e02
	v_interp_mov_f32_e32 v20, p0, attr3.w                       ; c8520f02
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v11, v11, v12                                 ; 1016190b
	v_mul_f32_e32 v0, v0, v12                                   ; 10001900
	v_mul_f32_e32 v13, v13, v12                                 ; 101a190d
	v_mul_f32_e32 v20, v20, v3                                  ; 10280714
	v_mul_f32_e32 v18, v18, v3                                  ; 10240712
	v_mul_f32_e32 v19, v19, v3                                  ; 10260713
	v_interp_mov_f32_e32 v21, p0, attr4.w                       ; c8561302
	v_interp_mov_f32_e32 v22, p0, attr4.x                       ; c85a1002
	v_mul_f32_e32 v14, v4, v8                                   ; 101c1104
	v_interp_mov_f32_e32 v23, p0, attr4.y                       ; c85e1102
	v_mad_f32 v15, v2, -v6, -v14                                ; d541000f c43a0d02
	v_mac_f32_e32 v14, v2, v6                                   ; 3e1c0d02
	v_mad_f32 v15, v5, -v9, v15 mul:2                           ; d541000f 4c3e1305
	v_interp_mov_f32_e32 v1, p0, attr2.y                        ; c8060902
	v_mac_f32_e32 v14, v5, v9                                   ; 3e1c1305
	v_interp_mov_f32_e32 v3, p0, attr2.w                        ; c80e0b02
	v_mad_f32 v17, v6, -v15, -v2                                ; d5410011 c40a1f06
	v_interp_mov_f32_e32 v2, p0, attr2.z                        ; c80a0a02
	v_mad_f32 v8, v8, -v15, -v4                                 ; d5410008 c4121f08
	v_mad_f32 v16, v9, -v15, -v5                                ; d5410010 c4161f09
	v_max_f32_e32 v14, 0, v14                                   ; 201c1c80
	v_mul_f32_e32 v8, v8, v13                                   ; 10101b08
	v_mul_f32_e32 v19, v19, v14                                 ; 10261d13
	v_mul_f32_e32 v20, v20, v14                                 ; 10281d14
	v_mul_f32_e32 v18, v18, v14                                 ; 10241d12
	v_mac_f32_e32 v8, v17, v11                                  ; 3e101711
	v_interp_mov_f32_e32 v5, p0, attr3.x                        ; c8160c02
	v_mac_f32_e32 v23, v19, v21                                 ; 3e2e2b13
	v_mac_f32_e32 v22, v18, v21                                 ; 3e2c2b12
	v_mac_f32_e32 v8, v16, v0                                   ; 3e100110
	v_interp_mov_f32_e32 v0, p0, attr4.z                        ; c8021202
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_mac_f32_e32 v0, v20, v21                                  ; 3e002b14
	v_log_f32_e32 v8, v8                                        ; 7e104f08
	v_mul_f32_e32 v8, 0x41800000, v8                            ; 101010ff 41800000
	v_exp_f32_e32 v8, v8                                        ; 7e104b08
	v_mul_f32_e32 v8, 0x3f266666, v8                            ; 101010ff 3f266666
	v_mul_f32_e32 v8, v8, v21                                   ; 10102b08
	v_mul_f32_e32 v8, 0x3ca3d70a, v8                            ; 101010ff 3ca3d70a
	v_fma_mixlo_f16 v4, v22, v1, v8                             ; cc210004 04220316
	v_fma_mixhi_f16 v4, v23, v2, v8                             ; cc220004 04220517
	v_mac_f32_e32 v8, v0, v3                                    ; 3e100700
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v5                          ; 5e100b08
	exp mrt0 v4, v4, v8, v8 done compr vm                       ; f8001c0f 80800804
	s_endpgm                                                    ; bf810000
