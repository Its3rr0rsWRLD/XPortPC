# Pixel Shader
BB0:
	v_mov_b32_e32 v0, 0x3c00                                    ; 7e0002ff 00003c00
	v_bfrev_b32_e32 v1, 60                                      ; 7e0270bc
	exp mrt0 v0, v0, v1, v1 done compr vm                       ; f8001c0f 80800100
	s_endpgm                                                    ; bf810000
