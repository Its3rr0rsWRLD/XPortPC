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
	s_cbranch_execz BB15                                        ; bf8800f0
BB10:
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[16:23], s[8:9], 0x20                       ; f40c0404 fa000020
	s_load_dwordx4 s[12:15], s[8:9], 0x70                       ; f4080304 fa000070
	s_load_dwordx4 s[0:3], s[0:1], 0x60                         ; f4080000 fa000060
	v_mul_u32_u24_e32 v7, 48, v7                                ; 160e0eb0
	v_add_nc_u32_e32 v0, 0x1000, v7                             ; 4a000eff 00001000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x8                                                ; bfa10008
	buffer_load_dwordx4 v[8:11], v7, s[0:3], s4 offen glc dlc   ; e038d000 04000807
	buffer_load_dwordx4 v[12:15], v7, s[0:3], s4 offen offset:16 glc dlc ; e038d010 04000c07
	buffer_load_dwordx4 v[16:19], v7, s[0:3], s4 offen offset:32 glc dlc ; e038d020 04001007
	buffer_load_dwordx4 v[20:23], v7, s[0:3], s4 offen offset:3072 glc dlc ; e038dc00 04001407
	buffer_load_dword v1, v0, s[0:3], s4 offen offset:2048 glc dlc ; e030d800 04000100
	buffer_load_dwordx4 v[24:27], v7, s[0:3], s4 offen offset:3088 glc dlc ; e038dc10 04001807
	buffer_load_dword v2, v0, s[0:3], s4 offen offset:2064 glc dlc ; e030d810 04000200
	buffer_load_dwordx4 v[28:31], v7, s[0:3], s4 offen offset:3104 glc dlc ; e038dc20 04001c07
	buffer_load_dword v0, v0, s[0:3], s4 offen offset:2080 glc dlc ; e030d820 04000000
	v_add_f32_e32 v3, v5, v6                                    ; 06060d05
	v_sub_f32_e32 v3, 1.0, v3                                   ; 080606f2
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mul_f32_e32 v23, v23, v5                                  ; 102e0b17
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mul_f32_e32 v1, v1, v5                                    ; 10020b01
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mac_f32_e32 v23, v27, v6                                  ; 3e2e0d1b
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v1, v2, v6                                    ; 3e020d02
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v23, v31, v3                                  ; 3e2e071f
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v1, v0, v3                                    ; 3e020700
	image_sample_lz  v23, [v23, v1], s[16:23], s[12:15] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f09c080a 00641717 00000001
	s_load_dwordx4 s[0:3], s[8:9], null                         ; f4080004 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s4, s[0:3], 0x94                        ; f4200100 fa000094
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[16:31], s[0:3], 0x40               ; f4300400 fa000040
	s_buffer_load_dwordx16 s[32:47], s[0:3], null               ; f4300800 fa000000
	v_mul_f32_e32 v8, v8, v5                                    ; 10100b08
	v_mul_f32_e32 v9, v9, v5                                    ; 10120b09
	v_mul_f32_e32 v10, v10, v5                                  ; 10140b0a
	v_mul_f32_e32 v11, v11, v5                                  ; 10160b0b
	v_mul_f32_e32 v20, v20, v5                                  ; 10280b14
	v_mul_f32_e32 v21, v21, v5                                  ; 102a0b15
	v_mul_f32_e32 v22, v22, v5                                  ; 102c0b16
	v_mac_f32_e32 v8, v12, v6                                   ; 3e100d0c
	v_mac_f32_e32 v9, v13, v6                                   ; 3e120d0d
	v_mac_f32_e32 v10, v14, v6                                  ; 3e140d0e
	v_mac_f32_e32 v11, v15, v6                                  ; 3e160d0f
	v_mac_f32_e32 v20, v24, v6                                  ; 3e280d18
	v_mac_f32_e32 v21, v25, v6                                  ; 3e2a0d19
	v_mac_f32_e32 v22, v26, v6                                  ; 3e2c0d1a
	v_mac_f32_e32 v8, v16, v3                                   ; 3e100710
	v_mac_f32_e32 v9, v17, v3                                   ; 3e120711
	v_mac_f32_e32 v10, v18, v3                                  ; 3e140712
	v_mac_f32_e32 v11, v19, v3                                  ; 3e160713
	v_mac_f32_e32 v20, v28, v3                                  ; 3e28071c
	v_mac_f32_e32 v21, v29, v3                                  ; 3e2a071d
	v_mul_f32_e32 v4, v21, v21                                  ; 10082b15
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v7, s46, s19                                  ; d5080007 0000262e
	v_mul_f32_e64 v12, s47, s19                                 ; d508000c 0000262f
	v_mul_f32_e64 v5, s44, s19                                  ; d5080005 0000262c
	v_mul_f32_e64 v6, s45, s19                                  ; d5080006 0000262d
	v_mul_f32_e64 v13, s44, s23                                 ; d508000d 00002e2c
	v_mul_f32_e64 v14, s45, s23                                 ; d508000e 00002e2d
	v_mul_f32_e64 v15, s46, s23                                 ; d508000f 00002e2e
	v_mul_f32_e64 v16, s47, s23                                 ; d5080010 00002e2f
	v_mad_f32 v7, s42, s18, v7                                  ; d5410007 041c242a
	v_mad_f32 v12, s43, s18, v12                                ; d541000c 0430242b
	v_mad_f32 v5, s40, s18, v5                                  ; d5410005 04142428
	v_mad_f32 v6, s41, s18, v6                                  ; d5410006 04182429
	v_mad_f32 v13, s40, s22, v13                                ; d541000d 04342c28
	v_mad_f32 v14, s41, s22, v14                                ; d541000e 04382c29
	v_mad_f32 v15, s42, s22, v15                                ; d541000f 043c2c2a
	v_mad_f32 v16, s43, s22, v16                                ; d5410010 04402c2b
	v_mad_f32 v7, s38, s17, v7                                  ; d5410007 041c2226
	v_mad_f32 v12, s39, s17, v12                                ; d541000c 04302227
	v_mad_f32 v5, s36, s17, v5                                  ; d5410005 04142224
	v_mad_f32 v6, s37, s17, v6                                  ; d5410006 04182225
	v_mul_f32_e64 v17, s44, s27                                 ; d5080011 0000362c
	v_mul_f32_e64 v18, s45, s27                                 ; d5080012 0000362d
	v_mad_f32 v13, s36, s21, v13                                ; d541000d 04342a24
	v_mad_f32 v14, s37, s21, v14                                ; d541000e 04382a25
	v_mul_f32_e64 v19, s46, s27                                 ; d5080013 0000362e
	v_mad_f32 v15, s38, s21, v15                                ; d541000f 043c2a26
	v_mul_f32_e64 v24, s47, s27                                 ; d5080018 0000362f
	v_mad_f32 v16, s39, s21, v16                                ; d5410010 04402a27
	v_mad_f32 v7, s34, s16, v7                                  ; d5410007 041c2022
	v_mad_f32 v12, s35, s16, v12                                ; d541000c 04302023
	v_mad_f32 v5, s32, s16, v5                                  ; d5410005 04142020
	v_mad_f32 v6, s33, s16, v6                                  ; d5410006 04182021
	v_mad_f32 v17, s40, s26, v17                                ; d5410011 04443428
	v_mad_f32 v18, s41, s26, v18                                ; d5410012 04483429
	v_mad_f32 v13, s32, s20, v13                                ; d541000d 04342820
	v_mad_f32 v14, s33, s20, v14                                ; d541000e 04382821
	v_mad_f32 v19, s42, s26, v19                                ; d5410013 044c342a
	v_mad_f32 v15, s34, s20, v15                                ; d541000f 043c2822
	v_mad_f32 v24, s43, s26, v24                                ; d5410018 0460342b
	v_mul_f32_e64 v25, s44, s31                                 ; d5080019 00003e2c
	v_mad_f32 v16, s35, s20, v16                                ; d5410010 04402823
	v_mul_f32_e64 v26, s45, s31                                 ; d508001a 00003e2d
	v_mul_f32_e64 v27, s46, s31                                 ; d508001b 00003e2e
	v_mul_f32_e64 v28, s47, s31                                 ; d508001c 00003e2f
	v_mad_f32 v17, s36, s25, v17                                ; d5410011 04443224
	v_mad_f32 v18, s37, s25, v18                                ; d5410012 04483225
	v_mad_f32 v19, s38, s25, v19                                ; d5410013 044c3226
	v_mad_f32 v24, s39, s25, v24                                ; d5410018 04603227
	v_mad_f32 v25, s40, s30, v25                                ; d5410019 04643c28
	v_mad_f32 v26, s41, s30, v26                                ; d541001a 04683c29
	v_mad_f32 v27, s42, s30, v27                                ; d541001b 046c3c2a
	v_mad_f32 v28, s43, s30, v28                                ; d541001c 04703c2b
	v_mad_f32 v17, s32, s24, v17                                ; d5410011 04443020
	v_mad_f32 v18, s33, s24, v18                                ; d5410012 04483021
	v_mad_f32 v19, s34, s24, v19                                ; d5410013 044c3022
	v_mad_f32 v24, s35, s24, v24                                ; d5410018 04603023
	v_mac_f32_e32 v22, v30, v3                                  ; 3e2c071e
	v_mad_f32 v25, s36, s29, v25                                ; d5410019 04643a24
	v_mad_f32 v26, s37, s29, v26                                ; d541001a 04683a25
	v_mad_f32 v27, s38, s29, v27                                ; d541001b 046c3a26
	v_mad_f32 v28, s39, s29, v28                                ; d541001c 04703a27
	v_mac_f32_e32 v4, v22, v22                                  ; 3e082d16
	v_mad_f32 v25, s32, s28, v25                                ; d5410019 04643820
	v_mad_f32 v26, s33, s28, v26                                ; d541001a 04683821
	v_mad_f32 v27, s34, s28, v27                                ; d541001b 046c3822
	v_mad_f32 v28, s35, s28, v28                                ; d541001c 04703823
	v_mac_f32_e32 v4, v20, v20                                  ; 3e082914
	v_mul_f32_e32 v25, v25, v11                                 ; 10321719
	v_mul_f32_e32 v26, v26, v11                                 ; 1034171a
	v_mul_f32_e32 v27, v27, v11                                 ; 1036171b
	v_mul_f32_e32 v28, v28, v11                                 ; 1038171c
	v_rsq_f32_e32 v4, v4                                        ; 7e085d04
	v_mul_f32_e32 v22, v22, v4                                  ; 102c0916
	v_mul_f32_e32 v21, v21, v4                                  ; 102a0915
	v_mul_f32_e32 v20, v20, v4                                  ; 10280914
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_max_f32_e32 v23, 0, v23                                   ; 202e2e80
	v_mul_f32_e32 v23, s4, v23                                  ; 102e2e04
	v_mac_f32_e32 v10, v22, v23                                 ; 3e142f16
	v_mac_f32_e32 v8, v20, v23                                  ; 3e102f14
	v_mac_f32_e32 v9, v21, v23                                  ; 3e122f15
	v_mac_f32_e32 v26, v18, v10                                 ; 3e341512
	v_mac_f32_e32 v25, v17, v10                                 ; 3e321511
	v_mac_f32_e32 v27, v19, v10                                 ; 3e361513
	v_mac_f32_e32 v28, v24, v10                                 ; 3e381518
	v_mac_f32_e32 v26, v14, v9                                  ; 3e34130e
	v_mac_f32_e32 v25, v13, v9                                  ; 3e32130d
	v_mac_f32_e32 v27, v15, v9                                  ; 3e36130f
	v_mac_f32_e32 v28, v16, v9                                  ; 3e381310
	v_mac_f32_e32 v26, v6, v8                                   ; 3e341106
	v_mac_f32_e32 v25, v5, v8                                   ; 3e321105
	v_mac_f32_e32 v27, v7, v8                                   ; 3e361107
	v_mac_f32_e32 v28, v12, v8                                  ; 3e38110c
	exp pos0 v25, v26, v27, v28 done vm                         ; f80018cf 1c1b1a19
BB15:
	s_endpgm                                                    ; bf810000
