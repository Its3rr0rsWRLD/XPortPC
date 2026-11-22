# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v0                          ; 5e040102
	exp mrt0 v2, v2, off, off done compr vm                     ; f8001c03 80808002
	s_endpgm                                                    ; bf810000
