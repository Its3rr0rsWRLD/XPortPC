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
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_interp_p1_f32_e32 v14, v0, attr0.w                        ; c8380300
	v_interp_p2_f32_e32 v14, v1, attr0.w                        ; c8390301
	v_interp_p1_f32_e32 v15, v0, attr1.x                        ; c83c0400
	v_interp_p2_f32_e32 v15, v1, attr1.x                        ; c83d0401
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v10, v8, v4                                   ; 10140908
	v_mad_f32 v11, v6, -v2, -v10                                ; d541000b c42a0506
	v_mac_f32_e32 v10, v6, v2                                   ; 3e140506
	v_mad_f32 v11, v9, -v5, v11 mul:2                           ; d541000b 4c2e0b09
	v_mac_f32_e32 v10, v9, v5                                   ; 3e140b09
	v_mad_f32 v12, v5, -v11, -v9                                ; d541000c c4261705
	v_mad_f32 v13, v2, -v11, -v6                                ; d541000d c41a1702
	v_mad_f32 v4, v4, -v11, -v8                                 ; d5410004 c4221704
	v_max_f32_e32 v10, 0, v10                                   ; 20141480
	v_mul_f32_e32 v4, v4, v8                                    ; 10081104
	v_mac_f32_e32 v4, v13, v6                                   ; 3e080d0d
	v_mac_f32_e32 v4, v12, v9                                   ; 3e08130c
	v_max_f32_e32 v4, 0, v4                                     ; 20080880
	v_mul_f32_e32 v4, v4, v4                                    ; 10080904
	(then repeated 2 times)
	v_mul_f32_e32 v4, 0x3f400000, v4                            ; 100808ff 3f400000
	v_fma_mixlo_f16 v16, v14, v10, v4                           ; cc210010 0412150e
	v_fma_mixhi_f16 v16, v15, v10, v4                           ; cc220010 0412150f
	v_mac_f32_e32 v4, v0, v10                                   ; 3e081500
	v_cvt_pkrtz_f16_f32_e64 v4, v4, 1.0                         ; d52f0004 0001e504
	exp mrt0 v16, v16, v4, v4 done compr vm                     ; f8001c0f 80800410
	s_endpgm                                                    ; bf810000
