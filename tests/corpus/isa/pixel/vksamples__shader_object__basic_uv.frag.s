# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_bfrev_b32_e32 v3, 60                                      ; 7e0670bc
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v2                          ; 5e000500
	exp mrt0 v0, v0, v3, v3 done compr vm                       ; f8001c0f 80800300
	s_endpgm                                                    ; bf810000
