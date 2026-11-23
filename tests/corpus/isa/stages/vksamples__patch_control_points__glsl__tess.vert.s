# Vertex Shader as LS + Tessellation Control Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s5, 0, s3                                 ; 99050380
	s_bfe_u64 exec, -1, s5                                      ; 94fe05c1
	s_cbranch_execz BB57                                        ; bf88017e
BB1:
	s_mov_b32 s5, s9                                            ; be850309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_load_dwordx4 s[16:19], s[8:9], null                       ; f4080404 fa000000
	v_add_nc_u32_e32 v2, s5, v2                                 ; 4a040405
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx3 v[4:6], v2, s[16:19], 0 idxen           ; e03c2000 80040402
	v_mul_u32_u24_e32 v3, 20, v3                                ; 16060694
	s_lshl_b32 s6, s3, 8                                        ; 8f068803
	s_bfe_u64 s[6:7], -1, s6                                    ; 948606c1
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v4, s11, v4                                   ; 0608080b
	v_add_f32_e32 v5, s12, v5                                   ; 060a0a0c
	v_add_f32_e32 v6, s13, v6                                   ; 060c0c0d
	v_mad_f32 v7, 0xb6321453, v6, -v5                           ; d5410007 84160cff b6321453
	v_mad_f32 v5, 0x36321453, v5, -v6                           ; d5410005 841a0aff 36321453
	ds_write2_b32 v3, v4, v7 offset0:4 offset1:5                ; d8380504 00070403
	ds_write_b32 v3, v5 offset:24                               ; d8340018 00000503
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_saveexec_b64 s[6:7], s[6:7]                           ; be862406
	s_cbranch_execz BB46                                        ; bf880135
BB2:
	v_readfirstlane_b32 s5, v1                                  ; 7e0a0501
	s_bfe_u32 s8, s5, 0x50008                                   ; 9388ff05 00050008
	s_bfe_u32 s5, s5, 0x80000                                   ; 9385ff05 00080000
	s_mul_i32 s5, s5, 3                                         ; 93058305
	s_add_u32 s5, s5, s8                                        ; 80050805
	s_mov_b64 s[8:9], 1                                         ; be880481
	s_cmp_lt_u32 s5, 64                                         ; bf0ac005
	s_cselect_b64 s[12:13], -1, 0                               ; 858c80c1
	s_and_b64 s[12:13], s[12:13], s[8:9]                        ; 878c080c
	s_and_saveexec_b64 s[12:13], s[12:13]                       ; be8c240c
	s_cbranch_execz BB8                                         ; bf880004
BB3:
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_mov_b32_e32 v2, 3                                         ; 7e040283
	ds_write_b32 v0, v2                                         ; d8340000 00000200
BB8:
	s_movk_i32 s11, 0x8000                                      ; b00b8000
	s_load_dwordx4 s[16:19], s[10:11], 0x10                     ; f4080405 fa000010
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s5, s[16:19], null                      ; f4200148 fa000000
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cmp_lt_f32_e64 vcc, 1.0, s5                               ; d401006a 00000af2
	s_cbranch_vccz BB10                                         ; bf8600b8
BB9:
	v_mul_u32_u24_sdwa v0, 60, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 160002f9 008606bc
	ds_read2_b32 v[2:3], v0 offset0:4 offset1:5                 ; d8dc0504 02000000
	ds_read_b32 v6, v0 offset:24                                ; d8d80018 06000000
	ds_read2_b32 v[8:9], v0 offset0:14 offset1:15               ; d8dc0f0e 08000000
	ds_read_b32 v10, v0 offset:64                               ; d8d80040 0a000000
	s_load_dwordx4 s[16:19], s[10:11], null                     ; f4080405 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[32:47], s[16:19], 0x40             ; f4300808 fa000040
	s_buffer_load_dwordx16 s[16:31], s[16:19], null             ; f4300408 fa000000
	ds_read2_b32 v[12:13], v0 offset0:9 offset1:10              ; d8dc0a09 0c000000
	ds_read_b32 v0, v0 offset:44                                ; d8d8002c 00000000
	s_mov_b32 s10, 0x3fcccccd                                   ; be8a03ff 3fcccccd
	v_mul_f32_e64 v16, s5, 0x3ecccccd                           ; d5080010 0001fe05 3ecccccd
	v_add_f32_e64 v11, v8, v2 div:2                             ; d503000b 18020508
	v_add_f32_e64 v14, v9, v3 div:2                             ; d503000e 18020709
	v_add_f32_e64 v15, v10, v6 div:2                            ; d503000f 18020d0a
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v18, s41, v15, s45                                ; d5410012 00b61e29
	v_mad_f32 v19, s42, v15, s46                                ; d5410013 00ba1e2a
	v_mad_f32 v17, s40, v15, s44                                ; d5410011 00b21e28
	v_mad_f32 v15, s43, v15, s47                                ; d541000f 00be1e2b
	v_add_f32_e64 v2, v2, v12 div:2                             ; d5030002 18021902
	v_add_f32_e64 v3, v3, v13 div:2                             ; d5030003 18021b03
	v_add_f32_e64 v12, v12, v8 div:2                            ; d503000c 1802110c
	v_mac_f32_e32 v18, s37, v14                                 ; 3e241c25
	v_add_f32_e64 v13, v13, v9 div:2                            ; d503000d 1802130d
	v_mac_f32_e32 v19, s38, v14                                 ; 3e261c26
	v_mac_f32_e32 v17, s36, v14                                 ; 3e221c24
	v_mac_f32_e32 v15, s39, v14                                 ; 3e1e1c27
	v_add_f32_e64 v6, v6, v0 div:2                              ; d5030006 18020106
	v_add_f32_e64 v0, v0, v10 div:2                             ; d5030000 18021500
	v_mac_f32_e32 v18, s33, v11                                 ; 3e241621
	v_mac_f32_e32 v19, s34, v11                                 ; 3e261622
	v_mac_f32_e32 v17, s32, v11                                 ; 3e221620
	v_mac_f32_e32 v15, s35, v11                                 ; 3e1e1623
	v_mad_f32 v9, s42, v6, s46                                  ; d5410009 00ba0c2a
	v_mad_f32 v8, s41, v6, s45                                  ; d5410008 00b60c29
	v_mad_f32 v23, s40, v6, s44                                 ; d5410017 00b20c28
	v_mad_f32 v6, s43, v6, s47                                  ; d5410006 00be0c2b
	v_mul_f32_e32 v21, s29, v15                                 ; 102a1e1d
	v_mul_f32_e32 v22, s30, v15                                 ; 102c1e1e
	v_mul_f32_e32 v20, s28, v15                                 ; 10281e1c
	v_mul_f32_e32 v15, s31, v15                                 ; 101e1e1f
	v_mac_f32_e32 v9, s38, v3                                   ; 3e120626
	v_mac_f32_e32 v8, s37, v3                                   ; 3e100625
	v_mac_f32_e32 v23, s36, v3                                  ; 3e2e0624
	v_mac_f32_e32 v6, s39, v3                                   ; 3e0c0627
	v_mac_f32_e32 v21, s25, v19                                 ; 3e2a2619
	v_mac_f32_e32 v22, s26, v19                                 ; 3e2c261a
	v_mac_f32_e32 v20, s24, v19                                 ; 3e282618
	v_mac_f32_e32 v15, s27, v19                                 ; 3e1e261b
	v_mac_f32_e32 v8, s33, v2                                   ; 3e100421
	v_mac_f32_e32 v23, s32, v2                                  ; 3e2e0420
	v_mac_f32_e32 v21, s21, v18                                 ; 3e2a2415
	v_mac_f32_e32 v22, s22, v18                                 ; 3e2c2416
	v_mac_f32_e32 v20, s20, v18                                 ; 3e282414
	v_mac_f32_e32 v15, s23, v18                                 ; 3e1e2417
	v_mac_f32_e32 v9, s34, v2                                   ; 3e120422
	v_mac_f32_e32 v6, s35, v2                                   ; 3e0c0423
	v_mac_f32_e32 v21, s17, v17                                 ; 3e2a2211
	v_mac_f32_e32 v22, s18, v17                                 ; 3e2c2212
	v_mac_f32_e32 v20, s16, v17                                 ; 3e282210
	v_mac_f32_e32 v15, s19, v17                                 ; 3e1e2213
	v_mul_f32_e32 v11, s28, v6                                  ; 10160c1c
	v_mul_f32_e32 v14, s29, v6                                  ; 101c0c1d
	v_mul_f32_e32 v22, v22, v22                                 ; 102c2d16
	v_mac_f32_e32 v11, s24, v9                                  ; 3e161218
	v_mac_f32_e32 v14, s25, v9                                  ; 3e1c1219
	v_mac_f32_e32 v22, v15, v15                                 ; 3e2c1f0f
	v_mul_f32_e32 v15, s30, v6                                  ; 101e0c1e
	v_mul_f32_e32 v6, s31, v6                                   ; 100c0c1f
	v_mac_f32_e32 v11, s20, v8                                  ; 3e161014
	v_mac_f32_e32 v14, s21, v8                                  ; 3e1c1015
	v_mac_f32_e32 v22, v21, v21                                 ; 3e2c2b15
	v_mac_f32_e32 v15, s26, v9                                  ; 3e1e121a
	v_mac_f32_e32 v6, s27, v9                                   ; 3e0c121b
	v_mac_f32_e32 v11, s16, v23                                 ; 3e162e10
	v_mac_f32_e32 v14, s17, v23                                 ; 3e1c2e11
	v_mac_f32_e32 v22, v20, v20                                 ; 3e2c2914
	v_mac_f32_e32 v15, s22, v8                                  ; 3e1e1016
	v_mac_f32_e32 v6, s23, v8                                   ; 3e0c1017
	v_sqrt_f32_e32 v22, v22                                     ; 7e2c6716
	v_mac_f32_e32 v15, s18, v23                                 ; 3e1e2e12
	v_mac_f32_e32 v6, s19, v23                                  ; 3e0c2e13
	v_mul_f32_e32 v15, v15, v15                                 ; 101e1f0f
	v_cmp_le_f32_e32 vcc, 1.0, v22                              ; 7c062cf2
	v_cmp_gt_f32_e64 s[14:15], s10, v22                         ; d404000e 00022c0a
	v_mad_f32 v20, s40, v0, s44                                 ; d5410014 00b20028
	v_mad_f32 v21, s41, v0, s45                                 ; d5410015 00b60029
	v_mac_f32_e32 v15, v6, v6                                   ; 3e1e0d06
	s_and_b64 vcc, vcc, s[14:15]                                ; 87ea0e6a
	v_mac_f32_e32 v20, s36, v13                                 ; 3e281a24
	v_mac_f32_e32 v21, s37, v13                                 ; 3e2a1a25
	v_cndmask_b32_e32 v10, s5, v16, vcc                         ; 02142005
	v_cmp_le_f32_e32 vcc, s10, v22                              ; 7c062c0a
	v_mad_f32 v22, s42, v0, s46                                 ; d5410016 00ba002a
	v_mad_f32 v0, s43, v0, s47                                  ; d5410000 00be002b
	v_mac_f32_e32 v15, v14, v14                                 ; 3e1e1d0e
	v_mac_f32_e32 v20, s32, v12                                 ; 3e281820
	v_mac_f32_e32 v21, s33, v12                                 ; 3e2a1821
	v_cndmask_b32_e64 v18, v10, 1.0, vcc                        ; d5010012 01a9e50a
	v_mac_f32_e32 v22, s38, v13                                 ; 3e2c1a26
	v_mac_f32_e32 v0, s39, v13                                  ; 3e001a27
	v_mac_f32_e32 v15, v11, v11                                 ; 3e1e170b
	v_mac_f32_e32 v22, s34, v12                                 ; 3e2c1822
	v_mac_f32_e32 v0, s35, v12                                  ; 3e001823
	v_sqrt_f32_e32 v15, v15                                     ; 7e1e670f
	v_mul_f32_e32 v3, s30, v0                                   ; 1006001e
	v_mul_f32_e32 v2, s29, v0                                   ; 1004001d
	v_mul_f32_e32 v23, s28, v0                                  ; 102e001c
	v_mul_f32_e32 v0, s31, v0                                   ; 1000001f
	v_mac_f32_e32 v3, s26, v22                                  ; 3e062c1a
	v_mac_f32_e32 v2, s25, v22                                  ; 3e042c19
	v_mac_f32_e32 v23, s24, v22                                 ; 3e2e2c18
	v_cmp_le_f32_e32 vcc, 1.0, v15                              ; 7c061ef2
	v_mac_f32_e32 v0, s27, v22                                  ; 3e002c1b
	v_cmp_gt_f32_e64 s[14:15], s10, v15                         ; d404000e 00021e0a
	v_mac_f32_e32 v3, s22, v21                                  ; 3e062a16
	v_mac_f32_e32 v2, s21, v21                                  ; 3e042a15
	v_mac_f32_e32 v23, s20, v21                                 ; 3e2e2a14
	v_mac_f32_e32 v0, s23, v21                                  ; 3e002a17
	s_and_b64 vcc, vcc, s[14:15]                                ; 87ea0e6a
	v_mac_f32_e32 v3, s18, v20                                  ; 3e062812
	v_mac_f32_e32 v2, s17, v20                                  ; 3e042811
	v_cndmask_b32_e32 v17, s5, v16, vcc                         ; 02222005
	v_cmp_le_f32_e32 vcc, s10, v15                              ; 7c061e0a
	v_mac_f32_e32 v23, s16, v20                                 ; 3e2e2810
	v_mac_f32_e32 v0, s19, v20                                  ; 3e002813
	v_mul_f32_e32 v3, v3, v3                                    ; 10060703
	v_cndmask_b32_e64 v19, v17, 1.0, vcc                        ; d5010013 01a9e511
	v_mac_f32_e32 v3, v0, v0                                    ; 3e060100
	v_mac_f32_e32 v3, v2, v2                                    ; 3e060502
	v_mac_f32_e32 v3, v23, v23                                  ; 3e062f17
	v_sqrt_f32_e32 v3, v3                                       ; 7e066703
	v_cmp_gt_f32_e64 s[14:15], s10, v3                          ; d404000e 0002060a
	v_cmp_le_f32_e32 vcc, 1.0, v3                               ; 7c0606f2
	s_and_b64 vcc, vcc, s[14:15]                                ; 87ea0e6a
	v_cndmask_b32_e32 v16, s5, v16, vcc                         ; 02202005
	v_cmp_le_f32_e32 vcc, s10, v3                               ; 7c06060a
	v_cndmask_b32_e64 v20, v16, 1.0, vcc                        ; d5010014 01a9e510
	v_add_f32_e64 v21, v18, v20 div:2                           ; d5030015 18022912
	s_branch BB11                                               ; bf820004
BB10:
	v_mov_b32_e32 v18, 1.0                                      ; 7e2402f2
	v_mov_b32_e32 v19, 1.0                                      ; 7e2602f2
	v_mov_b32_e32 v20, 1.0                                      ; 7e2802f2
	v_mov_b32_e32 v21, 1.0                                      ; 7e2a02f2
BB11:
	v_mul_f32_e64 v0, s5, 0x3ecccccd                            ; d5080000 0001fe05 3ecccccd
	v_cmp_eq_f32_e32 vcc, 1.0, v18                              ; 7c0424f2
	v_cmp_eq_f32_e64 s[10:11], v18, v0                          ; d402000a 00020112
	s_nor_b64 s[14:15], vcc, s[10:11]                           ; 8d8e0a6a
	s_andn2_b64 s[10:11], s[10:11], vcc                         ; 8a8a6a0a
	s_barrier                                                   ; bf8a0000
	v_bfe_u32 v2, v1, 8, 5                                      ; d5480002 02151101
	v_cmpx_eq_i32_e32 0, v2                                     ; 7d240480
	s_mov_b64 s[16:17], exec                                    ; be90047e
BB12:
	v_min3_f32 v0, v18, v19, v20                                ; d5510000 04522712
	v_max3_f32 v2, v18, v19, v20                                ; d5540002 04522712
	v_cmp_lt_f32_e64 s[18:19], 0, v0                            ; d4010012 00020080
	v_max_f32_e32 v2, v2, v21                                   ; 20042b02
	v_cmp_ge_f32_e64 s[20:21], 1.0, v2                          ; d4060014 000204f2
	s_nand_b64 s[20:21], s[20:21], s[18:19]                     ; 8c941214
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_andn2_b64 s[18:19], exec, s[18:19]                        ; 8a92127e
	s_cselect_b64 s[18:19], -1, 0                               ; 859280c1
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_mov_b32 s5, src_scc                                       ; be8503fd
	s_and_b64 s[18:19], s[20:21], exec                          ; 87927e14
	s_cselect_b64 s[18:19], -1, 0                               ; 859280c1
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_lshl_b32 s18, src_scc, 1                                  ; 8f1281fd
	s_or_b32 s5, s5, s18                                        ; 88051205
	s_mov_b64 s[18:19], 7                                       ; be920487
	s_and_saveexec_b64 s[18:19], s[18:19]                       ; be922412
BB13:
	s_ff1_i32_b64 s20, exec                                     ; be94147e
	s_lshl_b64 s[20:21], 1, s20                                 ; 8f941481
	s_and_saveexec_b64 s[20:21], s[20:21]                       ; be942414
	s_cbranch_execz BB29                                        ; bf880004
BB14:
	v_mov_b32_e32 v0, s5                                        ; 7e000205
	v_mov_b32_e32 v2, 0                                         ; 7e040280
	ds_and_b32 v2, v0                                           ; d8240000 00000002
BB29:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_b64 exec, s[8:9], exec                                ; 87fe7e08
BB30:
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	ds_read_b32 v0, v0                                          ; d8d80000 00000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_readfirstlane_b32 s5, v0                                  ; 7e0a0500
BB35:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_and_b64 exec, s[16:17], exec                              ; 87fe7e10
BB36:
	s_load_dwordx4 s[16:19], s[0:1], 0x50                       ; f4080400 fa000050
	v_lshlrev_b32_sdwa v0, 4, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 340002f9 00860684
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[18:21], v0, s[16:19], s4 offen glc   ; e0785000 04041200
BB41:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_cmp_lg_i32 s5, 1                                          ; bf018105
	v_cndmask_b32_e64 v0, 0, 1.0, vcc                           ; d5010000 01a9e480
	v_cndmask_b32_e64 v2, 0, 1.0, s[14:15]                      ; d5010002 0039e480
	v_cndmask_b32_e64 v3, 0, 1.0, s[10:11]                      ; d5010003 0029e480
	s_cselect_b64 s[8:9], -1, 0                                 ; 858880c1
	s_cselect_b32 s4, 0, 0                                      ; 85048080
	v_cndmask_b32_e64 v8, 0, v4, s[8:9]                         ; d5010008 00220880
	v_cndmask_b32_e64 v9, 0, v7, s[8:9]                         ; d5010009 00220e80
	v_cndmask_b32_e64 v10, 0, v5, s[8:9]                        ; d501000a 00220a80
	v_cndmask_b32_e64 v0, 0, v0, s[8:9]                         ; d5010000 00220080
	v_cndmask_b32_e64 v2, 0, v2, s[8:9]                         ; d5010002 00220480
	s_cmp_lg_i32 s4, 0                                          ; bf018004
	v_cndmask_b32_e64 v3, 0, v3, s[8:9]                         ; d5010003 00220680
	s_cselect_b64 s[8:9], -1, 0                                 ; 858880c1
	v_cmp_neq_f32_e32 vcc, 0, v0                                ; 7c1a0080
	v_cmp_neq_f32_e64 s[10:11], 0, v2                           ; d40d000a 00020480
	s_mov_b64 s[14:15], s[8:9]                                  ; be8e0408
	v_cmp_neq_f32_e64 s[12:13], 0, v3                           ; d40d000c 00020680
BB46:
	s_load_dwordx4 s[16:19], s[0:1], 0x60                       ; f4080400 fa000060
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_readfirstlane_b32 s0, v1                                  ; 7e000501
	s_bfe_u32 s1, s0, 0x50008                                   ; 9381ff00 00050008
	s_bfe_u32 s0, s0, 0x80000                                   ; 9380ff00 00080000
	s_mul_i32 s0, s0, 3                                         ; 93008300
	s_add_u32 s0, s0, s1                                        ; 80000100
	s_and_b32 s0, s0, 0xffffffc0                                ; 8700ff00 ffffffc0
	s_bfe_u32 s3, s3, 0x80008                                   ; 9383ff03 00080008
	v_mbcnt_lo_u32_b32 v0, -1, s0                               ; d7650000 000000c1
	s_add_u32 s3, s3, 7                                         ; 80038703
	s_and_b32 s3, s3, -8                                        ; 8703c803
	v_mbcnt_hi_u32_b32 v0, -1, v0                               ; d7660000 000200c1
	s_pack_ll_b32_b16 s3, 0, s3                                 ; 99030380
	s_bfe_u64 s[0:1], -1, s3                                    ; 948003c1
	s_cmp_lg_i32 s5, 1                                          ; bf018105
	s_cselect_b64 s[4:5], -1, 0                                 ; 858480c1
	s_and_b64 s[0:1], s[0:1], s[4:5]                            ; 87800400
	s_and_b64 exec, s[0:1], exec                                ; 87fe7e00
	s_cbranch_execz BB57                                        ; bf880011
BB47:
	v_lshlrev_b32_e32 v0, 4, v0                                 ; 34000084
	v_cndmask_b32_e64 v11, 0, 1.0, vcc                          ; d501000b 01a9e480
	v_cndmask_b32_e64 v7, 0, 1, s[14:15]                        ; d5010007 00390280
	v_cndmask_b32_e64 v6, 0, 1, s[8:9]                          ; d5010006 00210280
	v_cndmask_b32_e64 v5, 0, 1.0, s[12:13]                      ; d5010005 0031e480
	v_cndmask_b32_e64 v4, 0, 1.0, s[10:11]                      ; d5010004 0029e480
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_waitcnt_vscnt null, 0x0                                   ; bbfd0000
	buffer_store_dwordx4 v[8:11], v0, s[16:19], s2 offen glc    ; e0785000 02040800
	buffer_store_dwordx4 v[4:7], v0, s[16:19], s2 offen offset:3072 glc ; e0785c00 02040400
BB57:
	s_endpgm                                                    ; bf810000
