# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v5, v0, attr0.x                         ; c8140000
	v_interp_p1_f32_e32 v6, v0, attr1.x                         ; c8180400
	v_interp_p1_f32_e32 v8, v0, attr1.y                         ; c8200500
	v_interp_p1_f32_e32 v0, v0, attr0.w                         ; c8000300
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v5, v1, attr0.x                         ; c8150001
	v_interp_p2_f32_e32 v6, v1, attr1.x                         ; c8190401
	v_interp_p2_f32_e32 v8, v1, attr1.y                         ; c8210501
	v_interp_p2_f32_e32 v0, v1, attr0.w                         ; c8010301
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mov_b32_e32 v9, 0x3ecccccd                                ; 7e1202ff 3ecccccd
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mac_f32_e32 v7, v0, v0                                    ; 3e0e0100
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mul_f32_e32 v0, v0, v7                                    ; 10000f00
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v4, v4, v8                                    ; 10081104
	v_mac_f32_e32 v4, v2, v6                                    ; 3e080d02
	v_mac_f32_e32 v4, v5, v0                                    ; 3e080105
	v_cmp_lt_f32_e32 vcc, 0x3e800000, v4                        ; 7c0208ff 3e800000
	v_cndmask_b32_e32 v9, 0x3e4ccccd, v9, vcc                   ; 021212ff 3e4ccccd
	v_cmp_lt_f32_e32 vcc, 0.5, v4                               ; 7c0208f0
	v_cndmask_b32_e64 v9, v9, 0x3f19999a, vcc                   ; d5010009 01a9ff09 3f19999a
	v_cmp_lt_f32_e32 vcc, 0x3f666666, v4                        ; 7c0208ff 3f666666
	v_cndmask_b32_e64 v9, v9, 1.0, vcc                          ; d5010009 01a9e509
	v_cmp_lt_f32_e32 vcc, 0x3f7ae148, v4                        ; 7c0208ff 3f7ae148
	v_cndmask_b32_e64 v9, v9, 0x3fc00000, vcc                   ; d5010009 01a9ff09 3fc00000
	v_mul_f32_e32 v10, 0x3f6bd7b2, v9                           ; 101412ff 3f6bd7b2
	v_mul_f32_e32 v9, 0x3cae2973, v9                            ; 101212ff 3cae2973
	v_cvt_pkrtz_f16_f32_e32 v10, v10, v9                        ; 5e14130a
	v_cvt_pkrtz_f16_f32_e64 v9, v9, 0                           ; d52f0009 00010109
	exp mrt0 v10, v10, v9, v9 done compr vm                     ; f8001c0f 8080090a
	s_endpgm                                                    ; bf810000
