# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v4, v0, attr1.y                         ; c8100500
	v_interp_p1_f32_e32 v5, v0, attr0.w                         ; c8140300
	v_interp_p1_f32_e32 v6, v0, attr1.w                         ; c8180700
	v_interp_p1_f32_e32 v8, v0, attr2.x                         ; c8200800
	v_interp_p1_f32_e32 v9, v0, attr1.z                         ; c8240600
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v4, v1, attr1.y                         ; c8110501
	v_interp_p2_f32_e32 v5, v1, attr0.w                         ; c8150301
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
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_interp_p1_f32_e32 v11, v0, attr0.x                        ; c82c0000
	v_interp_p2_f32_e32 v11, v1, attr0.x                        ; c82d0001
	v_interp_p1_f32_e32 v13, v0, attr0.y                        ; c8340100
	v_interp_p2_f32_e32 v13, v1, attr0.y                        ; c8350101
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mul_f32_e32 v4, v4, v8                                    ; 10081104
	v_mac_f32_e32 v4, v2, v6                                    ; 3e080d02
	v_mac_f32_e32 v4, v5, v9                                    ; 3e081305
	v_cmp_gt_f32_e32 vcc, 0.5, v4                               ; 7c0808f0
	v_cndmask_b32_e64 v10, 1.0, 0x3f400000, vcc                 ; d501000a 01a9fef2 3f400000
	v_cmp_gt_f32_e32 vcc, 0x3eb33333, v4                        ; 7c0808ff 3eb33333
	v_cndmask_b32_e64 v10, v10, 0x3f19999a, vcc                 ; d501000a 01a9ff0a 3f19999a
	v_cmp_gt_f32_e32 vcc, 0x3e800000, v4                        ; 7c0808ff 3e800000
	v_cndmask_b32_e64 v10, v10, 0.5, vcc                        ; d501000a 01a9e10a
	v_cmp_gt_f32_e32 vcc, 0x3dcccccd, v4                        ; 7c0808ff 3dcccccd
	v_cndmask_b32_e64 v10, v10, 0x3e800000, vcc                 ; d501000a 01a9ff0a 3e800000
	v_fma_mixlo_f16 v12, v11, v10, neg(0) op_sel_hi:[0,0,1]     ; cc21400c 8202150b
	v_fma_mixhi_f16 v12, v13, v10, neg(0) op_sel_hi:[0,0,1]     ; cc22400c 8202150d
	v_mul_f32_e32 v0, v0, v10                                   ; 10001500
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 0                           ; d52f0000 00010100
	exp mrt0 v12, v12, v0, v0 done compr vm                     ; f8001c0f 8080000c
	s_endpgm                                                    ; bf810000
