# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x5                                                ; bfa10005
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_load_dwordx8 s[16:23], s[2:3], 0x60                       ; f40c0401 fa000060
	s_load_dwordx4 s[24:27], s[2:3], 0xb0                       ; f4080601 fa0000b0
	s_load_dwordx8 s[32:39], s[2:3], 0xc0                       ; f40c0801 fa0000c0
	s_load_dwordx8 s[40:47], s[2:3], 0x110                      ; f40c0a01 fa000110
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[3:5], [v0, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220300 00000002
	image_sample  v[6:8], [v0, v2], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00c40600 00000002
	image_sample  v[12:15], [v0, v2], s[32:39], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 01480c00 00000002
	s_buffer_load_dword s1, s[44:47], 0xd0                      ; f4200056 fa0000d0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_lt_i32 0, s1                                          ; bf040180
	s_cbranch_scc0 BB2                                          ; bf840012
BB1:
	s_cmp_eq_i32 s1, 2                                          ; bf008201
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_eq_i32 s1, 3                                          ; bf008301
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cndmask_b32_e32 v3, v3, v6, vcc                           ; 02060d03
	v_cndmask_b32_e32 v4, v4, v7, vcc                           ; 02080f04
	v_cndmask_b32_e32 v5, v5, v8, vcc                           ; 020a1105
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_eq_i32 s1, 4                                          ; bf008401
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v3, v3, v12, vcc                          ; 02061903
	v_cndmask_b32_e32 v4, v4, v13, vcc                          ; 02081b04
	v_cndmask_b32_e32 v5, v5, v14, vcc                          ; 020a1d05
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v3, v3, v15, vcc                          ; 02061f03
	v_cndmask_b32_e32 v4, v4, v15, vcc                          ; 02081f04
	v_cndmask_b32_e32 v5, v5, v15, vcc                          ; 020a1f05
	s_branch BB3                                                ; bf82015f
BB2:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x2                                                ; bfa10002
	s_buffer_load_dwordx16 s[0:15], s[44:47], null              ; f4300016 fa000000
	s_buffer_load_dwordx4 s[16:19], s[44:47], 0xc0              ; f4280416 fa0000c0
	s_buffer_load_dwordx16 s[48:63], s[44:47], 0x40             ; f4300c16 fa000040
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v0, v7, v7                                    ; 10000f07
	s_mov_b32 s20, 0x41800000                                   ; be9403ff 41800000
	v_mac_f32_e32 v0, v8, v8                                    ; 3e001108
	v_mac_f32_e32 v0, v6, v6                                    ; 3e000d06
	v_rsq_f32_e32 v0, v0                                        ; 7e005d00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e32 v1, s0, v3                                    ; 08020600
	v_sub_f32_e32 v2, s1, v4                                    ; 08040801
	v_sub_f32_e32 v9, s2, v5                                    ; 08120a02
	v_mul_f32_e32 v6, v6, v0                                    ; 100c0106
	v_mul_f32_e32 v7, v7, v0                                    ; 100e0107
	v_mul_f32_e32 v8, v8, v0                                    ; 10100108
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v18, s4, v12                                  ; 10241804
	v_mul_f32_e32 v19, s5, v13                                  ; 10261a05
	v_mul_f32_e32 v20, s6, v14                                  ; 10281c06
	v_mul_f32_e32 v10, v2, v2                                   ; 10140502
	v_mac_f32_e32 v10, v9, v9                                   ; 3e141309
	v_mac_f32_e32 v10, v1, v1                                   ; 3e140301
	v_rsq_f32_e32 v11, v10                                      ; 7e165d0a
	v_add_f32_e32 v10, 1.0, v10                                 ; 061414f2
	v_rcp_f32_e32 v10, v10                                      ; 7e14550a
	v_mul_f32_e32 v1, v1, v11                                   ; 10021701
	v_mul_f32_e32 v2, v2, v11                                   ; 10041702
	v_mul_f32_e32 v9, v9, v11                                   ; 10121709
	v_mul_f32_e32 v21, s4, v15                                  ; 102a1e04
	v_sub_f32_e32 v22, s16, v3                                  ; 082c0610
	v_sub_f32_e32 v23, s17, v4                                  ; 082e0811
	v_sub_f32_e32 v24, s18, v5                                  ; 08300a12
	v_mul_f32_e32 v16, v8, v9                                   ; 10201308
	v_mul_f32_e32 v10, s7, v10                                  ; 10141407
	v_mul_f32_e32 v25, v23, v23                                 ; 10322f17
	v_mad_f32 v17, v7, v2, v16                                  ; d5410011 04420507
	v_mad_f32 v16, v7, -v2, -v16                                ; d5410010 c4420507
	v_mac_f32_e32 v25, v24, v24                                 ; 3e323118
	v_mac_f32_e32 v17, v6, v1                                   ; 3e220306
	v_mad_f32 v16, v6, -v1, v16 mul:2                           ; d5410010 4c420306
	v_mul_f32_e32 v26, s5, v15                                  ; 10341e05
	v_mul_f32_e32 v27, s6, v15                                  ; 10361e06
	v_mac_f32_e32 v25, v22, v22                                 ; 3e322d16
	v_max_f32_e32 v17, 0, v17                                   ; 20222280
	v_mad_f32 v1, v6, -v16, -v1                                 ; d5410001 c4062106
	v_mad_f32 v2, v7, -v16, -v2                                 ; d5410002 c40a2107
	v_mad_f32 v16, v8, -v16, -v9                                ; d5410010 c4262108
	v_rsq_f32_e32 v25, v25                                      ; 7e325d19
	v_mul_f32_e32 v18, v18, v17                                 ; 10242312
	v_mul_f32_e32 v19, v19, v17                                 ; 10262313
	v_mul_f32_e32 v20, v20, v17                                 ; 10282314
	v_mul_f32_e32 v23, v23, v25                                 ; 102e3317
	v_mul_f32_e32 v22, v22, v25                                 ; 102c3316
	v_mul_f32_e32 v24, v24, v25                                 ; 10303318
	v_sub_f32_e32 v0, s9, v4                                    ; 08000809
	v_mul_f32_e32 v16, v16, v24                                 ; 10203110
	v_mac_f32_e32 v16, v2, v23                                  ; 3e202f02
	v_mul_f32_e32 v2, v0, v0                                    ; 10040100
	v_mac_f32_e32 v16, v1, v22                                  ; 3e202d01
	v_sub_f32_e32 v1, s10, v5                                   ; 08020a0a
	v_max_f32_e32 v16, 0, v16                                   ; 20202080
	v_mac_f32_e32 v2, v1, v1                                    ; 3e040301
	v_log_f32_e32 v16, v16                                      ; 7e204f10
	v_mul_f32_e32 v16, s20, v16                                 ; 10202014
	v_exp_f32_e32 v16, v16                                      ; 7e204b10
	v_mac_f32_e32 v18, v21, v16                                 ; 3e242115
	v_mac_f32_e32 v20, v27, v16                                 ; 3e28211b
	v_sub_f32_e32 v27, s8, v3                                   ; 08360608
	v_mac_f32_e32 v19, v26, v16                                 ; 3e26211a
	v_mul_f32_e32 v17, s12, v12                                 ; 1022180c
	v_mul_f32_e32 v21, s14, v14                                 ; 102a1c0e
	v_mul_f32_e32 v18, v10, v18                                 ; 1024250a
	v_mac_f32_e32 v2, v27, v27                                  ; 3e04371b
	v_mul_f32_e32 v19, v10, v19                                 ; 1026270a
	v_mul_f32_e32 v10, v10, v20                                 ; 1014290a
	v_mul_f32_e32 v20, s13, v13                                 ; 10281a0d
	v_rsq_f32_e32 v9, v2                                        ; 7e125d02
	v_add_f32_e32 v2, 1.0, v2                                   ; 060404f2
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_mul_f32_e32 v1, v1, v9                                    ; 10021301
	v_mul_f32_e32 v0, v0, v9                                    ; 10001300
	v_mul_f32_e32 v27, v27, v9                                  ; 1036131b
	v_mul_f32_e32 v11, v8, v1                                   ; 10160308
	v_mul_f32_e32 v25, s12, v15                                 ; 10321e0c
	v_mul_f32_e32 v26, s13, v15                                 ; 10341e0d
	v_mul_f32_e32 v2, s15, v2                                   ; 1004040f
	v_mad_f32 v16, v7, v0, v11                                  ; d5410010 042e0107
	v_mad_f32 v11, v7, -v0, -v11                                ; d541000b c42e0107
	v_mac_f32_e32 v16, v6, v27                                  ; 3e203706
	v_mad_f32 v11, v6, -v27, v11 mul:2                          ; d541000b 4c2e3706
	v_max_f32_e32 v16, 0, v16                                   ; 20202080
	v_mad_f32 v27, v6, -v11, -v27                               ; d541001b c46e1706
	v_mad_f32 v0, v7, -v11, -v0                                 ; d5410000 c4021707
	v_mad_f32 v11, v8, -v11, -v1                                ; d541000b c4061708
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v21, v21, v16                                 ; 102a2115
	v_mul_f32_e32 v20, v20, v16                                 ; 10282114
	v_mul_f32_e32 v11, v11, v24                                 ; 1016310b
	v_mac_f32_e32 v18, v17, v2                                  ; 3e240511
	v_mac_f32_e32 v10, v21, v2                                  ; 3e140515
	v_mac_f32_e32 v19, v20, v2                                  ; 3e260514
	v_sub_f32_e32 v1, s50, v5                                   ; 08020a32
	v_mac_f32_e32 v11, v0, v23                                  ; 3e162f00
	v_sub_f32_e32 v0, s49, v4                                   ; 08000831
	v_mac_f32_e32 v11, v27, v22                                 ; 3e162d1b
	v_mul_f32_e32 v27, s14, v15                                 ; 10361e0e
	v_max_f32_e32 v11, 0, v11                                   ; 20161680
	v_log_f32_e32 v11, v11                                      ; 7e164f0b
	v_mul_f32_e32 v11, s20, v11                                 ; 10161614
	v_exp_f32_e32 v11, v11                                      ; 7e164b0b
	v_mul_f32_e32 v26, v26, v11                                 ; 1034171a
	v_mul_f32_e32 v27, v27, v11                                 ; 1036171b
	v_mul_f32_e32 v25, v25, v11                                 ; 10321719
	v_mac_f32_e32 v19, v26, v2                                  ; 3e26051a
	v_mac_f32_e32 v10, v27, v2                                  ; 3e14051b
	v_sub_f32_e32 v27, s48, v3                                  ; 08360630
	v_mul_f32_e32 v17, s52, v12                                 ; 10221834
	v_mac_f32_e32 v18, v25, v2                                  ; 3e240519
	v_mul_f32_e32 v2, v0, v0                                    ; 10040100
	v_mul_f32_e32 v20, s53, v13                                 ; 10281a35
	v_mul_f32_e32 v21, s54, v14                                 ; 102a1c36
	v_mac_f32_e32 v2, v1, v1                                    ; 3e040301
	v_mac_f32_e32 v2, v27, v27                                  ; 3e04371b
	v_rsq_f32_e32 v9, v2                                        ; 7e125d02
	v_add_f32_e32 v2, 1.0, v2                                   ; 060404f2
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_mul_f32_e32 v27, v27, v9                                  ; 1036131b
	v_mul_f32_e32 v1, v1, v9                                    ; 10021301
	v_mul_f32_e32 v0, v0, v9                                    ; 10001300
	v_mul_f32_e32 v11, v8, v1                                   ; 10160308
	v_mul_f32_e32 v25, s52, v15                                 ; 10321e34
	v_mul_f32_e32 v26, s53, v15                                 ; 10341e35
	v_mul_f32_e32 v2, s55, v2                                   ; 10040437
	v_mad_f32 v16, v7, v0, v11                                  ; d5410010 042e0107
	v_mad_f32 v11, v7, -v0, -v11                                ; d541000b c42e0107
	v_mac_f32_e32 v16, v6, v27                                  ; 3e203706
	v_mad_f32 v11, v6, -v27, v11 mul:2                          ; d541000b 4c2e3706
	v_max_f32_e32 v16, 0, v16                                   ; 20202080
	v_mad_f32 v27, v6, -v11, -v27                               ; d541001b c46e1706
	v_mad_f32 v0, v7, -v11, -v0                                 ; d5410000 c4021707
	v_mad_f32 v11, v8, -v11, -v1                                ; d541000b c4061708
	v_mul_f32_e32 v21, v21, v16                                 ; 102a2115
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v20, v20, v16                                 ; 10282114
	v_mul_f32_e32 v11, v11, v24                                 ; 1016310b
	v_mac_f32_e32 v10, v21, v2                                  ; 3e140515
	v_mac_f32_e32 v18, v17, v2                                  ; 3e240511
	v_mac_f32_e32 v19, v20, v2                                  ; 3e260514
	v_sub_f32_e32 v1, s58, v5                                   ; 08020a3a
	v_mac_f32_e32 v11, v0, v23                                  ; 3e162f00
	v_sub_f32_e32 v0, s57, v4                                   ; 08000839
	v_mac_f32_e32 v11, v27, v22                                 ; 3e162d1b
	v_mul_f32_e32 v27, s54, v15                                 ; 10361e36
	v_max_f32_e32 v11, 0, v11                                   ; 20161680
	s_buffer_load_dwordx16 s[0:15], s[44:47], 0x80              ; f4300016 fa000080
	v_log_f32_e32 v11, v11                                      ; 7e164f0b
	v_mul_f32_e32 v11, s20, v11                                 ; 10161614
	v_exp_f32_e32 v11, v11                                      ; 7e164b0b
	v_mul_f32_e32 v26, v26, v11                                 ; 1034171a
	v_mul_f32_e32 v25, v25, v11                                 ; 10321719
	v_mul_f32_e32 v27, v27, v11                                 ; 1036171b
	v_mac_f32_e32 v19, v26, v2                                  ; 3e26051a
	v_mac_f32_e32 v18, v25, v2                                  ; 3e240519
	v_mac_f32_e32 v10, v27, v2                                  ; 3e14051b
	v_sub_f32_e32 v27, s56, v3                                  ; 08360638
	v_mul_f32_e32 v2, v0, v0                                    ; 10040100
	v_mul_f32_e32 v17, s60, v12                                 ; 1022183c
	v_mul_f32_e32 v20, s61, v13                                 ; 10281a3d
	v_mul_f32_e32 v21, s62, v14                                 ; 102a1c3e
	v_mac_f32_e32 v2, v1, v1                                    ; 3e040301
	v_mac_f32_e32 v2, v27, v27                                  ; 3e04371b
	v_rsq_f32_e32 v9, v2                                        ; 7e125d02
	v_add_f32_e32 v2, 1.0, v2                                   ; 060404f2
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_mul_f32_e32 v27, v27, v9                                  ; 1036131b
	v_mul_f32_e32 v0, v0, v9                                    ; 10001300
	v_mul_f32_e32 v1, v1, v9                                    ; 10021301
	v_mul_f32_e32 v11, v8, v1                                   ; 10160308
	v_mul_f32_e32 v25, s60, v15                                 ; 10321e3c
	v_mul_f32_e32 v2, s63, v2                                   ; 1004043f
	v_mul_f32_e32 v26, s61, v15                                 ; 10341e3d
	v_mad_f32 v16, v7, v0, v11                                  ; d5410010 042e0107
	v_mad_f32 v11, v7, -v0, -v11                                ; d541000b c42e0107
	v_mac_f32_e32 v16, v6, v27                                  ; 3e203706
	v_mad_f32 v11, v6, -v27, v11 mul:2                          ; d541000b 4c2e3706
	v_max_f32_e32 v16, 0, v16                                   ; 20202080
	v_mad_f32 v27, v6, -v11, -v27                               ; d541001b c46e1706
	v_mad_f32 v0, v7, -v11, -v0                                 ; d5410000 c4021707
	v_mad_f32 v11, v8, -v11, -v1                                ; d541000b c4061708
	v_mul_f32_e32 v20, v20, v16                                 ; 10282114
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v21, v21, v16                                 ; 102a2115
	v_mul_f32_e32 v11, v11, v24                                 ; 1016310b
	v_mac_f32_e32 v19, v20, v2                                  ; 3e260514
	v_mac_f32_e32 v18, v17, v2                                  ; 3e240511
	v_mac_f32_e32 v10, v21, v2                                  ; 3e140515
	v_mac_f32_e32 v11, v0, v23                                  ; 3e162f00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e32 v0, s1, v4                                    ; 08000801
	v_sub_f32_e32 v1, s2, v5                                    ; 08020a02
	v_mac_f32_e32 v11, v27, v22                                 ; 3e162d1b
	v_mul_f32_e32 v27, s62, v15                                 ; 10361e3e
	v_max_f32_e32 v11, 0, v11                                   ; 20161680
	v_log_f32_e32 v11, v11                                      ; 7e164f0b
	v_mul_f32_e32 v11, s20, v11                                 ; 10161614
	v_exp_f32_e32 v11, v11                                      ; 7e164b0b
	v_mul_f32_e32 v26, v26, v11                                 ; 1034171a
	v_mul_f32_e32 v27, v27, v11                                 ; 1036171b
	v_mul_f32_e32 v25, v25, v11                                 ; 10321719
	v_mac_f32_e32 v19, v26, v2                                  ; 3e26051a
	v_mac_f32_e32 v10, v27, v2                                  ; 3e14051b
	v_sub_f32_e32 v27, s0, v3                                   ; 08360600
	v_mul_f32_e32 v17, s4, v12                                  ; 10221804
	v_mac_f32_e32 v18, v25, v2                                  ; 3e240519
	v_mul_f32_e32 v2, v0, v0                                    ; 10040100
	v_mul_f32_e32 v20, s5, v13                                  ; 10281a05
	v_mul_f32_e32 v21, s6, v14                                  ; 102a1c06
	v_mac_f32_e32 v2, v1, v1                                    ; 3e040301
	v_mac_f32_e32 v2, v27, v27                                  ; 3e04371b
	v_rsq_f32_e32 v9, v2                                        ; 7e125d02
	v_add_f32_e32 v2, 1.0, v2                                   ; 060404f2
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_mul_f32_e32 v27, v27, v9                                  ; 1036131b
	v_mul_f32_e32 v0, v0, v9                                    ; 10001300
	v_mul_f32_e32 v1, v1, v9                                    ; 10021301
	v_mul_f32_e32 v11, v8, v1                                   ; 10160308
	v_mul_f32_e32 v25, s4, v15                                  ; 10321e04
	v_mul_f32_e32 v2, s7, v2                                    ; 10040407
	v_mul_f32_e32 v26, s5, v15                                  ; 10341e05
	v_mad_f32 v16, v7, v0, v11                                  ; d5410010 042e0107
	v_mad_f32 v11, v7, -v0, -v11                                ; d541000b c42e0107
	v_mac_f32_e32 v16, v6, v27                                  ; 3e203706
	v_mad_f32 v11, v6, -v27, v11 mul:2                          ; d541000b 4c2e3706
	v_max_f32_e32 v16, 0, v16                                   ; 20202080
	v_mad_f32 v0, v7, -v11, -v0                                 ; d5410000 c4021707
	v_mad_f32 v27, v6, -v11, -v27                               ; d541001b c46e1706
	v_mad_f32 v11, v8, -v11, -v1                                ; d541000b c4061708
	v_mul_f32_e32 v20, v20, v16                                 ; 10282114
	v_mul_f32_e32 v21, v21, v16                                 ; 102a2115
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v11, v11, v24                                 ; 1016310b
	v_mac_f32_e32 v19, v20, v2                                  ; 3e260514
	v_sub_f32_e32 v3, s8, v3                                    ; 08060608
	v_mac_f32_e32 v10, v21, v2                                  ; 3e140515
	v_sub_f32_e32 v4, s9, v4                                    ; 08080809
	v_mac_f32_e32 v18, v17, v2                                  ; 3e240511
	v_sub_f32_e32 v5, s10, v5                                   ; 080a0a0a
	v_mac_f32_e32 v11, v0, v23                                  ; 3e162f00
	v_mac_f32_e32 v11, v27, v22                                 ; 3e162d1b
	v_mul_f32_e32 v27, s6, v15                                  ; 10361e06
	v_max_f32_e32 v11, 0, v11                                   ; 20161680
	v_log_f32_e32 v11, v11                                      ; 7e164f0b
	v_mul_f32_e32 v11, s20, v11                                 ; 10161614
	v_exp_f32_e32 v11, v11                                      ; 7e164b0b
	v_mul_f32_e32 v27, v27, v11                                 ; 1036171b
	v_mul_f32_e32 v26, v26, v11                                 ; 1034171a
	v_mul_f32_e32 v25, v25, v11                                 ; 10321719
	v_mac_f32_e32 v10, v27, v2                                  ; 3e14051b
	v_mul_f32_e32 v27, v4, v4                                   ; 10360904
	v_mul_f32_e32 v12, s12, v12                                 ; 1018180c
	v_mac_f32_e32 v19, v26, v2                                  ; 3e26051a
	v_mul_f32_e32 v13, s13, v13                                 ; 101a1a0d
	v_mac_f32_e32 v18, v25, v2                                  ; 3e240519
	v_mul_f32_e32 v14, s14, v14                                 ; 101c1c0e
	v_mac_f32_e32 v27, v5, v5                                   ; 3e360b05
	v_mac_f32_e32 v27, v3, v3                                   ; 3e360703
	v_rsq_f32_e32 v0, v27                                       ; 7e005d1b
	v_add_f32_e32 v27, 1.0, v27                                 ; 063636f2
	v_rcp_f32_e32 v27, v27                                      ; 7e36551b
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v3, v3, v0                                    ; 10060103
	v_mul_f32_e32 v1, v8, v5                                    ; 10020b08
	v_mul_f32_e32 v27, s15, v27                                 ; 1036360f
	v_mad_f32 v2, v7, v4, v1                                    ; d5410002 04060907
	v_mad_f32 v1, v7, -v4, -v1                                  ; d5410001 c4060907
	v_mac_f32_e32 v2, v6, v3                                    ; 3e040706
	v_mad_f32 v1, v6, -v3, v1 mul:2                             ; d5410001 4c060706
	v_max_f32_e32 v2, 0, v2                                     ; 20040480
	v_mad_f32 v6, v6, -v1, -v3                                  ; d5410006 c40e0306
	v_mul_f32_e32 v3, s12, v15                                  ; 10061e0c
	v_mad_f32 v8, v8, -v1, -v5                                  ; d5410008 c4160308
	v_mad_f32 v7, v7, -v1, -v4                                  ; d5410007 c4120307
	v_mul_f32_e32 v4, s13, v15                                  ; 10081e0d
	v_mul_f32_e32 v15, s14, v15                                 ; 101e1e0e
	v_mul_f32_e32 v12, v12, v2                                  ; 1018050c
	v_mul_f32_e32 v14, v14, v2                                  ; 101c050e
	v_mul_f32_e32 v13, v13, v2                                  ; 101a050d
	v_mul_f32_e32 v8, v8, v24                                   ; 10103108
	v_mac_f32_e32 v18, v12, v27                                 ; 3e24370c
	v_mad_f32 v5, v14, v27, v10                                 ; d5410005 042a370e
	v_mac_f32_e32 v19, v13, v27                                 ; 3e26370d
	v_mac_f32_e32 v8, v7, v23                                   ; 3e102f07
	v_mac_f32_e32 v8, v6, v22                                   ; 3e102d06
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_log_f32_e32 v8, v8                                        ; 7e104f08
	v_mul_f32_e32 v8, s20, v8                                   ; 10101014
	v_exp_f32_e32 v8, v8                                        ; 7e104b08
	v_mul_f32_e32 v4, v4, v8                                    ; 10081104
	v_mul_f32_e32 v3, v3, v8                                    ; 10061103
	v_mul_f32_e32 v15, v15, v8                                  ; 101e110f
	v_mad_f32 v4, v4, v27, v19                                  ; d5410004 044e3704
	v_mad_f32 v3, v3, v27, v18                                  ; d5410003 044a3703
	v_mac_f32_e32 v5, v15, v27                                  ; 3e0a370f
BB3:
	v_cvt_pkrtz_f16_f32_e32 v3, v3, v4                          ; 5e060903
	v_cvt_pkrtz_f16_f32_e64 v5, v5, 1.0                         ; d52f0005 0001e505
	exp mrt0 v3, v3, v5, v5 done compr vm                       ; f8001c0f 80800503
	s_endpgm                                                    ; bf810000
