# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v8, v0, attr0.w                         ; c8200300
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v5, v0, attr0.z                         ; c8140200
	v_interp_p1_f32_e32 v6, v0, attr0.x                         ; c8180000
	v_interp_p1_f32_e32 v7, v0, attr1.x                         ; c81c0400
	v_interp_p2_f32_e32 v8, v1, attr0.w                         ; c8210301
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v5, v1, attr0.z                         ; c8150201
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v6, v1, attr0.x                         ; c8190001
	v_interp_p2_f32_e32 v7, v1, attr1.x                         ; c81d0401
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_interp_mov_f32_e32 v9, p0, attr1.z                        ; c8260602
	v_interp_mov_f32_e32 v10, p0, attr1.w                       ; c82a0702
	v_mad_f32 v2, 2.0, v2, -1.0                                 ; d5410002 03ce04f4
	s_mov_b32 s0, 0x43800ccd                                    ; be8003ff 43800ccd
	v_mul_f32_e32 v4, v3, v3                                    ; 10080703
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v7                          ; 5e100f08
	v_interp_mov_f32_e32 v11, p0, attr2.x                       ; c82e0802
	v_interp_mov_f32_e32 v12, p0, attr2.y                       ; c8320902
	v_mov_b32_e32 v13, 0                                        ; 7e1a0280
	v_cvt_pkrtz_f16_f32_e32 v9, v9, v10                         ; 5e121509
	v_mad_f32 v2, 0x437fe666, -v2, s0                           ; d5410002 400204ff 437fe666
	v_mac_f32_e32 v4, v5, v5                                    ; 3e080b05
	v_cvt_pkrtz_f16_f32_e32 v11, v11, v12                       ; 5e16190b
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_mac_f32_e32 v4, v6, v6                                    ; 3e080d06
	v_rsq_f32_e32 v4, v4                                        ; 7e085d04
	v_mul_f32_e32 v2, 0x424ccccd, v2                            ; 100404ff 424ccccd
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v2                          ; 5e000500
	v_mul_f32_e32 v6, v6, v4                                    ; 100c0906
	v_mul_f32_e32 v3, v3, v4                                    ; 10060903
	v_mul_f32_e32 v5, v5, v4                                    ; 100a0905
	v_cvt_pkrtz_f16_f32_e64 v6, v6, -v3                         ; d52f0006 40020706
	v_cvt_pkrtz_f16_f32_e64 v5, v5, 1.0                         ; d52f0005 0001e505
	exp mrt0 v13, v13, v13, v13 compr                           ; f800040f 80800d0d
	exp mrt1 v8, v8, v0, v0 compr                               ; f800041f 80800008
	exp mrt2 v6, v6, v5, v5 compr                               ; f800042f 80800506
	exp mrt3 v9, v9, v11, v11 done compr vm                     ; f8001c3f 80800b09
	s_endpgm                                                    ; bf810000
