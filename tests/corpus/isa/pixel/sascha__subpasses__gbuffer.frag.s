# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v8, v0, attr1.z                         ; c8200600
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v5, v0, attr0.z                         ; c8140200
	v_interp_p1_f32_e32 v6, v0, attr0.x                         ; c8180000
	v_interp_p1_f32_e32 v7, v0, attr1.w                         ; c81c0700
	v_interp_p2_f32_e32 v8, v1, attr1.z                         ; c8210601
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v5, v1, attr0.z                         ; c8150201
	v_interp_p1_f32_e32 v9, v0, attr2.x                         ; c8240800
	v_interp_p2_f32_e32 v6, v1, attr0.x                         ; c8190001
	v_interp_p2_f32_e32 v7, v1, attr1.w                         ; c81d0701
	v_interp_p2_f32_e32 v9, v1, attr2.x                         ; c8250801
	v_interp_p1_f32_e32 v10, v0, attr0.w                        ; c8280300
	v_interp_p2_f32_e32 v10, v1, attr0.w                        ; c8290301
	v_interp_p1_f32_e32 v11, v0, attr1.x                        ; c82c0400
	v_interp_p2_f32_e32 v11, v1, attr1.x                        ; c82d0401
	v_mad_f32 v2, 2.0, v2, -1.0                                 ; d5410002 03ce04f4
	s_mov_b32 s0, 0x43800ccd                                    ; be8003ff 43800ccd
	v_mul_f32_e32 v4, v3, v3                                    ; 10080703
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v7                          ; 5e100f08
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mov_b32_e32 v12, 0                                        ; 7e180280
	v_cvt_pkrtz_f16_f32_e32 v10, v10, v11                       ; 5e14170a
	v_mad_f32 v2, 0x437fe666, -v2, s0                           ; d5410002 400204ff 437fe666
	v_mac_f32_e32 v4, v5, v5                                    ; 3e080b05
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 0                           ; d52f0000 00010100
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_mac_f32_e32 v4, v6, v6                                    ; 3e080d06
	v_rsq_f32_e32 v4, v4                                        ; 7e085d04
	v_mul_f32_e32 v2, 0x424ccccd, v2                            ; 100404ff 424ccccd
	v_cvt_pkrtz_f16_f32_e32 v9, v9, v2                          ; 5e120509
	v_mul_f32_e32 v6, v6, v4                                    ; 100c0906
	v_mul_f32_e32 v3, v3, v4                                    ; 10060903
	v_mul_f32_e32 v5, v5, v4                                    ; 100a0905
	v_cvt_pkrtz_f16_f32_e64 v6, v6, -v3                         ; d52f0006 40020706
	v_cvt_pkrtz_f16_f32_e64 v5, v5, 1.0                         ; d52f0005 0001e505
	exp mrt0 v12, v12, v12, v12 compr                           ; f800040f 80800c0c
	exp mrt1 v8, v8, v9, v9 compr                               ; f800041f 80800908
	exp mrt2 v6, v6, v5, v5 compr                               ; f800042f 80800506
	exp mrt3 v10, v10, v0, v0 done compr vm                     ; f8001c3f 8080000a
	s_endpgm                                                    ; bf810000
