# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v3, v0, attr0.w                         ; c80c0300
	v_interp_p1_f32_e32 v4, v0, attr1.x                         ; c8100400
	v_interp_p1_f32_e32 v5, v0, attr2.x                         ; c8140800
	v_interp_p1_f32_e32 v6, v0, attr1.y                         ; c8180500
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p2_f32_e32 v3, v1, attr0.w                         ; c80d0301
	v_interp_p2_f32_e32 v4, v1, attr1.x                         ; c8110401
	v_interp_p2_f32_e32 v5, v1, attr2.x                         ; c8150801
	v_interp_p2_f32_e32 v6, v1, attr1.y                         ; c8190501
	v_mul_f32_e32 v3, v3, v2                                    ; 10060503
	v_mul_f32_e32 v4, v4, v2                                    ; 10080504
	v_mul_f32_e32 v6, v6, v5                                    ; 100c0b06
	v_mul_f32_e32 v3, v3, v2                                    ; 10060503
	v_mac_f32_e32 v3, v4, v5                                    ; 3e060b04
	v_mac_f32_e32 v3, v6, v5                                    ; 3e060b06
	v_mul_f32_e32 v7, -0.5, v3                                  ; 100e06f1
	v_cmpx_nlt_f32_e32 0, v7                                    ; 7c3c0e80
	s_cbranch_execz BB1                                         ; bf880018
	v_mul_f32_e32 v3, 0xbf38aa3b, v3                            ; 100606ff bf38aa3b
	v_interp_p1_f32_e32 v8, v0, attr1.z                         ; c8200600
	v_interp_p2_f32_e32 v8, v1, attr1.z                         ; c8210601
	v_exp_f32_e32 v3, v3                                        ; 7e064b03
	v_mul_f32_e32 v3, v3, v8                                    ; 10061103
	v_cmpx_ngt_f32_e32 0x3c23d70a, v3                           ; 7c3606ff 3c23d70a
	s_cbranch_execz BB1                                         ; bf88000f
	v_interp_p1_f32_e32 v9, v0, attr0.x                         ; c8240000
	v_interp_p1_f32_e32 v11, v0, attr0.y                        ; c82c0100
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v9, v1, attr0.x                         ; c8250001
	v_interp_p2_f32_e32 v11, v1, attr0.y                        ; c82d0101
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_fma_mixlo_f16 v10, v9, v3, neg(0) op_sel_hi:[0,0,1]       ; cc21400a 82020709
	v_fma_mixhi_f16 v10, v11, v3, neg(0) op_sel_hi:[0,0,1]      ; cc22400a 8202070b
	v_mul_f32_e32 v0, v0, v3                                    ; 10000700
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v3                          ; 5e000700
	exp mrt0 v10, v10, v0, v0 done compr vm                     ; f8001c0f 8080000a
	s_endpgm                                                    ; bf810000
BB1:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
