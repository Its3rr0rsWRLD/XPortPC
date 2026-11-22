# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v9, v0, attr2.w                         ; c8240b00
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v4, v0, attr2.x                         ; c8100800
	v_interp_p1_f32_e32 v5, v0, attr1.z                         ; c8140600
	v_interp_p1_f32_e32 v8, v0, attr0.z                         ; c8200200
	v_interp_p1_f32_e32 v11, v0, attr0.y                        ; c82c0100
	v_interp_p1_f32_e32 v12, v0, attr2.z                        ; c8300a00
	v_interp_p2_f32_e32 v9, v1, attr2.w                         ; c8250b01
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p1_f32_e32 v14, v0, attr0.x                        ; c8380000
	v_interp_p2_f32_e32 v4, v1, attr2.x                         ; c8110801
	v_interp_p2_f32_e32 v5, v1, attr1.z                         ; c8150601
	v_interp_p1_f32_e32 v15, v0, attr2.y                        ; c83c0900
	v_interp_p2_f32_e32 v8, v1, attr0.z                         ; c8210201
	v_interp_p2_f32_e32 v11, v1, attr0.y                        ; c82d0101
	v_interp_p2_f32_e32 v12, v1, attr2.z                        ; c8310a01
	v_interp_p2_f32_e32 v14, v1, attr0.x                        ; c8390001
	v_interp_p2_f32_e32 v15, v1, attr2.y                        ; c83d0901
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v10, v9, v8                                   ; 10141109
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mad_f32 v13, v12, -v11, -v10                              ; d541000d c42a170c
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mad_f32 v13, v15, -v14, v13 mul:2                         ; d541000d 4c361d0f
	v_mac_f32_e32 v10, v12, v11                                 ; 3e14170c
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mad_f32 v16, v14, -v13, -v15                              ; d5410010 c43e1b0e
	v_mad_f32 v17, v11, -v13, -v12                              ; d5410011 c4321b0b
	v_mad_f32 v13, v8, -v13, -v9                                ; d541000d c4261b08
	v_mac_f32_e32 v10, v15, v14                                 ; 3e141d0f
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_mul_f32_e32 v18, v17, v17                                 ; 10242311
	v_mul_f32_e32 v6, v5, v3                                    ; 100c0705
	v_mul_f32_e32 v5, v5, v14                                   ; 100a1d05
	v_mul_f32_e32 v7, v2, v3                                    ; 100e0702
	v_mul_f32_e32 v3, v4, v3                                    ; 10060704
	v_mul_f32_e32 v4, v4, v8                                    ; 10081104
	v_mac_f32_e32 v18, v13, v13                                 ; 3e241b0d
	v_mac_f32_e32 v4, v2, v11                                   ; 3e081702
	v_mac_f32_e32 v18, v16, v16                                 ; 3e242110
	v_rsq_f32_e32 v18, v18                                      ; 7e245d12
	v_mul_f32_e32 v16, v16, v18                                 ; 10202510
	v_mul_f32_e32 v17, v17, v18                                 ; 10222511
	v_mul_f32_e32 v13, v13, v18                                 ; 101a250d
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e64 v4, -v5                                   ; d411007e 40020b04
BB1:
	v_mul_f32_e32 v3, v3, v13                                   ; 10061b03
	v_mad_f32 v7, v7, -v17, -v3                                 ; d5410007 c40e2307
	v_mad_f32 v6, v6, -v16, v7                                  ; d5410006 441e2106
	v_max_f32_e32 v6, 0, v6                                     ; 200c0c80
	v_log_f32_e32 v6, v6                                        ; 7e0c4f06
	v_mul_f32_e32 v6, 0x41800000, v6                            ; 100c0cff 41800000
	v_exp_f32_e32 v6, v6                                        ; 7e0c4b06
	v_mul_f32_e32 v2, 0x3f400000, v6                            ; 10040cff 3f400000
	v_mul_f32_e32 v6, 0x3ec00000, v6                            ; 100c0cff 3ec00000
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
BB4:
	v_mov_b32_e32 v2, 0                                         ; 7e040280
	v_mov_b32_e32 v6, 0                                         ; 7e0c0280
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_interp_p1_f32_e32 v3, v0, attr0.w                         ; c80c0300
	v_interp_p1_f32_e32 v5, v0, attr1.x                         ; c8140400
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v3, v1, attr0.w                         ; c80d0301
	v_interp_p2_f32_e32 v5, v1, attr1.x                         ; c8150401
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_max_f32_e32 v10, 0, v10                                   ; 20141480
	v_add_f32_e32 v4, 0x3dcccccd, v10                           ; 060814ff 3dcccccd
	v_add_f32_e32 v10, 1.0, v10                                 ; 061414f2
	v_fma_mixlo_f16 v7, v4, v3, v6                              ; cc210007 041a0704
	v_fma_mixhi_f16 v7, v4, v5, v6                              ; cc220007 041a0b04
	v_fma_mixlo_f16 v8, v4, v0, v6                              ; cc210008 041a0104
	v_fma_mixhi_f16 v8, 1.0, v10, v2                            ; cc220008 040a14f2
	exp mrt0 v7, v7, v8, v8 done compr vm                       ; f8001c0f 80800807
	s_endpgm                                                    ; bf810000
