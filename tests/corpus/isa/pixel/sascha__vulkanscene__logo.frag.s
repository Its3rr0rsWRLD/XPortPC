# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v8, v0, attr0.w                         ; c8200300
	v_interp_p1_f32_e32 v2, v0, attr2.x                         ; c8080800
	v_interp_p1_f32_e32 v3, v0, attr0.z                         ; c80c0200
	v_interp_p1_f32_e32 v4, v0, attr0.y                         ; c8100100
	v_interp_p1_f32_e32 v5, v0, attr1.w                         ; c8140700
	v_interp_p1_f32_e32 v6, v0, attr0.x                         ; c8180000
	v_interp_p1_f32_e32 v7, v0, attr1.z                         ; c81c0600
	v_interp_p1_f32_e32 v10, v0, attr1.x                        ; c8280400
	v_interp_p2_f32_e32 v8, v1, attr0.w                         ; c8210301
	v_interp_p2_f32_e32 v2, v1, attr2.x                         ; c8090801
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v3, v1, attr0.z                         ; c80d0201
	v_interp_p2_f32_e32 v4, v1, attr0.y                         ; c8110101
	v_interp_p2_f32_e32 v5, v1, attr1.w                         ; c8150701
	v_interp_p2_f32_e32 v6, v1, attr0.x                         ; c8190001
	v_interp_p2_f32_e32 v7, v1, attr1.z                         ; c81d0601
	v_interp_p2_f32_e32 v10, v1, attr1.x                        ; c8290401
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mul_f32_e32 v3, v3, v2                                    ; 10060503
	v_mac_f32_e32 v3, v4, v5                                    ; 3e060b04
	v_mac_f32_e32 v3, v6, v7                                    ; 3e060f06
	v_max_f32_e32 v3, 0, v3                                     ; 20060680
	v_mul_f32_e32 v0, v0, v3                                    ; 10000700
	v_fma_mixlo_f16 v9, v8, v3, neg(0) op_sel_hi:[0,0,1]        ; cc214009 82020708
	v_fma_mixhi_f16 v9, v10, v3, neg(0) op_sel_hi:[0,0,1]       ; cc224009 8202070a
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 1.0                         ; d52f0000 0001e500
	exp mrt0 v9, v9, v0, v0 done compr vm                       ; f8001c0f 80800009
	s_endpgm                                                    ; bf810000
