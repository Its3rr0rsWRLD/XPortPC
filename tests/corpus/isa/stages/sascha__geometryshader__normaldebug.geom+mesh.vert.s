# Vertex Shader as ES + Geometry Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s0, 0, s3                                 ; 99000380
	s_bfe_u64 exec, -1, s0                                      ; 94fe00c1
	s_cbranch_execz BB6                                         ; bf880098
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
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[16:31], s[4:7], 0x40               ; f4300402 fa000040
	s_buffer_load_dwordx16 s[32:47], s[4:7], null               ; f4300802 fa000000
	s_bfe_u32 s1, s3, 0x40018                                   ; 9381ff03 00040018
	s_lshl_b32 s1, s1, 6                                        ; 8f018601
	v_mbcnt_lo_u32_b32 v8, -1, s1                               ; d7650008 000002c1
	v_mbcnt_hi_u32_b32 v8, -1, v8                               ; d7660008 000210c1
	v_mul_u32_u24_e32 v8, 36, v8                                ; 161010a4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v9, s44, s19                                  ; d5080009 0000262c
	v_mul_f32_e64 v10, s45, s19                                 ; d508000a 0000262d
	v_mul_f32_e64 v11, s46, s19                                 ; d508000b 0000262e
	v_mul_f32_e64 v12, s44, s23                                 ; d508000c 00002e2c
	v_mul_f32_e64 v13, s45, s23                                 ; d508000d 00002e2d
	v_mul_f32_e64 v14, s46, s23                                 ; d508000e 00002e2e
	v_mad_f32 v9, s40, s18, v9                                  ; d5410009 04242428
	v_mad_f32 v10, s41, s18, v10                                ; d541000a 04282429
	v_mad_f32 v11, s42, s18, v11                                ; d541000b 042c242a
	v_mul_f32_e64 v15, s44, s27                                 ; d508000f 0000362c
	v_mad_f32 v12, s40, s22, v12                                ; d541000c 04302c28
	v_mad_f32 v13, s41, s22, v13                                ; d541000d 04342c29
	v_mul_f32_e64 v16, s45, s27                                 ; d5080010 0000362d
	v_mad_f32 v14, s42, s22, v14                                ; d541000e 04382c2a
	v_mul_f32_e64 v17, s46, s27                                 ; d5080011 0000362e
	v_mad_f32 v9, s36, s17, v9                                  ; d5410009 04242224
	v_mad_f32 v10, s37, s17, v10                                ; d541000a 04282225
	v_mad_f32 v11, s38, s17, v11                                ; d541000b 042c2226
	v_mad_f32 v15, s40, s26, v15                                ; d541000f 043c3428
	v_mad_f32 v12, s36, s21, v12                                ; d541000c 04302a24
	v_mad_f32 v13, s37, s21, v13                                ; d541000d 04342a25
	v_mad_f32 v16, s41, s26, v16                                ; d5410010 04403429
	v_mad_f32 v14, s38, s21, v14                                ; d541000e 04382a26
	v_mad_f32 v17, s42, s26, v17                                ; d5410011 0444342a
	v_mad_f32 v9, s32, s16, v9                                  ; d5410009 04242020
	v_mul_f32_e64 v18, s44, s31                                 ; d5080012 00003e2c
	v_mul_f32_e64 v19, s45, s31                                 ; d5080013 00003e2d
	v_mad_f32 v10, s33, s16, v10                                ; d541000a 04282021
	v_mad_f32 v11, s34, s16, v11                                ; d541000b 042c2022
	v_mul_f32_e64 v20, s46, s31                                 ; d5080014 00003e2e
	v_mad_f32 v15, s36, s25, v15                                ; d541000f 043c3224
	v_mad_f32 v12, s32, s20, v12                                ; d541000c 04302820
	v_mad_f32 v13, s33, s20, v13                                ; d541000d 04342821
	v_mad_f32 v16, s37, s25, v16                                ; d5410010 04403225
	v_mad_f32 v14, s34, s20, v14                                ; d541000e 04382822
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
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v18, v15, v4                                  ; 3e24090f
	v_mac_f32_e32 v20, v17, v4                                  ; 3e280911
	v_mac_f32_e32 v19, v16, v4                                  ; 3e260910
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v21, s24, v7                                  ; 102a0e18
	v_mul_f32_e32 v22, s25, v7                                  ; 102c0e19
	v_mul_f32_e32 v7, s26, v7                                   ; 100e0e1a
	v_mac_f32_e32 v18, v12, v3                                  ; 3e24070c
	v_mac_f32_e32 v20, v14, v3                                  ; 3e28070e
	v_mac_f32_e32 v19, v13, v3                                  ; 3e26070d
	v_mac_f32_e32 v21, s20, v6                                  ; 3e2a0c14
	v_mac_f32_e32 v22, s21, v6                                  ; 3e2c0c15
	v_mac_f32_e32 v7, s22, v6                                   ; 3e0e0c16
	v_mac_f32_e32 v18, v9, v2                                   ; 3e240509
	v_mac_f32_e32 v20, v11, v2                                  ; 3e28050b
	v_mac_f32_e32 v19, v10, v2                                  ; 3e26050a
	v_mac_f32_e32 v21, s16, v5                                  ; 3e2a0a10
	v_mac_f32_e32 v22, s17, v5                                  ; 3e2c0a11
	v_mac_f32_e32 v7, s18, v5                                   ; 3e0e0a12
	ds_write2_b32 v8, v22, v7 offset0:4 offset1:5               ; d8380504 00071608
	ds_write2_b32 v8, v18, v19 offset1:1                        ; d8380100 00131208
	ds_write2_b32 v8, v20, v21 offset0:2 offset1:3              ; d8380302 00151408
BB6:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_lshl_b32 s0, s3, 8                                        ; 8f008803
	s_pack_ll_b32_b16 s11, s11, 0                               ; 990b800b
	s_bfe_u64 s[0:1], -1, s0                                    ; 948000c1
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_cbranch_execz BB21                                        ; bf88016a
BB7:
	s_mov_b32 s0, s11                                           ; be80030b
	s_movk_i32 s11, 0x8000                                      ; b00b8000
	s_load_dwordx4 s[4:7], s[10:11], null                       ; f4080105 fa000000
	v_mad_u32_u16 v2, 36, v0, 0                                 ; d7730002 020200a4
	ds_read2_b32 v[4:5], v2 offset1:1                           ; d8dc0100 04000002
	ds_read2_b32 v[6:7], v2 offset0:2 offset1:3                 ; d8dc0302 06000002
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[16:31], s[4:7], 0x40               ; f4300402 fa000040
	s_buffer_load_dwordx16 s[32:47], s[4:7], null               ; f4300802 fa000000
	s_bfe_u32 s1, s3, 0x40018                                   ; 9381ff03 00040018
	v_mov_b32_e32 v9, 1.0                                       ; 7e1202f2
	v_mov_b32_e32 v10, 0                                        ; 7e140280
	v_mov_b32_e32 v11, 4                                        ; 7e160284
	s_mov_b32 s4, 0x3ca3d70a                                    ; be8403ff 3ca3d70a
	v_mov_b32_e32 v14, 5                                        ; 7e1c0285
	v_mad_u32_u16 v0, 36, v0, 0 op_sel:[0,1,0,0]                ; d7731000 020200a4
	s_lshl_b32 s1, s1, 6                                        ; 8f018601
	v_mbcnt_lo_u32_b32 v3, -1, s1                               ; d7650003 000002c1
	v_mbcnt_hi_u32_b32 v3, -1, v3                               ; d7660003 000206c1
	v_mul_u32_u24_e32 v3, 6, v3                                 ; 16060686
	v_mad_u32_u16 v1, 36, v1, 0                                 ; d7730001 020202a4
	v_add_nc_u32_e32 v17, 3, v3                                 ; 4a220683
	v_add_nc_u32_e32 v15, 2, v3                                 ; 4a1e0682
	v_add_nc_u32_e32 v12, 1, v3                                 ; 4a180681
	v_bfe_u32 v8, v3, 5, 1                                      ; d5480008 02050b03
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v20, s25, v6, s29                                 ; d5410014 00760c19
	v_mad_f32 v19, s24, v6, s28                                 ; d5410013 00720c18
	v_mad_f32 v21, s26, v6, s30                                 ; d5410015 007a0c1a
	v_mad_f32 v22, s27, v6, s31                                 ; d5410016 007e0c1b
	v_bfe_u32 v18, v17, 5, 1                                    ; d5480012 02050b11
	v_bfe_u32 v16, v15, 5, 1                                    ; d5480010 02050b0f
	v_bfe_u32 v13, v12, 5, 1                                    ; d548000d 02050b0c
	v_xor_b32_e32 v8, v3, v8                                    ; 3a101103
	v_mac_f32_e32 v20, s21, v5                                  ; 3e280a15
	v_mac_f32_e32 v19, s20, v5                                  ; 3e260a14
	v_mac_f32_e32 v21, s22, v5                                  ; 3e2a0a16
	v_mac_f32_e32 v22, s23, v5                                  ; 3e2c0a17
	v_xor_b32_e32 v17, v17, v18                                 ; 3a222511
	v_xor_b32_e32 v15, v15, v16                                 ; 3a1e210f
	v_xor_b32_e32 v12, v12, v13                                 ; 3a181b0c
	v_mad_u32_u24 v8, 28, v8, s0                                ; d5430008 0002109c
	v_mac_f32_e32 v20, s17, v4                                  ; 3e280811
	v_mac_f32_e32 v19, s16, v4                                  ; 3e260810
	v_mac_f32_e32 v21, s18, v4                                  ; 3e2a0812
	v_mac_f32_e32 v22, s19, v4                                  ; 3e2c0813
	v_mac_f32_e32 v4, s4, v7                                    ; 3e080e04
	v_mad_u32_u24 v17, 28, v17, s0                              ; d5430011 0002229c
	v_mad_u32_u24 v15, 28, v15, s0                              ; d543000f 00021e9c
	v_mad_u32_u24 v12, 28, v12, s0                              ; d543000c 0002189c
	v_mul_f32_e32 v23, s44, v22                                 ; 102e2c2c
	v_mul_f32_e32 v25, s46, v22                                 ; 10322c2e
	v_mul_f32_e32 v24, s45, v22                                 ; 10302c2d
	v_mul_f32_e32 v22, s47, v22                                 ; 102c2c2f
	v_mac_f32_e32 v23, s40, v21                                 ; 3e2e2a28
	v_mac_f32_e32 v25, s42, v21                                 ; 3e322a2a
	v_mac_f32_e32 v24, s41, v21                                 ; 3e302a29
	v_mac_f32_e32 v22, s43, v21                                 ; 3e2c2a2b
	v_mac_f32_e32 v23, s36, v20                                 ; 3e2e2824
	v_mac_f32_e32 v25, s38, v20                                 ; 3e322826
	v_mac_f32_e32 v24, s37, v20                                 ; 3e302825
	v_mac_f32_e32 v22, s39, v20                                 ; 3e2c2827
	v_mac_f32_e32 v23, s32, v19                                 ; 3e2e2620
	v_mac_f32_e32 v25, s34, v19                                 ; 3e322622
	v_mac_f32_e32 v24, s33, v19                                 ; 3e302621
	v_mac_f32_e32 v22, s35, v19                                 ; 3e2c2623
	ds_write2_b32 v8, v23, v24 offset0:1 offset1:2              ; d8380201 00181708
	ds_write2_b32 v8, v25, v22 offset0:3 offset1:4              ; d8380403 00161908
	ds_write2_b32 v8, v9, v10 offset0:5 offset1:6               ; d8380605 000a0908
	ds_write_b8 v8, v11 offset:28                               ; d878001c 00000b08
	ds_read2_b32 v[18:19], v2 offset0:4 offset1:5               ; d8dc0504 12000002
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v6, s4, v19                                   ; 3e0c2604
	v_mac_f32_e32 v5, s4, v18                                   ; 3e0a2404
	v_mad_f32 v28, s26, v6, s30                                 ; d541001c 007a0c1a
	v_mad_f32 v27, s25, v6, s29                                 ; d541001b 00760c19
	v_mad_f32 v26, s24, v6, s28                                 ; d541001a 00720c18
	v_mad_f32 v6, s27, v6, s31                                  ; d5410006 007e0c1b
	v_mac_f32_e32 v28, s22, v5                                  ; 3e380a16
	v_mac_f32_e32 v27, s21, v5                                  ; 3e360a15
	v_mac_f32_e32 v26, s20, v5                                  ; 3e340a14
	v_mac_f32_e32 v6, s23, v5                                   ; 3e0c0a17
	v_mac_f32_e32 v28, s18, v4                                  ; 3e380812
	v_mac_f32_e32 v27, s17, v4                                  ; 3e360811
	v_mac_f32_e32 v26, s16, v4                                  ; 3e340810
	v_mac_f32_e32 v6, s19, v4                                   ; 3e0c0813
	v_mul_f32_e32 v29, s44, v6                                  ; 103a0c2c
	v_mul_f32_e32 v31, s46, v6                                  ; 103e0c2e
	v_mul_f32_e32 v30, s45, v6                                  ; 103c0c2d
	v_mul_f32_e32 v6, s47, v6                                   ; 100c0c2f
	v_mac_f32_e32 v29, s40, v28                                 ; 3e3a3828
	v_mac_f32_e32 v31, s42, v28                                 ; 3e3e382a
	v_mac_f32_e32 v30, s41, v28                                 ; 3e3c3829
	v_mac_f32_e32 v6, s43, v28                                  ; 3e0c382b
	v_mac_f32_e32 v29, s36, v27                                 ; 3e3a3624
	v_mac_f32_e32 v31, s38, v27                                 ; 3e3e3626
	v_mac_f32_e32 v30, s37, v27                                 ; 3e3c3625
	v_mac_f32_e32 v6, s39, v27                                  ; 3e0c3627
	v_mac_f32_e32 v29, s32, v26                                 ; 3e3a3420
	v_mac_f32_e32 v31, s34, v26                                 ; 3e3e3422
	v_mac_f32_e32 v30, s33, v26                                 ; 3e3c3421
	v_mac_f32_e32 v6, s35, v26                                  ; 3e0c3423
	ds_write2_b32 v12, v29, v30 offset0:1 offset1:2             ; d8380201 001e1d0c
	ds_write2_b32 v12, v31, v6 offset0:3 offset1:4              ; d8380403 00061f0c
	ds_write2_b32 v12, v10, v9 offset0:5 offset1:6              ; d8380605 00090a0c
	ds_write_b8 v12, v14 offset:28                              ; d878001c 00000e0c
	ds_read2_b32 v[4:5], v0 offset1:1                           ; d8dc0100 04000000
	ds_read2_b32 v[6:7], v0 offset0:2 offset1:3                 ; d8dc0302 06000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v33, s25, v6, s29                                 ; d5410021 00760c19
	v_mad_f32 v35, s27, v6, s31                                 ; d5410023 007e0c1b
	v_mad_f32 v34, s26, v6, s30                                 ; d5410022 007a0c1a
	v_mad_f32 v32, s24, v6, s28                                 ; d5410020 00720c18
	v_mac_f32_e32 v33, s21, v5                                  ; 3e420a15
	v_mac_f32_e32 v35, s23, v5                                  ; 3e460a17
	v_mac_f32_e32 v34, s22, v5                                  ; 3e440a16
	v_mac_f32_e32 v32, s20, v5                                  ; 3e400a14
	v_mac_f32_e32 v33, s17, v4                                  ; 3e420811
	v_mac_f32_e32 v35, s19, v4                                  ; 3e460813
	v_mac_f32_e32 v34, s18, v4                                  ; 3e440812
	v_mac_f32_e32 v32, s16, v4                                  ; 3e400810
	v_mul_f32_e32 v38, s46, v35                                 ; 104c462e
	v_mul_f32_e32 v37, s45, v35                                 ; 104a462d
	v_mul_f32_e32 v36, s44, v35                                 ; 1048462c
	v_mul_f32_e32 v35, s47, v35                                 ; 1046462f
	v_mac_f32_e32 v38, s42, v34                                 ; 3e4c442a
	v_mac_f32_e32 v37, s41, v34                                 ; 3e4a4429
	v_mac_f32_e32 v36, s40, v34                                 ; 3e484428
	v_mac_f32_e32 v35, s43, v34                                 ; 3e46442b
	v_mac_f32_e32 v38, s38, v33                                 ; 3e4c4226
	v_mac_f32_e32 v37, s37, v33                                 ; 3e4a4225
	v_mac_f32_e32 v36, s36, v33                                 ; 3e484224
	v_mac_f32_e32 v35, s39, v33                                 ; 3e464227
	v_mac_f32_e32 v38, s34, v32                                 ; 3e4c4022
	v_mac_f32_e32 v37, s33, v32                                 ; 3e4a4021
	v_mac_f32_e32 v36, s32, v32                                 ; 3e484020
	v_mac_f32_e32 v35, s35, v32                                 ; 3e464023
	ds_write2_b32 v15, v36, v37 offset0:1 offset1:2             ; d8380201 0025240f
	ds_write2_b32 v15, v38, v35 offset0:3 offset1:4             ; d8380403 0023260f
	ds_write2_b32 v15, v9, v10 offset0:5 offset1:6              ; d8380605 000a090f
	ds_write_b8 v15, v11 offset:28                              ; d878001c 00000b0f
	ds_read2_b32 v[12:13], v0 offset0:4 offset1:5               ; d8dc0504 0c000000
	v_mac_f32_e32 v4, s4, v7                                    ; 3e080e04
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v5, s4, v12                                   ; 3e0a1804
	v_mac_f32_e32 v6, s4, v13                                   ; 3e0c1a04
	v_mad_f32 v40, s25, v6, s29                                 ; d5410028 00760c19
	v_mad_f32 v41, s26, v6, s30                                 ; d5410029 007a0c1a
	v_mad_f32 v39, s24, v6, s28                                 ; d5410027 00720c18
	v_mad_f32 v6, s27, v6, s31                                  ; d5410006 007e0c1b
	v_mac_f32_e32 v40, s21, v5                                  ; 3e500a15
	v_mac_f32_e32 v41, s22, v5                                  ; 3e520a16
	v_mac_f32_e32 v39, s20, v5                                  ; 3e4e0a14
	v_mac_f32_e32 v6, s23, v5                                   ; 3e0c0a17
	v_mac_f32_e32 v40, s17, v4                                  ; 3e500811
	v_mac_f32_e32 v41, s18, v4                                  ; 3e520812
	v_mac_f32_e32 v39, s16, v4                                  ; 3e4e0810
	v_mac_f32_e32 v6, s19, v4                                   ; 3e0c0813
	v_mul_f32_e32 v0, s46, v6                                   ; 10000c2e
	v_mul_f32_e32 v43, s45, v6                                  ; 10560c2d
	v_mul_f32_e32 v42, s44, v6                                  ; 10540c2c
	v_mul_f32_e32 v6, s47, v6                                   ; 100c0c2f
	v_mac_f32_e32 v0, s42, v41                                  ; 3e00522a
	v_mac_f32_e32 v43, s41, v41                                 ; 3e565229
	v_mac_f32_e32 v42, s40, v41                                 ; 3e545228
	v_mac_f32_e32 v6, s43, v41                                  ; 3e0c522b
	v_mac_f32_e32 v0, s38, v40                                  ; 3e005026
	v_mac_f32_e32 v43, s37, v40                                 ; 3e565025
	v_mac_f32_e32 v42, s36, v40                                 ; 3e545024
	v_mac_f32_e32 v6, s39, v40                                  ; 3e0c5027
	v_mac_f32_e32 v0, s34, v39                                  ; 3e004e22
	v_mac_f32_e32 v43, s33, v39                                 ; 3e564e21
	v_mac_f32_e32 v42, s32, v39                                 ; 3e544e20
	v_mac_f32_e32 v6, s35, v39                                  ; 3e0c4e23
	ds_write2_b32 v17, v42, v43 offset0:1 offset1:2             ; d8380201 002b2a11
	ds_write2_b32 v17, v0, v6 offset0:3 offset1:4               ; d8380403 00060011
	ds_write2_b32 v17, v10, v9 offset0:5 offset1:6              ; d8380605 00090a11
	ds_write_b8 v17, v14 offset:28                              ; d878001c 00000e11
	ds_read2_b32 v[4:5], v1 offset1:1                           ; d8dc0100 04000001
	ds_read2_b32 v[6:7], v1 offset0:2 offset1:3                 ; d8dc0302 06000001
	v_add_nc_u32_e32 v2, 4, v3                                  ; 4a040684
	v_bfe_u32 v8, v2, 5, 1                                      ; d5480008 02050b02
	v_xor_b32_e32 v2, v2, v8                                    ; 3a041102
	v_mad_u32_u24 v2, 28, v2, s0                                ; d5430002 0002049c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v13, s25, v6, s29                                 ; d541000d 00760c19
	v_mad_f32 v15, s26, v6, s30                                 ; d541000f 007a0c1a
	v_mad_f32 v12, s24, v6, s28                                 ; d541000c 00720c18
	v_mad_f32 v16, s27, v6, s31                                 ; d5410010 007e0c1b
	v_mac_f32_e32 v13, s21, v5                                  ; 3e1a0a15
	v_mac_f32_e32 v15, s22, v5                                  ; 3e1e0a16
	v_mac_f32_e32 v12, s20, v5                                  ; 3e180a14
	v_mac_f32_e32 v16, s23, v5                                  ; 3e200a17
	v_mac_f32_e32 v13, s17, v4                                  ; 3e1a0811
	v_mac_f32_e32 v15, s18, v4                                  ; 3e1e0812
	v_mac_f32_e32 v12, s16, v4                                  ; 3e180810
	v_mac_f32_e32 v16, s19, v4                                  ; 3e200813
	v_mul_f32_e32 v19, s46, v16                                 ; 1026202e
	v_mul_f32_e32 v17, s44, v16                                 ; 1022202c
	v_mul_f32_e32 v18, s45, v16                                 ; 1024202d
	v_mul_f32_e32 v16, s47, v16                                 ; 1020202f
	v_mac_f32_e32 v19, s42, v15                                 ; 3e261e2a
	v_mac_f32_e32 v17, s40, v15                                 ; 3e221e28
	v_mac_f32_e32 v18, s41, v15                                 ; 3e241e29
	v_mac_f32_e32 v16, s43, v15                                 ; 3e201e2b
	v_mac_f32_e32 v19, s38, v13                                 ; 3e261a26
	v_mac_f32_e32 v17, s36, v13                                 ; 3e221a24
	v_mac_f32_e32 v18, s37, v13                                 ; 3e241a25
	v_mac_f32_e32 v16, s39, v13                                 ; 3e201a27
	v_mac_f32_e32 v19, s34, v12                                 ; 3e261822
	v_mac_f32_e32 v17, s32, v12                                 ; 3e221820
	v_mac_f32_e32 v18, s33, v12                                 ; 3e241821
	v_mac_f32_e32 v16, s35, v12                                 ; 3e201823
	ds_write2_b32 v2, v17, v18 offset0:1 offset1:2              ; d8380201 00121102
	ds_write2_b32 v2, v19, v16 offset0:3 offset1:4              ; d8380403 00101302
	ds_write2_b32 v2, v9, v10 offset0:5 offset1:6               ; d8380605 000a0902
	ds_write_b8 v2, v11 offset:28                               ; d878001c 00000b02
	ds_read2_b32 v[0:1], v1 offset0:4 offset1:5                 ; d8dc0504 00000001
	v_mac_f32_e32 v4, s4, v7                                    ; 3e080e04
	v_add_nc_u32_e32 v3, 5, v3                                  ; 4a060685
	s_bfe_u32 s12, s12, 0x30006                                 ; 938cff0c 00030006
	s_bitcmp1_b32 s12, 0                                        ; bf0d800c
	v_bfe_u32 v20, v3, 5, 1                                     ; d5480014 02050b03
	s_cselect_b64 s[6:7], -1, 0                                 ; 858680c1
	v_xor_b32_e32 v3, v3, v20                                   ; 3a062903
	v_mad_u32_u24 v3, 28, v3, s0                                ; d5430003 0002069c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v5, s4, v0                                    ; 3e0a0004
	v_mac_f32_e32 v6, s4, v1                                    ; 3e0c0204
	v_mad_f32 v22, s25, v6, s29                                 ; d5410016 00760c19
	v_mad_f32 v23, s26, v6, s30                                 ; d5410017 007a0c1a
	v_mad_f32 v21, s24, v6, s28                                 ; d5410015 00720c18
	v_mad_f32 v6, s27, v6, s31                                  ; d5410006 007e0c1b
	v_mac_f32_e32 v22, s21, v5                                  ; 3e2c0a15
	v_mac_f32_e32 v23, s22, v5                                  ; 3e2e0a16
	v_mac_f32_e32 v21, s20, v5                                  ; 3e2a0a14
	v_mac_f32_e32 v6, s23, v5                                   ; 3e0c0a17
	v_mac_f32_e32 v22, s17, v4                                  ; 3e2c0811
	v_mac_f32_e32 v23, s18, v4                                  ; 3e2e0812
	v_mac_f32_e32 v21, s16, v4                                  ; 3e2a0810
	v_mac_f32_e32 v6, s19, v4                                   ; 3e0c0813
	v_mul_f32_e32 v24, s44, v6                                  ; 10300c2c
	v_mul_f32_e32 v26, s46, v6                                  ; 10340c2e
	v_mul_f32_e32 v25, s45, v6                                  ; 10320c2d
	v_mul_f32_e32 v6, s47, v6                                   ; 100c0c2f
	v_mac_f32_e32 v24, s40, v23                                 ; 3e302e28
	v_mac_f32_e32 v26, s42, v23                                 ; 3e342e2a
	v_mac_f32_e32 v25, s41, v23                                 ; 3e322e29
	v_mac_f32_e32 v6, s43, v23                                  ; 3e0c2e2b
	v_mac_f32_e32 v24, s36, v22                                 ; 3e302c24
	v_mac_f32_e32 v26, s38, v22                                 ; 3e342c26
	v_mac_f32_e32 v25, s37, v22                                 ; 3e322c25
	v_mac_f32_e32 v6, s39, v22                                  ; 3e0c2c27
	v_mac_f32_e32 v24, s32, v21                                 ; 3e302a20
	v_mac_f32_e32 v26, s34, v21                                 ; 3e342a22
	v_mac_f32_e32 v25, s33, v21                                 ; 3e322a21
	v_mac_f32_e32 v6, s35, v21                                  ; 3e0c2a23
	ds_write2_b32 v3, v24, v25 offset0:1 offset1:2              ; d8380201 00191803
	ds_write2_b32 v3, v26, v6 offset0:3 offset1:4               ; d8380403 00061a03
	ds_write2_b32 v3, v10, v9 offset0:5 offset1:6               ; d8380605 00090a03
	ds_write_b8 v3, v14 offset:28                               ; d878001c 00000e03
	s_cbranch_scc0 BB16                                         ; bf840012
BB8:
	s_and_b64 s[4:5], -1, exec                                  ; 87847ec1
	s_bcnt1_i32_b64 s1, s[4:5]                                  ; be811004
	s_ff1_i32_b64 s4, exec                                      ; be84147e
	s_lshl_b64 s[4:5], 1, s4                                    ; 8f840481
	s_and_b64 s[4:5], s[6:7], s[4:5]                            ; 87840406
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_and_saveexec_b64 s[4:5], s[4:5]                           ; be842404
	s_cbranch_execz BB16                                        ; bf88000a
BB9:
	s_mul_i32 s6, s1, 3                                         ; 93068301
	s_movk_i32 m0, 0x100                                        ; b07c0100
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	v_mov_b32_e32 v0, s6                                        ; 7e000206
	ds_add_u32 v1, v0 gds                                       ; d8020000 00000001
	v_mov_b32_e32 v2, s1                                        ; 7e040201
	v_mov_b32_e32 v3, 4                                         ; 7e060284
	ds_add_u32 v3, v2 gds                                       ; d8020000 00000203
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
	v_mad_u32_u24 v1, 28, v1, s11                               ; d5430001 002e029c
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 s2, v0                                    ; 7d280002
	s_cbranch_execz BB25                                        ; bf880002
BB22:
	ds_read_u8 v2, v1 offset:28                                 ; d8e8001c 02000001
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
	v_mul_lo_u32 v3, 28, v3                                     ; d5690003 0002069c
	v_add_nc_u32_e32 v3, s11, v3                                ; 4a06060b
	ds_write_b8 v3, v4 offset:29                                ; d878001d 00000403
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
	s_cbranch_execz BB63                                        ; bf88000e
BB58:
	ds_read_u8 v1, v1 offset:29                                 ; d8e8001d 01000001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_bfe_u32 v0, v1, 5, 1                                      ; d5480000 02050b01
	v_xor_b32_e32 v1, v1, v0                                    ; 3a020101
	v_mad_u32_u24 v1, 28, v1, s11                               ; d5430001 002e029c
	ds_read2_b32 v[4:5], v1 offset0:1 offset1:2                 ; d8dc0201 04000001
	ds_read2_b32 v[6:7], v1 offset0:3 offset1:4                 ; d8dc0403 06000001
	ds_read2_b32 v[0:1], v1 offset0:5 offset1:6                 ; d8dc0605 00000001
BB63:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, vcc                                         ; befe046a
	s_cbranch_execz BB69                                        ; bf880002
BB64:
	exp prim v2, off, off, off done                             ; f8000941 80808002
BB69:
	s_waitcnt expcnt(0)                                         ; bf8cff0f
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_cbranch_execz BB75                                        ; bf880005
BB70:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	exp pos0 v4, v5, v6, v7 done vm                             ; f80018cf 07060504
	exp param0 v0, v1, off, off                                 ; f8000203 80800100
BB75:
	s_endpgm                                                    ; bf810000
