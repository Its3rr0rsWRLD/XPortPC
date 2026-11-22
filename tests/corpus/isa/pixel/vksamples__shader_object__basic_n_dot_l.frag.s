# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v2, 0xbf3504f3, v2                            ; 100404ff bf3504f3
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_madmk_f32 v4, v4, 0x3f3504f3, v2                          ; 40080504 3f3504f3
	v_mac_f32_e32 v3, v0, v0                                    ; 3e060100
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v3, v3, v4                                    ; 10060903
	v_cvt_pkrtz_f16_f32_e64 v5, v3, 1.0                         ; d52f0005 0001e503
	v_cvt_pkrtz_f16_f32_e32 v3, v3, v3                          ; 5e060703
	exp mrt0 v3, v3, v5, v5 done compr vm                       ; f8001c0f 80800503
	s_endpgm                                                    ; bf810000
