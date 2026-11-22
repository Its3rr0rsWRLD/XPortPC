# Pixel Shader
BB0:
	v_mad_f32 v2, s2, neg(0.5), v2                              ; d5410002 4409e002
	v_mad_f32 v3, s3, neg(0.5), v3                              ; d5410003 440de003
	v_rcp_f32_e32 v0, s3                                        ; 7e005403
	v_mad_f32 v2, v2, v0, -s4                                   ; d5410002 80120102
	v_mad_f32 v3, v3, v0, -s5                                   ; d5410003 80160103
	v_mul_f32_e32 v2, v2, v2                                    ; 10040502
	v_mac_f32_e32 v2, v3, v3                                    ; 3e040703
	v_sqrt_f32_e32 v2, v2                                       ; 7e046702
	v_cmpx_ngt_f32_e64 0xbe4ccccd, -v2                          ; d41b007e 400204ff be4ccccd
	s_cbranch_execz BB1                                         ; bf880007
	v_cvt_pkrtz_f16_f32_e64 v1, s6, s7                          ; d52f0001 00000e06
	v_cvt_pkrtz_f16_f32_e64 v2, s8, 1.0                         ; d52f0002 0001e408
	exp mrt0 v1, v1, v2, v2 done compr vm                       ; f8001c0f 80800201
	s_endpgm                                                    ; bf810000
BB1:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
