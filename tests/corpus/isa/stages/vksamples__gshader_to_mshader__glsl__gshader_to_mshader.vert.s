# Vertex Shader as ES + Geometry Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s0, 0, s3                                 ; 99000380
	s_bfe_u64 exec, -1, s0                                      ; 94fe00c1
	s_cbranch_execz BB6                                         ; bf8800ce
BB1:
	s_mov_b32 s0, s9                                            ; be800309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_load_dwordx8 s[16:23], s[8:9], null                       ; f40c0404 fa000000
	v_add_nc_u32_e32 v5, s0, v5                                 ; 4a0a0a00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx3 v[2:4], v5, s[16:19], 0 idxen           ; e03c2000 80040205
	buffer_load_dwordx3 v[5:7], v5, s[20:23], 0 idxen offset:16 ; e03c2010 80050505
	s_mov_b32 s0, s10                                           ; be80030a
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_load_dwordx4 s[4:7], s[0:1], null                         ; f4080100 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x4                                                ; bfa10004
	s_buffer_load_dwordx16 s[16:31], s[4:7], 0x40               ; f4300402 fa000040
	s_buffer_load_dwordx16 s[32:47], s[4:7], 0x80               ; f4300802 fa000080
	s_buffer_load_dwordx16 s[48:63], s[4:7], null               ; f4300c02 fa000000
	s_buffer_load_dwordx4 s[64:67], s[4:7], 0xe0                ; f4281002 fa0000e0
	s_buffer_load_dwordx8 s[72:79], s[4:7], 0xc0                ; f42c1202 fa0000c0
	s_bfe_u32 s1, s3, 0x40018                                   ; 9381ff03 00040018
	s_lshl_b32 s1, s1, 6                                        ; 8f018601
	v_mbcnt_lo_u32_b32 v8, -1, s1                               ; d7650008 000002c1
	v_mbcnt_hi_u32_b32 v8, -1, v8                               ; d7660008 000210c1
	v_mul_u32_u24_e32 v8, 36, v8                                ; 161010a4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v13, s45, s23                                 ; d508000d 00002e2d
	v_mul_f32_e64 v14, s46, s23                                 ; d508000e 00002e2e
	v_mul_f32_e64 v9, s44, s19                                  ; d5080009 0000262c
	v_mul_f32_e64 v10, s45, s19                                 ; d508000a 0000262d
	v_mul_f32_e64 v11, s46, s19                                 ; d508000b 0000262e
	v_mul_f32_e64 v12, s44, s23                                 ; d508000c 00002e2c
	v_mad_f32 v13, s41, s22, v13                                ; d541000d 04342c29
	v_mad_f32 v14, s42, s22, v14                                ; d541000e 04382c2a
	v_mad_f32 v9, s40, s18, v9                                  ; d5410009 04242428
	v_mul_f32_e64 v15, s44, s27                                 ; d508000f 0000362c
	v_mad_f32 v10, s41, s18, v10                                ; d541000a 04282429
	v_mul_f32_e64 v16, s45, s27                                 ; d5080010 0000362d
	v_mad_f32 v11, s42, s18, v11                                ; d541000b 042c242a
	v_mad_f32 v12, s40, s22, v12                                ; d541000c 04302c28
	v_mul_f32_e64 v17, s46, s27                                 ; d5080011 0000362e
	v_mad_f32 v13, s37, s21, v13                                ; d541000d 04342a25
	v_mad_f32 v14, s38, s21, v14                                ; d541000e 04382a26
	v_mad_f32 v9, s36, s17, v9                                  ; d5410009 04242224
	v_mad_f32 v15, s40, s26, v15                                ; d541000f 043c3428
	v_mad_f32 v10, s37, s17, v10                                ; d541000a 04282225
	v_mad_f32 v16, s41, s26, v16                                ; d5410010 04403429
	v_mad_f32 v11, s38, s17, v11                                ; d541000b 042c2226
	v_mad_f32 v12, s36, s21, v12                                ; d541000c 04302a24
	v_mad_f32 v17, s42, s26, v17                                ; d5410011 0444342a
	v_mad_f32 v13, s33, s20, v13                                ; d541000d 04342821
	v_mul_f32_e64 v18, s44, s31                                 ; d5080012 00003e2c
	v_mad_f32 v14, s34, s20, v14                                ; d541000e 04382822
	v_mul_f32_e64 v19, s45, s31                                 ; d5080013 00003e2d
	v_mul_f32_e64 v20, s46, s31                                 ; d5080014 00003e2e
	v_mad_f32 v9, s32, s16, v9                                  ; d5410009 04242020
	v_mad_f32 v15, s36, s25, v15                                ; d541000f 043c3224
	v_mad_f32 v10, s33, s16, v10                                ; d541000a 04282021
	v_mad_f32 v16, s37, s25, v16                                ; d5410010 04403225
	v_mad_f32 v11, s34, s16, v11                                ; d541000b 042c2022
	v_mad_f32 v12, s32, s20, v12                                ; d541000c 04302820
	v_mad_f32 v17, s38, s25, v17                                ; d5410011 04443226
	v_mad_f32 v18, s40, s30, v18                                ; d5410012 04483c28
	v_mad_f32 v19, s41, s30, v19                                ; d5410013 044c3c29
	v_mad_f32 v20, s42, s30, v20                                ; d5410014 04503c2a
	v_mad_f32 v15, s32, s24, v15                                ; d541000f 043c3020
	v_mad_f32 v16, s33, s24, v16                                ; d5410010 04403021
	v_mad_f32 v17, s34, s24, v17                                ; d5410011 04443022
	v_mad_f32 v18, s36, s29, v18                                ; d5410012 04483a24
	v_mad_f32 v19, s37, s29, v19                                ; d5410013 044c3a25
	v_mad_f32 v20, s38, s29, v20                                ; d5410014 04503a26
	v_mad_f32 v18, s32, s28, v18                                ; d5410012 04483820
	v_mad_f32 v19, s33, s28, v19                                ; d5410013 044c3821
	v_mad_f32 v20, s34, s28, v20                                ; d5410014 04503822
	v_mul_f32_e32 v24, s55, v18                                 ; 10302437
	v_mul_f32_e32 v21, s51, v18                                 ; 102a2433
	v_mul_f32_e32 v25, s55, v19                                 ; 10322637
	v_mul_f32_e32 v22, s51, v19                                 ; 102c2633
	v_mul_f32_e32 v26, s55, v20                                 ; 10342837
	v_mul_f32_e32 v23, s51, v20                                 ; 102e2833
	v_mac_f32_e32 v24, s54, v15                                 ; 3e301e36
	v_mac_f32_e32 v21, s50, v15                                 ; 3e2a1e32
	v_mac_f32_e32 v25, s54, v16                                 ; 3e322036
	v_mac_f32_e32 v22, s50, v16                                 ; 3e2c2032
	v_mul_f32_e32 v27, s59, v18                                 ; 1036243b
	v_mul_f32_e32 v28, s59, v19                                 ; 1038263b
	v_mac_f32_e32 v26, s54, v17                                 ; 3e342236
	v_mac_f32_e32 v23, s50, v17                                 ; 3e2e2232
	v_mul_f32_e32 v29, s59, v20                                 ; 103a283b
	v_mac_f32_e32 v24, s53, v12                                 ; 3e301835
	v_mac_f32_e32 v21, s49, v12                                 ; 3e2a1831
	v_mac_f32_e32 v25, s53, v13                                 ; 3e321a35
	v_mac_f32_e32 v22, s49, v13                                 ; 3e2c1a31
	v_mac_f32_e32 v27, s58, v15                                 ; 3e361e3a
	v_mac_f32_e32 v28, s58, v16                                 ; 3e38203a
	v_mac_f32_e32 v26, s53, v14                                 ; 3e341c35
	v_mac_f32_e32 v23, s49, v14                                 ; 3e2e1c31
	v_mac_f32_e32 v29, s58, v17                                 ; 3e3a223a
	v_mul_f32_e32 v18, s63, v18                                 ; 1024243f
	v_mac_f32_e32 v24, s52, v9                                  ; 3e301234
	v_mul_f32_e32 v19, s63, v19                                 ; 1026263f
	v_mac_f32_e32 v21, s48, v9                                  ; 3e2a1230
	v_mul_f32_e32 v20, s63, v20                                 ; 1028283f
	v_mac_f32_e32 v25, s52, v10                                 ; 3e321434
	v_mac_f32_e32 v22, s48, v10                                 ; 3e2c1430
	v_mac_f32_e32 v27, s57, v12                                 ; 3e361839
	v_mac_f32_e32 v28, s57, v13                                 ; 3e381a39
	v_mac_f32_e32 v26, s52, v11                                 ; 3e341634
	v_mac_f32_e32 v23, s48, v11                                 ; 3e2e1630
	v_mac_f32_e32 v29, s57, v14                                 ; 3e3a1c39
	v_mac_f32_e32 v18, s62, v15                                 ; 3e241e3e
	v_mac_f32_e32 v19, s62, v16                                 ; 3e26203e
	v_mac_f32_e32 v20, s62, v17                                 ; 3e28223e
	v_mac_f32_e32 v27, s56, v9                                  ; 3e361238
	v_mac_f32_e32 v28, s56, v10                                 ; 3e381438
	v_mac_f32_e32 v29, s56, v11                                 ; 3e3a1638
	v_mac_f32_e32 v18, s61, v12                                 ; 3e24183d
	v_mac_f32_e32 v19, s61, v13                                 ; 3e261a3d
	v_mac_f32_e32 v20, s61, v14                                 ; 3e281c3d
	v_mac_f32_e32 v18, s60, v9                                  ; 3e24123c
	v_mac_f32_e32 v19, s60, v10                                 ; 3e26143c
	v_mac_f32_e32 v20, s60, v11                                 ; 3e28163c
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v19, v28, v4                                  ; 3e26091c
	v_mac_f32_e32 v20, v29, v4                                  ; 3e28091d
	v_mac_f32_e32 v18, v27, v4                                  ; 3e24091b
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v30, s64, v7                                  ; 103c0e40
	v_mul_f32_e32 v31, s65, v7                                  ; 103e0e41
	v_mul_f32_e32 v7, s66, v7                                   ; 100e0e42
	v_mac_f32_e32 v19, v25, v3                                  ; 3e260719
	v_mac_f32_e32 v20, v26, v3                                  ; 3e28071a
	v_mac_f32_e32 v18, v24, v3                                  ; 3e240718
	v_mac_f32_e32 v30, s76, v6                                  ; 3e3c0c4c
	v_mac_f32_e32 v31, s77, v6                                  ; 3e3e0c4d
	v_mac_f32_e32 v7, s78, v6                                   ; 3e0e0c4e
	v_mac_f32_e32 v19, v22, v2                                  ; 3e260516
	v_mac_f32_e32 v20, v23, v2                                  ; 3e280517
	v_mac_f32_e32 v18, v21, v2                                  ; 3e240515
	v_mac_f32_e32 v30, s72, v5                                  ; 3e3c0a48
	v_mac_f32_e32 v31, s73, v5                                  ; 3e3e0a49
	v_mac_f32_e32 v7, s74, v5                                   ; 3e0e0a4a
	ds_write2_b32 v8, v31, v7 offset0:4 offset1:5               ; d8380504 00071f08
	ds_write2_b32 v8, v18, v19 offset1:1                        ; d8380100 00131208
	ds_write2_b32 v8, v20, v30 offset0:2 offset1:3              ; d8380302 001e1408
BB6:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_lshl_b32 s0, s3, 8                                        ; 8f008803
	s_pack_ll_b32_b16 s11, s11, 0                               ; 990b800b
	s_bfe_u64 s[0:1], -1, s0                                    ; 948000c1
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_cbranch_execz BB21                                        ; bf880147
BB7:
	v_mad_u32_u16 v2, 36, v0, 0 op_sel:[0,1,0,0]                ; d7731002 020200a4
	v_mad_u32_u16 v0, 36, v0, 0                                 ; d7730000 020200a4
	v_mad_u32_u16 v1, 36, v1, 0                                 ; d7730001 020202a4
	ds_read2_b32 v[4:5], v2 offset1:1                           ; d8dc0100 04000002
	ds_read_b32 v2, v2 offset:8                                 ; d8d80008 02000002
	ds_read2_b32 v[6:7], v0 offset1:1                           ; d8dc0100 06000000
	ds_read2_b32 v[8:9], v0 offset0:2 offset1:3                 ; d8dc0302 08000000
	ds_read2_b32 v[10:11], v1 offset1:1                         ; d8dc0100 0a000001
	ds_read_b32 v1, v1 offset:8                                 ; d8d80008 01000001
	s_mov_b32 s0, s11                                           ; be80030b
	s_movk_i32 s11, 0x8000                                      ; b00b8000
	s_load_dwordx4 s[4:7], s[10:11], 0x10                       ; f4080105 fa000010
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x2                                                ; bfa10002
	s_buffer_load_dwordx16 s[16:31], s[4:7], 0x40               ; f4300402 fa000040
	s_buffer_load_dwordx16 s[32:47], s[4:7], 0x80               ; f4300802 fa000080
	s_buffer_load_dwordx16 s[48:63], s[4:7], null               ; f4300c02 fa000000
	s_bfe_u32 s1, s3, 0x40018                                   ; 9381ff03 00040018
	v_add_f32_e32 v6, v6, v4                                    ; 060c0906
	v_add_f32_e32 v7, v7, v5                                    ; 060e0b07
	v_add_f32_e32 v8, v8, v2                                    ; 06100508
	v_mov_b32_e32 v5, 4                                         ; 7e0a0284
	s_lshl_b32 s1, s1, 6                                        ; 8f018601
	v_add_f32_e32 v6, v6, v10                                   ; 060c1506
	v_add_f32_e32 v7, v7, v11                                   ; 060e1707
	v_mbcnt_lo_u32_b32 v3, -1, s1                               ; d7650003 000002c1
	v_add_f32_e32 v8, v8, v1                                    ; 06100308
	v_mul_f32_e32 v6, 0x3eaaaaab, v6                            ; 100c0cff 3eaaaaab
	v_mul_f32_e32 v7, 0x3eaaaaab, v7                            ; 100e0eff 3eaaaaab
	v_mbcnt_hi_u32_b32 v3, -1, v3                               ; d7660003 000206c1
	v_mul_f32_e32 v8, 0x3eaaaaab, v8                            ; 101010ff 3eaaaaab
	v_lshlrev_b32_e32 v3, 1, v3                                 ; 34060681
	v_bfe_u32 v4, v3, 5, 1                                      ; d5480004 02050b03
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v11, s45, s19                                 ; d508000b 0000262d
	v_mul_f32_e64 v13, s47, s19                                 ; d508000d 0000262f
	v_mul_f32_e64 v12, s46, s19                                 ; d508000c 0000262e
	v_mul_f32_e64 v10, s44, s19                                 ; d508000a 0000262c
	v_mul_f32_e64 v14, s44, s23                                 ; d508000e 00002e2c
	v_xor_b32_e32 v4, v3, v4                                    ; 3a080903
	v_mul_f32_e64 v15, s45, s23                                 ; d508000f 00002e2d
	v_mul_f32_e64 v16, s46, s23                                 ; d5080010 00002e2e
	v_mul_f32_e64 v17, s47, s23                                 ; d5080011 00002e2f
	v_mad_f32 v11, s41, s18, v11                                ; d541000b 042c2429
	v_mad_f32 v13, s43, s18, v13                                ; d541000d 0434242b
	v_mad_f32 v12, s42, s18, v12                                ; d541000c 0430242a
	v_mad_f32 v10, s40, s18, v10                                ; d541000a 04282428
	v_mad_f32 v14, s40, s22, v14                                ; d541000e 04382c28
	v_mad_u32_u24 v4, 20, v4, s0                                ; d5430004 00020894
	v_mad_f32 v15, s41, s22, v15                                ; d541000f 043c2c29
	v_mad_f32 v16, s42, s22, v16                                ; d5410010 04402c2a
	v_mad_f32 v17, s43, s22, v17                                ; d5410011 04442c2b
	v_mad_f32 v11, s37, s17, v11                                ; d541000b 042c2225
	v_mad_f32 v13, s39, s17, v13                                ; d541000d 04342227
	v_mad_f32 v12, s38, s17, v12                                ; d541000c 04302226
	v_mad_f32 v10, s36, s17, v10                                ; d541000a 04282224
	v_mad_f32 v14, s36, s21, v14                                ; d541000e 04382a24
	v_mul_f32_e64 v18, s44, s27                                 ; d5080012 0000362c
	v_mul_f32_e64 v19, s45, s27                                 ; d5080013 0000362d
	v_mad_f32 v15, s37, s21, v15                                ; d541000f 043c2a25
	v_mul_f32_e64 v20, s46, s27                                 ; d5080014 0000362e
	v_mad_f32 v16, s38, s21, v16                                ; d5410010 04402a26
	v_mul_f32_e64 v21, s47, s27                                 ; d5080015 0000362f
	v_mad_f32 v17, s39, s21, v17                                ; d5410011 04442a27
	v_mad_f32 v11, s33, s16, v11                                ; d541000b 042c2021
	v_mad_f32 v13, s35, s16, v13                                ; d541000d 04342023
	v_mad_f32 v12, s34, s16, v12                                ; d541000c 04302022
	v_mad_f32 v10, s32, s16, v10                                ; d541000a 04282020
	v_mad_f32 v14, s32, s20, v14                                ; d541000e 04382820
	v_mad_f32 v18, s40, s26, v18                                ; d5410012 04483428
	v_mad_f32 v19, s41, s26, v19                                ; d5410013 044c3429
	v_mad_f32 v15, s33, s20, v15                                ; d541000f 043c2821
	v_mad_f32 v20, s42, s26, v20                                ; d5410014 0450342a
	v_mad_f32 v16, s34, s20, v16                                ; d5410010 04402822
	v_mad_f32 v21, s43, s26, v21                                ; d5410015 0454342b
	v_mad_f32 v17, s35, s20, v17                                ; d5410011 04442823
	v_mul_f32_e64 v22, s44, s31                                 ; d5080016 00003e2c
	v_mul_f32_e64 v23, s45, s31                                 ; d5080017 00003e2d
	v_mul_f32_e64 v24, s46, s31                                 ; d5080018 00003e2e
	v_mul_f32_e64 v25, s47, s31                                 ; d5080019 00003e2f
	v_mad_f32 v18, s36, s25, v18                                ; d5410012 04483224
	v_mad_f32 v19, s37, s25, v19                                ; d5410013 044c3225
	v_mad_f32 v20, s38, s25, v20                                ; d5410014 04503226
	v_mad_f32 v21, s39, s25, v21                                ; d5410015 04543227
	v_mad_f32 v22, s40, s30, v22                                ; d5410016 04583c28
	v_mad_f32 v23, s41, s30, v23                                ; d5410017 045c3c29
	v_mad_f32 v24, s42, s30, v24                                ; d5410018 04603c2a
	v_mad_f32 v25, s43, s30, v25                                ; d5410019 04643c2b
	v_mad_f32 v18, s32, s24, v18                                ; d5410012 04483020
	v_mad_f32 v19, s33, s24, v19                                ; d5410013 044c3021
	v_mad_f32 v20, s34, s24, v20                                ; d5410014 04503022
	v_mad_f32 v21, s35, s24, v21                                ; d5410015 04543023
	v_mad_f32 v22, s36, s29, v22                                ; d5410016 04583a24
	v_mad_f32 v23, s37, s29, v23                                ; d5410017 045c3a25
	v_mad_f32 v24, s38, s29, v24                                ; d5410018 04603a26
	v_mad_f32 v25, s39, s29, v25                                ; d5410019 04643a27
	v_mad_f32 v22, s32, s28, v22                                ; d5410016 04583820
	v_mad_f32 v23, s33, s28, v23                                ; d5410017 045c3821
	v_mad_f32 v24, s34, s28, v24                                ; d5410018 04603822
	v_mad_f32 v25, s35, s28, v25                                ; d5410019 04643823
	v_mul_f32_e32 v26, s51, v22                                 ; 10342c33
	v_mul_f32_e32 v27, s51, v23                                 ; 10362e33
	v_mul_f32_e32 v30, s55, v22                                 ; 103c2c37
	v_mul_f32_e32 v31, s55, v23                                 ; 103e2e37
	v_mul_f32_e32 v28, s51, v24                                 ; 10383033
	v_mul_f32_e32 v29, s51, v25                                 ; 103a3233
	v_mul_f32_e32 v32, s55, v24                                 ; 10403037
	v_mul_f32_e32 v33, s55, v25                                 ; 10423237
	v_mac_f32_e32 v26, s50, v18                                 ; 3e342432
	v_mac_f32_e32 v27, s50, v19                                 ; 3e362632
	v_mac_f32_e32 v30, s54, v18                                 ; 3e3c2436
	v_mac_f32_e32 v31, s54, v19                                 ; 3e3e2636
	v_mac_f32_e32 v28, s50, v20                                 ; 3e382832
	v_mac_f32_e32 v29, s50, v21                                 ; 3e3a2a32
	v_mac_f32_e32 v32, s54, v20                                 ; 3e402836
	v_mac_f32_e32 v33, s54, v21                                 ; 3e422a36
	v_mac_f32_e32 v26, s49, v14                                 ; 3e341c31
	v_mac_f32_e32 v27, s49, v15                                 ; 3e361e31
	v_mac_f32_e32 v30, s53, v14                                 ; 3e3c1c35
	v_mul_f32_e32 v34, s59, v22                                 ; 10442c3b
	v_mac_f32_e32 v31, s53, v15                                 ; 3e3e1e35
	v_mul_f32_e32 v35, s59, v23                                 ; 10462e3b
	v_mac_f32_e32 v28, s49, v16                                 ; 3e382031
	v_mac_f32_e32 v29, s49, v17                                 ; 3e3a2231
	v_mul_f32_e32 v1, s59, v24                                  ; 1002303b
	v_mul_f32_e32 v2, s59, v25                                  ; 1004323b
	v_mac_f32_e32 v32, s53, v16                                 ; 3e402035
	v_mac_f32_e32 v33, s53, v17                                 ; 3e422235
	v_mac_f32_e32 v26, s48, v10                                 ; 3e341430
	v_mac_f32_e32 v27, s48, v11                                 ; 3e361630
	v_mac_f32_e32 v30, s52, v10                                 ; 3e3c1434
	v_mac_f32_e32 v34, s58, v18                                 ; 3e44243a
	v_mac_f32_e32 v31, s52, v11                                 ; 3e3e1634
	v_mac_f32_e32 v35, s58, v19                                 ; 3e46263a
	v_mac_f32_e32 v28, s48, v12                                 ; 3e381830
	v_mac_f32_e32 v29, s48, v13                                 ; 3e3a1a30
	v_mac_f32_e32 v1, s58, v20                                  ; 3e02283a
	v_mac_f32_e32 v2, s58, v21                                  ; 3e042a3a
	v_mac_f32_e32 v32, s52, v12                                 ; 3e401834
	v_mac_f32_e32 v33, s52, v13                                 ; 3e421a34
	v_mul_f32_e32 v22, s63, v22                                 ; 102c2c3f
	v_mul_f32_e32 v23, s63, v23                                 ; 102e2e3f
	v_mul_f32_e32 v24, s63, v24                                 ; 1030303f
	v_mul_f32_e32 v25, s63, v25                                 ; 1032323f
	v_mac_f32_e32 v34, s57, v14                                 ; 3e441c39
	v_mac_f32_e32 v35, s57, v15                                 ; 3e461e39
	v_mac_f32_e32 v1, s57, v16                                  ; 3e022039
	v_mac_f32_e32 v2, s57, v17                                  ; 3e042239
	v_mac_f32_e32 v22, s62, v18                                 ; 3e2c243e
	v_mac_f32_e32 v23, s62, v19                                 ; 3e2e263e
	v_mac_f32_e32 v24, s62, v20                                 ; 3e30283e
	v_mac_f32_e32 v25, s62, v21                                 ; 3e322a3e
	v_mac_f32_e32 v34, s56, v10                                 ; 3e441438
	v_mac_f32_e32 v35, s56, v11                                 ; 3e461638
	v_mac_f32_e32 v1, s56, v12                                  ; 3e021838
	v_mac_f32_e32 v2, s56, v13                                  ; 3e041a38
	v_mac_f32_e32 v22, s61, v14                                 ; 3e2c1c3d
	v_mac_f32_e32 v23, s61, v15                                 ; 3e2e1e3d
	v_mac_f32_e32 v24, s61, v16                                 ; 3e30203d
	v_mac_f32_e32 v25, s61, v17                                 ; 3e32223d
	v_mac_f32_e32 v22, s60, v10                                 ; 3e2c143c
	v_mac_f32_e32 v23, s60, v11                                 ; 3e2e163c
	v_mac_f32_e32 v24, s60, v12                                 ; 3e30183c
	v_mac_f32_e32 v25, s60, v13                                 ; 3e321a3c
	v_mad_f32 v10, v34, v8, v22                                 ; d541000a 045a1122
	v_mad_f32 v11, v35, v8, v23                                 ; d541000b 045e1123
	v_mad_f32 v12, v1, v8, v24                                  ; d541000c 04621101
	v_mad_f32 v13, v2, v8, v25                                  ; d541000d 04661102
	v_mac_f32_e32 v10, v30, v7                                  ; 3e140f1e
	v_mac_f32_e32 v11, v31, v7                                  ; 3e160f1f
	v_mac_f32_e32 v12, v32, v7                                  ; 3e180f20
	v_mac_f32_e32 v13, v33, v7                                  ; 3e1a0f21
	v_mac_f32_e32 v10, v26, v6                                  ; 3e140d1a
	v_mac_f32_e32 v11, v27, v6                                  ; 3e160d1b
	v_mac_f32_e32 v12, v28, v6                                  ; 3e180d1c
	v_mac_f32_e32 v13, v29, v6                                  ; 3e1a0d1d
	ds_write2_b32 v4, v10, v11 offset0:1 offset1:2              ; d8380201 000b0a04
	ds_write2_b32 v4, v12, v13 offset0:3 offset1:4              ; d8380403 000d0c04
	ds_write_b8 v4, v5 offset:20                                ; d8780014 00000504
	ds_read2_b32 v[4:5], v0 offset0:4 offset1:5                 ; d8dc0504 04000000
	v_madmk_f32 v9, v9, 0x3dcccccd, v6                          ; 40120d09 3dcccccd
	v_add_nc_u32_e32 v3, 1, v3                                  ; 4a060681
	v_mov_b32_e32 v15, 5                                        ; 7e1e0285
	s_bfe_u32 s12, s12, 0x30006                                 ; 938cff0c 00030006
	s_bitcmp1_b32 s12, 0                                        ; bf0d800c
	v_bfe_u32 v14, v3, 5, 1                                     ; d548000e 02050b03
	s_cselect_b64 s[4:5], -1, 0                                 ; 858480c1
	v_xor_b32_e32 v3, v3, v14                                   ; 3a061d03
	v_mad_u32_u24 v3, 20, v3, s0                                ; d5430003 00020694
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_madmk_f32 v4, v4, 0x3dcccccd, v7                          ; 40080f04 3dcccccd
	v_madmk_f32 v5, v5, 0x3dcccccd, v8                          ; 400a1105 3dcccccd
	v_mac_f32_e32 v24, v1, v5                                   ; 3e300b01
	v_mac_f32_e32 v25, v2, v5                                   ; 3e320b02
	v_mac_f32_e32 v22, v34, v5                                  ; 3e2c0b22
	v_mac_f32_e32 v23, v35, v5                                  ; 3e2e0b23
	v_mac_f32_e32 v24, v32, v4                                  ; 3e300920
	v_mac_f32_e32 v25, v33, v4                                  ; 3e320921
	v_mac_f32_e32 v22, v30, v4                                  ; 3e2c091e
	v_mac_f32_e32 v23, v31, v4                                  ; 3e2e091f
	v_mac_f32_e32 v24, v28, v9                                  ; 3e30131c
	v_mac_f32_e32 v25, v29, v9                                  ; 3e32131d
	v_mac_f32_e32 v22, v26, v9                                  ; 3e2c131a
	v_mac_f32_e32 v23, v27, v9                                  ; 3e2e131b
	ds_write2_b32 v3, v22, v23 offset0:1 offset1:2              ; d8380201 00171603
	ds_write2_b32 v3, v24, v25 offset0:3 offset1:4              ; d8380403 00191803
	ds_write_b8 v3, v15 offset:20                               ; d8780014 00000f03
	s_cbranch_scc0 BB16                                         ; bf840010
BB8:
	s_and_b64 s[6:7], -1, exec                                  ; 87867ec1
	s_bcnt1_i32_b64 s1, s[6:7]                                  ; be811006
	s_ff1_i32_b64 s6, exec                                      ; be86147e
	s_lshl_b64 s[6:7], 1, s6                                    ; 8f860681
	s_and_b64 s[4:5], s[4:5], s[6:7]                            ; 87840604
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_and_saveexec_b64 s[4:5], s[4:5]                           ; be842404
	s_cbranch_execz BB16                                        ; bf880008
BB9:
	s_movk_i32 m0, 0x100                                        ; b07c0100
	v_mov_b32_e32 v0, s1                                        ; 7e000201
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	ds_add_u32 v1, v0 gds                                       ; d8020000 00000001
	v_mov_b32_e32 v2, 4                                         ; 7e040284
	ds_add_u32 v2, v0 gds                                       ; d8020000 00000002
BB16:
	s_mov_b32 s11, s0                                           ; be8b0300
BB21:
	s_waitcnt expcnt(0)                                         ; bf8cff0f
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, -1                                          ; befe04c1
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_bfe_u32 s0, s3, 0x40018                                   ; 9380ff03 00040018
	s_lshl_b32 s1, s0, 6                                        ; 8f018600
	s_bfe_u32 s2, s2, 0x9000c                                   ; 9382ff02 0009000c
	v_mbcnt_lo_u32_b32 v0, -1, s1                               ; d7650000 000002c1
	v_mbcnt_hi_u32_b32 v0, -1, v0                               ; d7660000 000200c1
	v_bfe_u32 v1, v0, 5, 1                                      ; d5480001 02050b00
	v_xor_b32_e32 v1, v0, v1                                    ; 3a020300
	v_mad_u32_u24 v1, 20, v1, s11                               ; d5430001 002e0294
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 s2, v0                                    ; 7d280002
	s_cbranch_execz BB25                                        ; bf880002
BB22:
	ds_read_u8 v2, v1 offset:20                                 ; d8e80014 02000001
BB25:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_andn2_b64 exec, -1, exec                                  ; 8afe7ec1
	v_mov_b32_e32 v2, 0                                         ; 7e040280
BB27:
	s_mov_b64 exec, -1                                          ; befe04c1
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cmp_ne_i32_e32 vcc, 0, v2                                 ; 7d0a0480
	s_mov_b64 exec, 1                                           ; befe0481
	s_bcnt1_i32_b64 s1, vcc                                     ; be81106a
BB28:
	s_add_u32 s4, s11, s0                                       ; 8004000b
	v_mov_b32_e32 v4, s1                                        ; 7e080201
	v_mov_b32_e32 v3, s4                                        ; 7e060204
	ds_write_b8 v3, v4                                          ; d8780000 00000403
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	v_mov_b32_e32 v5, s11                                       ; 7e0a020b
	ds_read_b32 v5, v5                                          ; d8d80000 05000005
BB33:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, -1                                          ; befe04c1
	v_mbcnt_lo_u32_b32 v3, -1, 0                                ; d7650003 000100c1
	v_mbcnt_hi_u32_b32 v3, -1, v3                               ; d7660003 000206c1
	v_mad_i32_i24 v4, v3, -8, 24                                ; d5420004 02619103
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_permlane16_b32 v5, v5, 0, 0                               ; d7770005 02010105
	v_lshlrev_b32_e32 v4, v4, v5                                ; 34080b04
	v_msad_u8 v4, 0, v4, 0                                      ; d5710004 02020880
	v_readlane_b32 s4, v4, s0                                   ; d7600004 00000104
	s_sub_i32 s4, s4, s1                                        ; 81840104
	s_lshr_b32 s3, s3, 28                                       ; 90039c03
	v_mbcnt_lo_u32_b32 v5, vcc_lo, s4                           ; d7650005 0000086a
	s_add_u32 s3, s3, -1                                        ; 8003c103
	v_readlane_b32 s3, v4, s3                                   ; d7600003 00000704
	v_mbcnt_hi_u32_b32 v5, vcc_hi, v5                           ; d7660005 00020a6b
	s_cmp_lg_i32 s3, 0                                          ; bf018003
	s_mul_i32 s2, s2, src_scc                                   ; 9302fd02
	s_cmp_eq_i32 s0, 0                                          ; bf008000
	s_cbranch_scc0 BB45                                         ; bf840010
BB34:
	s_cmp_eq_i32 s2, 0                                          ; bf008002
	s_cbranch_scc0 BB42                                         ; bf84000b
BB35:
	s_movk_i32 m0, 0x1001                                       ; b07c1001
	s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)                         ; bf900009
	v_cmpx_eq_i32_e32 0, v3                                     ; 7d240680
	s_cbranch_execz BB45                                        ; bf88000a
BB36:
	v_mov_b32_e32 v3, 0                                         ; 7e060280
	v_mov_b32_e32 v4, -1                                        ; 7e0802c1
	exp prim v3, off, off, off done                             ; f8000941 80808003
	exp pos0 v4, v4, v4, v4 done                                ; f80008cf 04040404
	s_branch BB45                                               ; bf820003
BB42:
	s_lshl_b32 s0, s2, 12                                       ; 8f008c02
	s_or_b32 m0, s0, s3                                         ; 887c0300
	s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)                         ; bf900009
BB45:
	s_waitcnt expcnt(0)                                         ; bf8cff0f
	s_mov_b64 exec, vcc                                         ; befe046a
	s_cbranch_execz BB51                                        ; bf88000a
BB46:
	v_bfe_u32 v3, v5, 5, 1                                      ; d5480003 02050b05
	v_mov_b32_sdwa v4, v0 dst_sel:BYTE_0 dst_unused:UNUSED_PRESERVE src0_sel:BYTE_0 ; 7e0802f9 00001000
	v_xor_b32_e32 v3, v5, v3                                    ; 3a060705
	v_mul_lo_u32 v3, 20, v3                                     ; d5690003 00020694
	v_add_nc_u32_e32 v3, s11, v3                                ; 4a06060b
	ds_write_b8 v3, v4 offset:21                                ; d8780015 00000403
BB51:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, -1                                          ; befe04c1
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	v_cmpx_gt_i32_e32 s2, v0                                    ; 7d280002
	s_mov_b64 vcc, exec                                         ; beea047e
BB52:
	v_add_nc_u32_e32 v3, -1, v5                                 ; 4a060ac1
	v_not_b32_e32 v2, v2                                        ; 7e046f02
	v_lshl_or_b32 v5, v5, 10, v3                                ; d76f0005 040d1505
	v_lshl_or_b32 v2, v2, 31, v5                                ; d76f0002 04153f02
BB57:
	s_mov_b64 exec, -1                                          ; befe04c1
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 s3, v0                                    ; 7d280003
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_cbranch_execz BB63                                        ; bf88000c
BB58:
	ds_read_u8 v1, v1 offset:21                                 ; d8e80015 01000001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_bfe_u32 v0, v1, 5, 1                                      ; d5480000 02050b01
	v_xor_b32_e32 v1, v1, v0                                    ; 3a020101
	v_mad_u32_u24 v1, 20, v1, s11                               ; d5430001 002e0294
	ds_read2_b32 v[4:5], v1 offset0:1 offset1:2                 ; d8dc0201 04000001
	ds_read2_b32 v[0:1], v1 offset0:3 offset1:4                 ; d8dc0403 00000001
BB63:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, vcc                                         ; befe046a
	s_cbranch_execz BB69                                        ; bf880002
BB64:
	exp prim v2, off, off, off done                             ; f8000941 80808002
BB69:
	s_waitcnt expcnt(0)                                         ; bf8cff0f
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_cbranch_execz BB75                                        ; bf880003
BB70:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	exp pos0 v4, v5, v0, v1 done vm                             ; f80018cf 01000504
BB75:
	s_endpgm                                                    ; bf810000
