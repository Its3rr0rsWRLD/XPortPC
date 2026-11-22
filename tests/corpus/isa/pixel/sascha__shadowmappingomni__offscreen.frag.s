# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.z                         ; c80c0200
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.z                         ; c80d0201
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_mul_f32_e32 v2, v2, v2                                    ; 10040502
	v_mac_f32_e32 v2, v3, v3                                    ; 3e040703
	v_mac_f32_e32 v2, v0, v0                                    ; 3e040100
	v_sqrt_f32_e32 v2, v2                                       ; 7e046702
	v_cvt_pkrtz_f16_f32_e64 v2, v2, 0                           ; d52f0002 00010102
	exp mrt0 v2, v2, off, off done compr vm                     ; f8001c03 80808002
	s_endpgm                                                    ; bf810000
