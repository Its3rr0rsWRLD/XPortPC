# Pixel Shader
BB0:
	v_mov_b32_e32 v0, 0x7e007e00                                ; 7e0002ff 7e007e00
	exp mrt0 v0, v0, v0, v0 done compr vm                       ; f8001c0f 80800000
	s_endpgm                                                    ; bf810000
