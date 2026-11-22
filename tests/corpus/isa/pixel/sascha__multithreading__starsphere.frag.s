# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.z                         ; c8080200
	v_interp_p1_f32_e32 v4, v0, attr0.y                         ; c8100100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.z                         ; c8090201
	v_interp_p2_f32_e32 v4, v1, attr0.y                         ; c8110101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_fract_f32_e32 v2, v2                                      ; 7e044102
	v_mul_f32_e32 v5, 0x43dcb625, v4                            ; 100a08ff 43dcb625
	v_fract_f32_e32 v0, v0                                      ; 7e004100
	v_add_f32_e32 v3, 0x4199851f, v2                            ; 060604ff 4199851f
	v_fract_f32_e32 v5, v5                                      ; 7e0a4105
	v_add_f32_e32 v6, 0x4199851f, v0                            ; 060c00ff 4199851f
	v_mul_f32_e32 v3, v2, v3                                    ; 10060702
	v_add_f32_e32 v7, 0x4199851f, v5                            ; 060e0aff 4199851f
	v_mac_f32_e32 v3, v5, v6                                    ; 3e060d05
	v_mac_f32_e32 v3, v0, v7                                    ; 3e060f00
	v_add_f32_e32 v0, v0, v3                                    ; 06000700
	v_add_f32_e32 v5, v5, v3                                    ; 060a0705
	v_add_f32_e32 v2, v2, v3                                    ; 06040702
	v_add_f32_e32 v4, 0x3e800000, v4                            ; 060808ff 3e800000
	v_add_f32_e32 v8, v0, v5                                    ; 06100b00
	v_add_f32_e32 v9, v0, v2                                    ; 06120500
	v_mul_f32_e64 v13, 0x3e19999a, v4 clamp                     ; d508800d 000208ff 3e19999a
	v_mul_f32_e64 v11, 0x3dcccccd, v4 clamp                     ; d508800b 000208ff 3dcccccd
	v_mul_f32_e64 v4, 0x3ecccccd, v4 clamp                      ; d5088004 000208ff 3ecccccd
	v_mul_f32_e32 v8, v8, v2                                    ; 10100508
	v_mac_f32_e32 v8, v9, v5                                    ; 3e100b09
	v_add_f32_e32 v5, v5, v2                                    ; 060a0505
	v_mac_f32_e32 v8, v5, v0                                    ; 3e100105
	v_fract_f32_e32 v8, v8                                      ; 7e104108
	v_cmp_le_f32_e32 vcc, 0x3f7d70a4, v8                        ; 7c0610ff 3f7d70a4
	v_add_f32_e32 v10, 0xbf7d70a4, v8                           ; 061410ff bf7d70a4
	v_mul_f32_e32 v10, 0x42c8000d, v10                          ; 101414ff 42c8000d
	v_log_f32_e32 v10, v10                                      ; 7e144f0a
	v_mul_f32_e32 v10, 0x41800000, v10                          ; 101414ff 41800000
	v_exp_f32_e32 v10, v10                                      ; 7e144b0a
	v_cndmask_b32_e32 v10, 0, v10, vcc                          ; 02141480
	v_fma_mixlo_f16 v12, 1.0, v10, v11                          ; cc21000c 042e14f2
	v_fma_mixhi_f16 v12, 1.0, v10, v13                          ; cc22000c 043614f2
	v_add_f32_e32 v10, v10, v4                                  ; 0614090a
	v_cvt_pkrtz_f16_f32_e64 v10, v10, 1.0                       ; d52f000a 0001e50a
	exp mrt0 v12, v12, v10, v10 done compr vm                   ; f8001c0f 80800a0c
	s_endpgm                                                    ; bf810000
