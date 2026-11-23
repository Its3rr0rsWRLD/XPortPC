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
	s_cbranch_execz BB15                                        ; bf8800ff
BB10:
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[16:23], s[8:9], 0x20                       ; f40c0404 fa000020
	s_load_dwordx4 s[12:15], s[8:9], 0x70                       ; f4080304 fa000070
	s_load_dwordx4 s[0:3], s[0:1], 0x60                         ; f4080000 fa000060
	v_lshlrev_b32_e32 v7, 6, v7                                 ; 340e0e86
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x7                                                ; bfa10007
	buffer_load_dwordx4 v[0:3], v7, s[0:3], s4 offen offset:3072 glc dlc ; e038dc00 04000007
	buffer_load_dwordx4 v[8:11], v7, s[0:3], s4 offen offset:3088 glc dlc ; e038dc10 04000807
	buffer_load_dwordx4 v[12:15], v7, s[0:3], s4 offen offset:3104 glc dlc ; e038dc20 04000c07
	buffer_load_dwordx4 v[16:19], v7, s[0:3], s4 offen offset:3120 glc dlc ; e038dc30 04001007
	buffer_load_dwordx4 v[20:23], v7, s[0:3], s4 offen glc dlc  ; e038d000 04001407
	buffer_load_dwordx4 v[24:27], v7, s[0:3], s4 offen offset:16 glc dlc ; e038d010 04001807
	buffer_load_dwordx4 v[28:31], v7, s[0:3], s4 offen offset:48 glc dlc ; e038d030 04001c07
	buffer_load_dwordx4 v[32:35], v7, s[0:3], s4 offen offset:32 glc dlc ; e038d020 04002007
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_sub_f32_e32 v10, v10, v2                                  ; 0814050a
	v_sub_f32_e32 v11, v11, v3                                  ; 0816070b
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_sub_f32_e32 v14, v14, v18                                 ; 081c250e
	v_sub_f32_e32 v15, v15, v19                                 ; 081e270f
	v_mac_f32_e32 v2, v5, v10                                   ; 3e041505
	v_mac_f32_e32 v3, v5, v11                                   ; 3e061705
	v_mac_f32_e32 v18, v5, v14                                  ; 3e241d05
	v_mac_f32_e32 v19, v5, v15                                  ; 3e261f05
	v_sub_f32_e32 v18, v18, v2                                  ; 08240512
	v_sub_f32_e32 v19, v19, v3                                  ; 08260713
	v_mac_f32_e32 v2, v6, v18                                   ; 3e042506
	v_mac_f32_e32 v3, v6, v19                                   ; 3e062706
	image_sample_lz v4, v[2:3], s[16:23], s[12:15] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f09c0108 00640402
	s_load_dwordx4 s[0:3], s[8:9], null                         ; f4080004 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s4, s[0:3], 0xf0                        ; f4200100 fa0000f0
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[16:31], s[0:3], 0x40               ; f4300400 fa000040
	s_buffer_load_dwordx16 s[32:47], s[0:3], null               ; f4300800 fa000000
	v_sub_f32_e32 v8, v8, v0                                    ; 08100108
	v_sub_f32_e32 v9, v9, v1                                    ; 08120309
	v_sub_f32_e32 v12, v12, v16                                 ; 0818210c
	v_sub_f32_e32 v13, v13, v17                                 ; 081a230d
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_sub_f32_e32 v27, v27, v23                                 ; 08362f1b
	v_sub_f32_e32 v24, v24, v20                                 ; 08302918
	v_sub_f32_e32 v25, v25, v21                                 ; 08322b19
	v_sub_f32_e32 v26, v26, v22                                 ; 08342d1a
	v_mac_f32_e32 v0, v5, v8                                    ; 3e001105
	v_mac_f32_e32 v1, v5, v9                                    ; 3e021305
	v_mac_f32_e32 v16, v5, v12                                  ; 3e201905
	v_mac_f32_e32 v17, v5, v13                                  ; 3e221b05
	v_mac_f32_e32 v23, v5, v27                                  ; 3e2e3705
	v_mac_f32_e32 v20, v5, v24                                  ; 3e283105
	v_mac_f32_e32 v21, v5, v25                                  ; 3e2a3305
	v_mac_f32_e32 v22, v5, v26                                  ; 3e2c3505
	v_sub_f32_e32 v16, v16, v0                                  ; 08200110
	v_sub_f32_e32 v17, v17, v1                                  ; 08220311
	v_mac_f32_e32 v0, v6, v16                                   ; 3e002106
	v_mac_f32_e32 v1, v6, v17                                   ; 3e022306
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v10, s47, s19                                 ; d508000a 0000262f
	v_mul_f32_e64 v7, s44, s19                                  ; d5080007 0000262c
	v_mul_f32_e64 v8, s45, s19                                  ; d5080008 0000262d
	v_mul_f32_e64 v9, s46, s19                                  ; d5080009 0000262e
	v_mul_f32_e64 v11, s44, s23                                 ; d508000b 00002e2c
	v_mul_f32_e64 v12, s45, s23                                 ; d508000c 00002e2d
	v_mul_f32_e64 v13, s46, s23                                 ; d508000d 00002e2e
	v_mul_f32_e64 v14, s47, s23                                 ; d508000e 00002e2f
	v_mad_f32 v10, s43, s18, v10                                ; d541000a 0428242b
	v_mad_f32 v7, s40, s18, v7                                  ; d5410007 041c2428
	s_buffer_load_dwordx4 s[0:3], s[0:3], 0x80                  ; f4280000 fa000080
	v_mad_f32 v8, s41, s18, v8                                  ; d5410008 04202429
	v_mad_f32 v9, s42, s18, v9                                  ; d5410009 0424242a
	v_mad_f32 v11, s40, s22, v11                                ; d541000b 042c2c28
	v_mad_f32 v12, s41, s22, v12                                ; d541000c 04302c29
	v_mad_f32 v13, s42, s22, v13                                ; d541000d 04342c2a
	v_mad_f32 v14, s43, s22, v14                                ; d541000e 04382c2b
	v_mad_f32 v10, s39, s17, v10                                ; d541000a 04282227
	v_mad_f32 v7, s36, s17, v7                                  ; d5410007 041c2224
	v_mad_f32 v8, s37, s17, v8                                  ; d5410008 04202225
	v_mad_f32 v9, s38, s17, v9                                  ; d5410009 04242226
	v_mul_f32_e64 v15, s44, s27                                 ; d508000f 0000362c
	v_mad_f32 v11, s36, s21, v11                                ; d541000b 042c2a24
	v_mul_f32_e64 v16, s45, s27                                 ; d5080010 0000362d
	v_mad_f32 v12, s37, s21, v12                                ; d541000c 04302a25
	v_mul_f32_e64 v17, s46, s27                                 ; d5080011 0000362e
	v_mul_f32_e64 v18, s47, s27                                 ; d5080012 0000362f
	v_mad_f32 v13, s38, s21, v13                                ; d541000d 04342a26
	v_mad_f32 v14, s39, s21, v14                                ; d541000e 04382a27
	v_mad_f32 v10, s35, s16, v10                                ; d541000a 04282023
	v_mad_f32 v7, s32, s16, v7                                  ; d5410007 041c2020
	v_mad_f32 v8, s33, s16, v8                                  ; d5410008 04202021
	v_mad_f32 v9, s34, s16, v9                                  ; d5410009 04242022
	v_mad_f32 v15, s40, s26, v15                                ; d541000f 043c3428
	v_mad_f32 v11, s32, s20, v11                                ; d541000b 042c2820
	v_mad_f32 v16, s41, s26, v16                                ; d5410010 04403429
	v_mad_f32 v12, s33, s20, v12                                ; d541000c 04302821
	v_mad_f32 v17, s42, s26, v17                                ; d5410011 0444342a
	v_mad_f32 v18, s43, s26, v18                                ; d5410012 0448342b
	v_mad_f32 v13, s34, s20, v13                                ; d541000d 04342822
	v_mul_f32_e64 v19, s44, s31                                 ; d5080013 00003e2c
	v_mad_f32 v14, s35, s20, v14                                ; d541000e 04382823
	v_mul_f32_e64 v24, s45, s31                                 ; d5080018 00003e2d
	v_mul_f32_e64 v25, s46, s31                                 ; d5080019 00003e2e
	v_mul_f32_e64 v26, s47, s31                                 ; d508001a 00003e2f
	v_mad_f32 v15, s36, s25, v15                                ; d541000f 043c3224
	v_mad_f32 v16, s37, s25, v16                                ; d5410010 04403225
	v_mad_f32 v17, s38, s25, v17                                ; d5410011 04443226
	v_mad_f32 v18, s39, s25, v18                                ; d5410012 04483227
	v_mad_f32 v19, s40, s30, v19                                ; d5410013 044c3c28
	v_mad_f32 v24, s41, s30, v24                                ; d5410018 04603c29
	v_mad_f32 v25, s42, s30, v25                                ; d5410019 04643c2a
	v_mad_f32 v26, s43, s30, v26                                ; d541001a 04683c2b
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_sub_f32_e32 v35, v35, v31                                 ; 08463f23
	v_mad_f32 v15, s32, s24, v15                                ; d541000f 043c3020
	v_mad_f32 v16, s33, s24, v16                                ; d5410010 04403021
	v_mad_f32 v17, s34, s24, v17                                ; d5410011 04443022
	v_mad_f32 v18, s35, s24, v18                                ; d5410012 04483023
	v_sub_f32_e32 v32, v32, v28                                 ; 08403920
	v_mad_f32 v19, s36, s29, v19                                ; d5410013 044c3a24
	v_mad_f32 v24, s37, s29, v24                                ; d5410018 04603a25
	v_sub_f32_e32 v33, v33, v29                                 ; 08423b21
	v_mad_f32 v25, s38, s29, v25                                ; d5410019 04643a26
	v_sub_f32_e32 v34, v34, v30                                 ; 08443d22
	v_mad_f32 v26, s39, s29, v26                                ; d541001a 04683a27
	v_mac_f32_e32 v31, v5, v35                                  ; 3e3e4705
	v_mac_f32_e32 v28, v5, v32                                  ; 3e384105
	v_mad_f32 v19, s32, s28, v19                                ; d5410013 044c3820
	v_mad_f32 v24, s33, s28, v24                                ; d5410018 04603821
	v_mac_f32_e32 v29, v5, v33                                  ; 3e3a4305
	v_mad_f32 v25, s34, s28, v25                                ; d5410019 04643822
	v_mac_f32_e32 v30, v5, v34                                  ; 3e3c4505
	v_mad_f32 v26, s35, s28, v26                                ; d541001a 04683823
	v_sub_f32_e32 v31, v31, v23                                 ; 083e2f1f
	v_sub_f32_e32 v28, v28, v20                                 ; 0838291c
	v_sub_f32_e32 v29, v29, v21                                 ; 083a2b1d
	v_sub_f32_e32 v30, v30, v22                                 ; 083c2d1e
	v_mac_f32_e32 v23, v6, v31                                  ; 3e2e3f06
	v_mac_f32_e32 v20, v6, v28                                  ; 3e283906
	v_mac_f32_e32 v21, v6, v29                                  ; 3e2a3b06
	v_mac_f32_e32 v22, v6, v30                                  ; 3e2c3d06
	v_mac_f32_e32 v26, v18, v22                                 ; 3e342d12
	v_mac_f32_e32 v19, v15, v22                                 ; 3e262d0f
	v_mac_f32_e32 v24, v16, v22                                 ; 3e302d10
	v_mac_f32_e32 v25, v17, v22                                 ; 3e322d11
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e32 v22, s2, v22                                  ; 082c2c02
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v4, s4, -v4, v21                                  ; d5410004 44560804
	v_mac_f32_e32 v24, v12, v4                                  ; 3e30090c
	v_mac_f32_e32 v19, v11, v4                                  ; 3e26090b
	v_mac_f32_e32 v25, v13, v4                                  ; 3e32090d
	v_mac_f32_e32 v26, v14, v4                                  ; 3e34090e
	v_sub_f32_e32 v4, s1, v4                                    ; 08080801
	v_mac_f32_e32 v24, v8, v20                                  ; 3e302908
	v_mac_f32_e32 v19, v7, v20                                  ; 3e262907
	v_mac_f32_e32 v25, v9, v20                                  ; 3e322909
	v_mac_f32_e32 v26, v10, v20                                 ; 3e34290a
	v_sub_f32_e32 v20, s0, v20                                  ; 08282800
	v_mul_f32_e32 v27, v4, v4                                   ; 10360904
	v_mac_f32_e32 v27, v22, v22                                 ; 3e362d16
	v_mac_f32_e32 v27, v20, v20                                 ; 3e362914
	v_rsq_f32_e32 v27, v27                                      ; 7e365d1b
	v_mul_f32_e32 v22, v22, v27                                 ; 102c3716
	v_mul_f32_e32 v20, v20, v27                                 ; 10283714
	v_mul_f32_e32 v4, v4, v27                                   ; 10083704
	exp pos0 v19, v24, v25, v26 done vm                         ; f80018cf 1a191813
	exp param0 v23, v0, v1, v2                                  ; f800020f 02010017
	exp param1 v3, v20, v4, v22                                 ; f800021f 16041403
BB15:
	s_endpgm                                                    ; bf810000
