# Tessellation Evaluation Shader as ESGS
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_barrier                                                   ; bf8a0000
	s_and_b32 s5, s3, 0xf000000                                 ; 8705ff03 0f000000
	s_cbranch_scc1 BB3                                          ; bf850007
BB1:
	s_bfe_u32 s5, s2, 0x90016                                   ; 9385ff02 00090016
	s_lshl_b32 s5, s5, 12                                       ; 8f058c05
	s_bfe_u32 s2, s2, 0x9000c                                   ; 9382ff02 0009000c
	s_or_b32 m0, s5, s2                                         ; 887c0205
	s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)                         ; bf900009
BB3:
	s_lshl_b32 s2, s3, 8                                        ; 8f028803
	s_bfe_u64 exec, -1, s2                                      ; 94fe02c1
	s_cbranch_execz BB9                                         ; bf880002
BB4:
	exp prim v0, off, off, off done                             ; f8000941 80808000
BB9:
	s_pack_ll_b32_b16 s3, 0, s3                                 ; 99030380
	s_waitcnt expcnt(0)                                         ; bf8cff0f
	s_bfe_u64 exec, -1, s3                                      ; 94fe03c1
	s_cbranch_execz BB15                                        ; bf8800f3
BB10:
	s_mov_b32 s2, s9                                            ; be820309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx4 s[28:31], s[8:9], null                       ; f4080704 fa000000
	s_load_dwordx4 s[32:35], s[0:1], 0x60                       ; f4080800 fa000060
	v_mul_u32_u24_e32 v7, 48, v7                                ; 160e0eb0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x2                                                ; bfa10002
	buffer_load_dwordx3 v[0:2], v7, s[32:35], s4 offen glc dlc  ; e03cd000 04080007
	buffer_load_dwordx3 v[8:10], v7, s[32:35], s4 offen offset:16 glc dlc ; e03cd010 04080807
	buffer_load_dwordx3 v[11:13], v7, s[32:35], s4 offen offset:32 glc dlc ; e03cd020 04080b07
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[32:47], s[28:31], 0x40             ; f430080e fa000040
	s_buffer_load_dwordx16 s[48:63], s[28:31], null             ; f4300c0e fa000000
	v_add_f32_e32 v14, v5, v6                                   ; 061c0d05
	v_sub_f32_e32 v14, 1.0, v14                                 ; 081c1cf2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v15, s60, s35                                 ; d508000f 0000463c
	v_mul_f32_e64 v16, s61, s35                                 ; d5080010 0000463d
	v_mul_f32_e64 v17, s62, s35                                 ; d5080011 0000463e
	v_mul_f32_e64 v18, s63, s35                                 ; d5080012 0000463f
	v_mad_f32 v15, s56, s34, v15                                ; d541000f 043c4438
	v_mad_f32 v16, s57, s34, v16                                ; d5410010 04404439
	v_mad_f32 v17, s58, s34, v17                                ; d5410011 0444443a
	v_mad_f32 v18, s59, s34, v18                                ; d5410012 0448443b
	v_mad_f32 v15, s52, s33, v15                                ; d541000f 043c4234
	v_mad_f32 v16, s53, s33, v16                                ; d5410010 04404235
	v_mul_f32_e64 v19, s60, s39                                 ; d5080013 00004e3c
	v_mad_f32 v17, s54, s33, v17                                ; d5410011 04444236
	v_mul_f32_e64 v20, s61, s39                                 ; d5080014 00004e3d
	v_mad_f32 v18, s55, s33, v18                                ; d5410012 04484237
	v_mul_f32_e64 v21, s62, s39                                 ; d5080015 00004e3e
	v_mul_f32_e64 v22, s63, s39                                 ; d5080016 00004e3f
	v_mad_f32 v15, s48, s32, v15                                ; d541000f 043c4030
	v_mad_f32 v16, s49, s32, v16                                ; d5410010 04404031
	v_mad_f32 v19, s56, s38, v19                                ; d5410013 044c4c38
	v_mad_f32 v17, s50, s32, v17                                ; d5410011 04444032
	v_mad_f32 v20, s57, s38, v20                                ; d5410014 04504c39
	v_mad_f32 v18, s51, s32, v18                                ; d5410012 04484033
	v_mad_f32 v21, s58, s38, v21                                ; d5410015 04544c3a
	v_mad_f32 v22, s59, s38, v22                                ; d5410016 04584c3b
	v_mad_f32 v19, s52, s37, v19                                ; d5410013 044c4a34
	v_mad_f32 v20, s53, s37, v20                                ; d5410014 04504a35
	v_mul_f32_e64 v23, s60, s43                                 ; d5080017 0000563c
	v_mad_f32 v21, s54, s37, v21                                ; d5410015 04544a36
	v_mul_f32_e64 v24, s61, s43                                 ; d5080018 0000563d
	v_mul_f32_e64 v25, s62, s43                                 ; d5080019 0000563e
	v_mad_f32 v22, s55, s37, v22                                ; d5410016 04584a37
	v_mad_f32 v19, s48, s36, v19                                ; d5410013 044c4830
	v_mul_f32_e64 v26, s63, s43                                 ; d508001a 0000563f
	v_mad_f32 v20, s49, s36, v20                                ; d5410014 04504831
	v_mad_f32 v23, s56, s42, v23                                ; d5410017 045c5438
	v_mad_f32 v21, s50, s36, v21                                ; d5410015 04544832
	v_mad_f32 v24, s57, s42, v24                                ; d5410018 04605439
	v_mad_f32 v25, s58, s42, v25                                ; d5410019 0464543a
	v_mad_f32 v22, s51, s36, v22                                ; d5410016 04584833
	v_mad_f32 v26, s59, s42, v26                                ; d541001a 0468543b
	v_mad_f32 v23, s52, s41, v23                                ; d5410017 045c5234
	v_mad_f32 v24, s53, s41, v24                                ; d5410018 04605235
	v_mul_f32_e64 v27, s60, s47                                 ; d508001b 00005e3c
	v_mad_f32 v25, s54, s41, v25                                ; d5410019 04645236
	v_mul_f32_e64 v28, s61, s47                                 ; d508001c 00005e3d
	v_mad_f32 v26, s55, s41, v26                                ; d541001a 04685237
	v_mul_f32_e64 v29, s62, s47                                 ; d508001d 00005e3e
	v_mul_f32_e64 v30, s63, s47                                 ; d508001e 00005e3f
	v_mad_f32 v23, s48, s40, v23                                ; d5410017 045c5030
	v_mad_f32 v24, s49, s40, v24                                ; d5410018 04605031
	v_mad_f32 v27, s56, s46, v27                                ; d541001b 046c5c38
	v_mad_f32 v25, s50, s40, v25                                ; d5410019 04645032
	v_mad_f32 v28, s57, s46, v28                                ; d541001c 04705c39
	v_mad_f32 v26, s51, s40, v26                                ; d541001a 04685033
	v_mad_f32 v29, s58, s46, v29                                ; d541001d 04745c3a
	v_mad_f32 v30, s59, s46, v30                                ; d541001e 04785c3b
	v_mad_f32 v27, s52, s45, v27                                ; d541001b 046c5a34
	v_mad_f32 v28, s53, s45, v28                                ; d541001c 04705a35
	v_mad_f32 v29, s54, s45, v29                                ; d541001d 04745a36
	v_mad_f32 v30, s55, s45, v30                                ; d541001e 04785a37
	v_mad_f32 v27, s48, s44, v27                                ; d541001b 046c5830
	v_mad_f32 v28, s49, s44, v28                                ; d541001c 04705831
	v_mad_f32 v29, s50, s44, v29                                ; d541001d 04745832
	v_mad_f32 v30, s51, s44, v30                                ; d541001e 04785833
	v_mul_f32_e32 v31, s12, v27                                 ; 103e360c
	v_mul_f32_e32 v3, s12, v29                                  ; 10063a0c
	v_mul_f32_e32 v4, s12, v30                                  ; 10083c0c
	v_mac_f32_e32 v31, s11, v23                                 ; 3e3e2e0b
	v_mac_f32_e32 v3, s11, v25                                  ; 3e06320b
	v_mac_f32_e32 v4, s11, v26                                  ; 3e08340b
	v_mac_f32_e32 v31, s10, v19                                 ; 3e3e260a
	v_mac_f32_e32 v3, s10, v21                                  ; 3e062a0a
	v_mac_f32_e32 v4, s10, v22                                  ; 3e082c0a
	v_mac_f32_e32 v31, s2, v15                                  ; 3e3e1e02
	v_mac_f32_e32 v3, s2, v17                                   ; 3e062202
	v_mul_f32_e32 v7, s16, v28                                  ; 100e3810
	v_mac_f32_e32 v4, s2, v18                                   ; 3e082402
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mul_f32_e32 v0, v5, v0                                    ; 10000105
	v_mul_f32_e32 v1, v5, v1                                    ; 10020305
	v_mul_f32_e32 v5, v5, v2                                    ; 100a0505
	v_mul_f32_e32 v2, s12, v28                                  ; 1004380c
	v_mac_f32_e32 v7, s15, v24                                  ; 3e0e300f
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v0, v6, v8                                    ; 3e001106
	v_mul_f32_e32 v8, s16, v29                                  ; 10103a10
	v_mac_f32_e32 v1, v6, v9                                    ; 3e021306
	v_mul_f32_e32 v9, s16, v30                                  ; 10123c10
	v_mac_f32_e32 v5, v6, v10                                   ; 3e0a1506
	v_mul_f32_e32 v6, s16, v27                                  ; 100c3610
	v_mac_f32_e32 v2, s11, v24                                  ; 3e04300b
	v_mac_f32_e32 v7, s14, v20                                  ; 3e0e280e
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v0, v14, v11                                  ; 3e00170e
	v_mac_f32_e32 v8, s15, v25                                  ; 3e10320f
	v_mac_f32_e32 v1, v14, v12                                  ; 3e02190e
	v_mul_f32_e32 v10, s20, v27                                 ; 10143614
	v_mul_f32_e32 v11, s20, v28                                 ; 10163814
	v_mac_f32_e32 v9, s15, v26                                  ; 3e12340f
	v_mac_f32_e32 v5, v14, v13                                  ; 3e0a1b0e
	v_mul_f32_e32 v12, s20, v29                                 ; 10183a14
	v_mul_f32_e32 v13, s20, v30                                 ; 101a3c14
	v_mac_f32_e32 v6, s15, v23                                  ; 3e0c2e0f
	v_mac_f32_e32 v2, s10, v20                                  ; 3e04280a
	v_mac_f32_e32 v7, s13, v16                                  ; 3e0e200d
	v_mac_f32_e32 v8, s14, v21                                  ; 3e102a0e
	v_mac_f32_e32 v10, s19, v23                                 ; 3e142e13
	v_mac_f32_e32 v11, s19, v24                                 ; 3e163013
	v_mac_f32_e32 v9, s14, v22                                  ; 3e122c0e
	v_mac_f32_e32 v12, s19, v25                                 ; 3e183213
	v_mac_f32_e32 v13, s19, v26                                 ; 3e1a3413
	v_mac_f32_e32 v6, s14, v19                                  ; 3e0c260e
	v_mul_f32_e32 v27, s24, v27                                 ; 10363618
	v_mac_f32_e32 v2, s2, v16                                   ; 3e042002
	v_mul_f32_e32 v28, s24, v28                                 ; 10383818
	v_mul_f32_e32 v29, s24, v29                                 ; 103a3a18
	v_mac_f32_e32 v8, s13, v17                                  ; 3e10220d
	v_mul_f32_e32 v30, s24, v30                                 ; 103c3c18
	v_mac_f32_e32 v10, s18, v19                                 ; 3e142612
	v_mac_f32_e32 v11, s18, v20                                 ; 3e162812
	v_mac_f32_e32 v9, s13, v18                                  ; 3e12240d
	v_mac_f32_e32 v12, s18, v21                                 ; 3e182a12
	v_mac_f32_e32 v13, s18, v22                                 ; 3e1a2c12
	v_mac_f32_e32 v6, s13, v15                                  ; 3e0c1e0d
	v_mac_f32_e32 v27, s23, v23                                 ; 3e362e17
	v_mac_f32_e32 v28, s23, v24                                 ; 3e383017
	v_mac_f32_e32 v29, s23, v25                                 ; 3e3a3217
	v_mac_f32_e32 v30, s23, v26                                 ; 3e3c3417
	v_mac_f32_e32 v10, s17, v15                                 ; 3e141e11
	v_mac_f32_e32 v11, s17, v16                                 ; 3e162011
	v_mac_f32_e32 v12, s17, v17                                 ; 3e182211
	v_mac_f32_e32 v13, s17, v18                                 ; 3e1a2411
	v_mac_f32_e32 v27, s22, v19                                 ; 3e362616
	v_mac_f32_e32 v28, s22, v20                                 ; 3e382816
	v_mac_f32_e32 v29, s22, v21                                 ; 3e3a2a16
	v_mac_f32_e32 v30, s22, v22                                 ; 3e3c2c16
	v_mac_f32_e32 v27, s21, v15                                 ; 3e361e15
	v_mac_f32_e32 v28, s21, v16                                 ; 3e382015
	v_mac_f32_e32 v29, s21, v17                                 ; 3e3a2215
	v_mac_f32_e32 v30, s21, v18                                 ; 3e3c2415
	v_mac_f32_e32 v27, v10, v5                                  ; 3e360b0a
	v_mac_f32_e32 v28, v11, v5                                  ; 3e380b0b
	v_mac_f32_e32 v29, v12, v5                                  ; 3e3a0b0c
	v_mac_f32_e32 v30, v13, v5                                  ; 3e3c0b0d
	v_mac_f32_e32 v27, v6, v1                                   ; 3e360306
	v_mac_f32_e32 v28, v7, v1                                   ; 3e380307
	v_mac_f32_e32 v29, v8, v1                                   ; 3e3a0308
	v_mac_f32_e32 v30, v9, v1                                   ; 3e3c0309
	v_mac_f32_e32 v27, v31, v0                                  ; 3e36011f
	v_mac_f32_e32 v28, v2, v0                                   ; 3e380102
	v_mac_f32_e32 v29, v3, v0                                   ; 3e3a0103
	v_mac_f32_e32 v30, v4, v0                                   ; 3e3c0104
	exp pos0 v27, v28, v29, v30 done vm                         ; f80018cf 1e1d1c1b
BB15:
	s_endpgm                                                    ; bf810000
