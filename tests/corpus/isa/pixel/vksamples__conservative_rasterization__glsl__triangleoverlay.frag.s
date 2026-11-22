# Pixel Shader
BB0:
	v_cvt_pkrtz_f16_f32_e64 v0, 1.0, 0                          ; d52f0000 000100f2
	v_mov_b32_e32 v1, 0x3c003c00                                ; 7e0202ff 3c003c00
	exp mrt0 v1, v1, v0, v0 done compr vm                       ; f8001c0f 80800001
	s_endpgm                                                    ; bf810000
