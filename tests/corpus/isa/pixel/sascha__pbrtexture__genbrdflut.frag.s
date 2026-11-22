# Pixel Shader
BB0:
	s_mov_b32 m0, s2                                            ; befc0302
	s_mov_b32 s0, 0                                             ; be800380
	v_mov_b32_e32 v6, 0                                         ; 7e0c0280
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	v_mad_f32 v3, v2, -v2, 1.0                                  ; d5410003 43ca0502
	v_max_f32_e32 v5, 0, v2                                     ; 200a0480
	v_mul_f32_e32 v0, v0, v0                                    ; 10000100
	v_sqrt_f32_e32 v3, v3                                       ; 7e066703
	v_mul_f32_e32 v4, v0, v0                                    ; 10080100
	s_nop 0                                                     ; bf800000
	(then repeated 1 times)
BB1:
	s_mov_b32 s2, s0                                            ; be820300
	s_mov_b32 s3, s0                                            ; be830300
	s_lshr_b64 s[2:3], s[2:3], 16                               ; 90829002
	s_and_b32 s1, s2, 0xaaaaaaaa                                ; 8701ff02 aaaaaaaa
	s_lshr_b32 s1, s1, 1                                        ; 90018101
	s_and_b32 s2, s2, 0x55555555                                ; 8702ff02 55555555
	s_lshl_b32 s2, s2, 1                                        ; 8f028102
	s_or_b32 s2, s2, s1                                         ; 88020102
	s_and_b32 s3, s2, 0xcccccccc                                ; 8703ff02 cccccccc
	s_lshr_b32 s3, s3, 2                                        ; 90038203
	s_and_b32 s2, s2, 0x33333333                                ; 8702ff02 33333333
	s_lshl_b32 s2, s2, 2                                        ; 8f028202
	s_or_b32 s2, s2, s3                                         ; 88020302
	s_and_b32 s4, s2, 0xf0f0f0f0                                ; 8704ff02 f0f0f0f0
	v_cvt_f32_u32_e32 v9, s0                                    ; 7e120c00
	s_mov_b32 s6, 0x3bc90fdb                                    ; be8603ff 3bc90fdb
	s_lshr_b32 s4, s4, 4                                        ; 90048404
	s_and_b32 s2, s2, 0xf0f0f0f                                 ; 8702ff02 0f0f0f0f
	s_lshl_b32 s2, s2, 4                                        ; 8f028402
	v_madak_f32 v9, s6, v9, 0x3d1b999a                          ; 42121206 3d1b999a
	s_or_b32 s2, s2, s4                                         ; 88020402
	s_and_b32 s5, s2, 0xff00ff00                                ; 8705ff02 ff00ff00
	v_mul_f32_e32 v9, 0.15915494, v9                            ; 101212f8
	s_lshr_b32 s5, s5, 8                                        ; 90058805
	s_and_b32 s2, s2, 0xff00ff                                  ; 8702ff02 00ff00ff
	s_lshl_b32 s2, s2, 8                                        ; 8f028802
	v_cos_f32_e32 v10, v9                                       ; 7e146d09
	v_sin_f32_e32 v9, v9                                        ; 7e126b09
	s_or_b32 s2, s2, s5                                         ; 88020502
	v_cvt_f32_u32_e32 v7, s2                                    ; 7e0e0c02
	v_mul_f32_e32 v7, 0x2f800000, v7                            ; 100e0eff 2f800000
	v_sub_f32_e32 v8, 1.0, v7                                   ; 08100ef2
	v_mad_f32 v7, v4, v7, v8                                    ; d5410007 04220f04
	v_rcp_f32_e32 v7, v7                                        ; 7e0e5507
	s_mov_b64 s[2:3], exec                                      ; be82047e
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_sub_f32_e64 v11, 1.0, |v8|                                ; d504020b 000210f2
	v_sqrt_f32_e32 v11, v11                                     ; 7e16670b
	v_mul_f32_e32 v10, v11, v10                                 ; 1014150b
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mad_f32 v10, v10, v10, |v8|                               ; d541040a 0422150a
	v_sqrt_f32_e32 v8, v8                                       ; 7e106708
	v_mac_f32_e32 v10, v11, v11                                 ; 3e14170b
	v_rsq_f32_e32 v10, v10                                      ; 7e145d0a
	v_mul_f32_e32 v8, v8, v10                                   ; 10101508
	v_mul_f32_e32 v11, v11, v10                                 ; 1016150b
	v_mul_f32_e32 v12, v2, v8                                   ; 10181102
	v_mac_f32_e32 v12, v3, v11                                  ; 3e181703
	v_mul_f32_e32 v13, 2.0, v12                                 ; 101a18f4
	v_mad_f32 v13, v8, v13, -v2                                 ; d541000d 840a1b08
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v13                                    ; 7c221a80
	s_cbranch_execz BB7                                         ; bf880018
BB2:
	v_mul_f32_e32 v7, 0.5, v0                                   ; 100e00f0
	v_max_f32_e32 v13, 0, v13                                   ; 201a1a80
	v_max_f32_e32 v12, 0, v12                                   ; 20181880
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_sub_f32_e32 v9, 1.0, v7                                   ; 08120ef2
	v_mul_f32_e32 v8, v8, v5                                    ; 10100b08
	v_mad_f32 v10, v13, v9, v7                                  ; d541000a 041e130d
	v_mac_f32_e32 v7, v5, v9                                    ; 3e0e1305
	v_rcp_f32_e32 v8, v8                                        ; 7e105508
	v_rcp_f32_e32 v10, v10                                      ; 7e14550a
	v_rcp_f32_e32 v7, v7                                        ; 7e0e5507
	v_mul_f32_e32 v13, v13, v10                                 ; 101a150d
	v_mul_f32_e32 v7, v5, v7                                    ; 100e0f05
	v_mul_f32_e32 v13, v13, v7                                  ; 101a0f0d
	v_mul_f32_e32 v13, v13, v12                                 ; 101a190d
	v_sub_f32_e32 v12, 1.0, v12                                 ; 081818f2
	v_mul_f32_e32 v13, v13, v8                                  ; 101a110d
	v_mul_f32_e32 v11, v12, v12                                 ; 1016190c
	v_mul_f32_e32 v11, v11, v11                                 ; 1016170b
	v_mul_f32_e32 v11, v11, v12                                 ; 1016190b
	v_sub_f32_e32 v12, 1.0, v11                                 ; 081816f2
	v_mac_f32_e32 v1, v11, v13                                  ; 3e021b0b
	v_mac_f32_e32 v6, v12, v13                                  ; 3e0c1b0c
BB7:
	s_mov_b64 exec, s[2:3]                                      ; befe0402
	s_add_u32 s0, s0, 1                                         ; 80008100
	s_cmpk_ge_u32 s0, 0x400                                     ; b6000400
	s_cbranch_scc0 BB1                                          ; bf84ffa0
BB11:
	v_fma_mixlo_f16 v0, 0, v6, neg(0) op_sel_hi:[0,0,1]         ; cc214000 82020cff 3a800000
	v_fma_mixhi_f16 v0, 0, v1, neg(0) op_sel_hi:[0,0,1]         ; cc224000 820202ff 3a800000
	v_bfrev_b32_e32 v1, 60                                      ; 7e0270bc
	exp mrt0 v0, v0, v1, v1 done compr vm                       ; f8001c0f 80800100
	s_endpgm                                                    ; bf810000
