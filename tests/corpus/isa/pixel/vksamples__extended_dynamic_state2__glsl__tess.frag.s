# Pixel Shader
BB0:
	v_mov_b32_e32 v0, 0x2f863955                                ; 7e0002ff 2f863955
	v_mov_b32_e32 v1, 0x3c002f86                                ; 7e0202ff 3c002f86
	exp mrt0 v0, v0, v1, v1 done compr vm                       ; f8001c0f 80800100
	s_endpgm                                                    ; bf810000
