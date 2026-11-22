# Pixel Shader
BB0:
	v_cvt_pkrtz_f16_f32_e64 v0, s2, s3                          ; d52f0000 00000602
	v_cvt_pkrtz_f16_f32_e64 v1, s4, s5                          ; d52f0001 00000a04
	exp mrt0 v0, v0, v1, v1 done compr vm                       ; f8001c0f 80800100
	s_endpgm                                                    ; bf810000
