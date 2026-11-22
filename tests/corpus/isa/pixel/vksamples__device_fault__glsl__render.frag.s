# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_mov_b32_e32 v2, 0x3c0030cc                                ; 7e0402ff 3c0030cc
	v_interp_mov_f32_e32 v0, p0, attr0.y                        ; c8020102
	v_interp_mov_f32_e32 v1, p0, attr0.x                        ; c8060002
	v_cvt_pkrtz_f16_f32_e32 v1, v1, v0                          ; 5e020101
	exp mrt0 v1, v1, v2, v2 done compr vm                       ; f8001c0f 80800201
	s_endpgm                                                    ; bf810000
