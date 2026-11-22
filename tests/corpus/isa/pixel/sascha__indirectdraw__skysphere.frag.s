# Pixel Shader
BB0:
	s_mov_b32 s0, 0x3f6e147b                                    ; be8003ff 3f6e147b
	s_mov_b32 m0, s2                                            ; befc0302
	s_mov_b32 s1, 0x3f666666                                    ; be8103ff 3f666666
	s_mov_b32 s2, 0x3e428f5c                                    ; be8203ff 3e428f5c
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_min_f32_e32 v0, 0.5, v0                                   ; 1e0000f0
	v_mad_f32 v0, 0x40d55555, v0, 0.5                           ; d5410000 03c200ff 40d55555
	v_fma_mixlo_f16 v1, 0x7ae2, v0, s0                          ; cc210001 000200ff bf147ae2
	v_fma_mixhi_f16 v1, 0xcccc, v0, s1                          ; cc220001 000600ff becccccc
	v_madak_f32 v0, s2, v0, 0x3f4f5c29                          ; 42000002 3f4f5c29
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 1.0                         ; d52f0000 0001e500
	exp mrt0 v1, v1, v0, v0 done compr vm                       ; f8001c0f 80800001
	s_endpgm                                                    ; bf810000
