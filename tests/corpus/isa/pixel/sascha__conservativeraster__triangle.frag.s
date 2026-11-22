# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_cvt_pkrtz_f16_f32_e32 v3, v3, v2                          ; 5e060503
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 0                           ; d52f0000 00010100
	exp mrt0 v3, v3, v0, v0 done compr vm                       ; f8001c0f 80800003
	s_endpgm                                                    ; bf810000
