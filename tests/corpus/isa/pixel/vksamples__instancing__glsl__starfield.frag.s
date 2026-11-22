# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_mul_f32_e32 v3, 0x43da98f6, v2                            ; 100604ff 43da98f6
	v_mul_f32_e32 v2, 0x43dcb625, v2                            ; 100404ff 43dcb625
	v_fract_f32_e32 v0, v0                                      ; 7e004100
	v_fract_f32_e32 v3, v3                                      ; 7e064103
	v_fract_f32_e32 v2, v2                                      ; 7e044102
	v_add_f32_e32 v5, 0x4199851f, v0                            ; 060a00ff 4199851f
	v_add_f32_e32 v4, 0x4199851f, v3                            ; 060806ff 4199851f
	v_add_f32_e32 v6, 0x4199851f, v2                            ; 060c04ff 4199851f
	v_mul_f32_e32 v4, v3, v4                                    ; 10080903
	v_mac_f32_e32 v4, v2, v5                                    ; 3e080b02
	v_mac_f32_e32 v4, v0, v6                                    ; 3e080d00
	v_add_f32_e32 v0, v0, v4                                    ; 06000900
	v_add_f32_e32 v2, v2, v4                                    ; 06040902
	v_add_f32_e32 v3, v3, v4                                    ; 06060903
	v_add_f32_e32 v7, v0, v2                                    ; 060e0500
	v_add_f32_e32 v8, v0, v3                                    ; 06100700
	v_mul_f32_e32 v7, v7, v3                                    ; 100e0707
	v_mac_f32_e32 v7, v8, v2                                    ; 3e0e0508
	v_add_f32_e32 v2, v2, v3                                    ; 06040702
	v_mac_f32_e32 v7, v2, v0                                    ; 3e0e0102
	v_fract_f32_e32 v7, v7                                      ; 7e0e4107
	v_add_f32_e32 v9, 0xbf7d70a4, v7                            ; 06120eff bf7d70a4
	v_cmp_le_f32_e32 vcc, 0x3f7d70a4, v7                        ; 7c060eff 3f7d70a4
	v_mul_f32_e32 v9, 0x42c8000d, v9                            ; 101212ff 42c8000d
	v_log_f32_e32 v9, v9                                        ; 7e124f09
	v_mul_f32_e32 v9, 0x41800000, v9                            ; 101212ff 41800000
	v_exp_f32_e32 v9, v9                                        ; 7e124b09
	v_cndmask_b32_e32 v9, 0, v9, vcc                            ; 02121280
	v_cvt_pkrtz_f16_f32_e64 v10, v9, 1.0                        ; d52f000a 0001e509
	v_cvt_pkrtz_f16_f32_e32 v9, v9, v9                          ; 5e121309
	exp mrt0 v9, v9, v10, v10 done compr vm                     ; f8001c0f 80800a09
	s_endpgm                                                    ; bf810000
