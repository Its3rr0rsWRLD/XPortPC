# Vertex Shader as LS + Tessellation Control Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s5, 0, s3                                 ; 99050380
	s_bfe_u64 exec, -1, s5                                      ; 94fe05c1
	s_cbranch_execz BB6                                         ; bf880019
BB1:
	s_mov_b32 s5, s9                                            ; be850309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[16:23], s[8:9], null                       ; f40c0404 fa000000
	s_load_dwordx4 s[12:15], s[8:9], 0x20                       ; f4080304 fa000020
	v_add_nc_u32_e32 v2, s5, v2                                 ; 4a040405
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx3 v[4:6], v2, s[20:23], 0 idxen offset:16 ; e03c2010 80050402
	buffer_load_dwordx2 v[8:9], v2, s[12:15], 0 idxen offset:32 ; e0342020 80030802
	buffer_load_dwordx3 v[10:12], v2, s[16:19], 0 idxen         ; e03c2000 80040a02
	v_mul_u32_u24_e32 v3, 36, v3                                ; 160606a4
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	ds_write2_b32 v3, v9, v4 offset0:8 offset1:9                ; d8380908 00040903
	ds_write2_b32 v3, v5, v6 offset0:10 offset1:11              ; d8380b0a 00060503
	ds_write2_b32 v3, v10, v11 offset0:4 offset1:5              ; d8380504 000b0a03
	ds_write2_b32 v3, v12, v8 offset0:6 offset1:7               ; d8380706 00080c03
BB6:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_lshl_b32 s5, s3, 8                                        ; 8f058803
	s_bfe_u64 exec, -1, s5                                      ; 94fe05c1
	s_cbranch_execz BB93                                        ; bf88026d
BB7:
	v_readfirstlane_b32 s5, v1                                  ; 7e0a0501
	s_mov_b64 s[6:7], 1                                         ; be860481
	s_bfe_u32 s5, s5, 0x80000                                   ; 9385ff05 00080000
	s_lshl_b32 s5, s5, 2                                        ; 8f058205
	s_cmp_lt_u32 s5, 64                                         ; bf0ac005
	s_cselect_b64 s[8:9], -1, 0                                 ; 858880c1
	s_and_b64 s[8:9], s[8:9], s[6:7]                            ; 87880608
	s_and_saveexec_b64 s[8:9], s[8:9]                           ; be882408
	s_cbranch_execz BB13                                        ; bf880004
BB8:
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_mov_b32_e32 v2, 3                                         ; 7e040283
	ds_write_b32 v0, v2                                         ; d8340000 00000200
BB13:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	v_bfe_u32 v0, v1, 8, 5                                      ; d5480000 02151101
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_eq_i32_e32 0, v0                                     ; 7d240080
	s_mov_b64 vcc, exec                                         ; beea047e
	s_cbranch_execz BB58                                        ; bf880203
BB14:
	s_movk_i32 s11, 0x8000                                      ; b00b8000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[16:23], s[10:11], 0x20                     ; f40c0405 fa000020
	s_load_dwordx4 s[12:15], s[10:11], 0x70                     ; f4080305 fa000070
	s_movk_i32 s5, 0x6c                                         ; b005006c
	v_mul_u32_u24_sdwa v2, s5, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 160402f9 00860605
	ds_read2_b32 v[4:5], v2 offset0:4 offset1:5                 ; d8dc0504 04000002
	ds_read2_b32 v[6:7], v2 offset0:6 offset1:7                 ; d8dc0706 06000002
	ds_read_b32 v9, v2 offset:32                                ; d8d80020 09000002
	s_load_dwordx4 s[24:27], s[10:11], null                     ; f4080605 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_lz  v7, [v7, v9], s[16:23], s[12:15] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f09c010a 00640707 00000009
	s_buffer_load_dword s10, s[24:27], 0xf0                     ; f420028c fa0000f0
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_buffer_load_dwordx4 s[12:15], s[24:27], 0x90              ; f428030c fa000090
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v3, s12, v4                                   ; 1006080c
	v_add_f32_e64 v8, s15, 0x41000000                           ; d5030008 0001fe0f 41000000
	v_mac_f32_e32 v8, s14, v6                                   ; 3e100c0e
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v7, s10, -v7, v5                                  ; d5410007 44160e0a
	s_mov_b64 s[10:11], exec                                    ; be8a047e
	v_mac_f32_e32 v8, s13, v7                                   ; 3e100e0d
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e64 v8, -v3                                   ; d411007e 40020708
BB15:
	s_mov_b64 s[12:13], -1                                      ; be8c04c1
	s_andn2_b64 exec, s[10:11], exec                            ; 8afe7e0a
	s_cbranch_execz BB44                                        ; bf880054
BB18:
	s_buffer_load_dwordx4 s[12:15], s[24:27], 0xa0              ; f428030c fa0000a0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v3, s12, v4                                   ; 1006080c
	v_add_f32_e64 v8, s15, 0x41000000                           ; d5030008 0001fe0f 41000000
	v_mac_f32_e32 v8, s14, v6                                   ; 3e100c0e
	v_mac_f32_e32 v8, s13, v7                                   ; 3e100e0d
	s_mov_b64 s[12:13], exec                                    ; be8c047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e64 v8, -v3                                   ; d411007e 40020708
BB19:
	s_mov_b64 s[14:15], -1                                      ; be8e04c1
	s_andn2_b64 exec, s[12:13], exec                            ; 8afe7e0c
	s_cbranch_execz BB42                                        ; bf880042
BB22:
	s_buffer_load_dwordx4 s[16:19], s[24:27], 0xb0              ; f428040c fa0000b0
	s_mov_b64 s[14:15], exec                                    ; be8e047e
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v3, s16, v4                                   ; 10060810
	v_add_f32_e64 v8, s19, 0x41000000                           ; d5030008 0001fe13 41000000
	v_mac_f32_e32 v8, s18, v6                                   ; 3e100c12
	v_mac_f32_e32 v8, s17, v7                                   ; 3e100e11
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e64 v8, -v3                                   ; d411007e 40020708
BB23:
	s_mov_b64 s[16:17], -1                                      ; be9004c1
	s_andn2_b64 exec, s[14:15], exec                            ; 8afe7e0e
	s_cbranch_execz BB40                                        ; bf880030
BB26:
	s_buffer_load_dwordx4 s[16:19], s[24:27], 0xc0              ; f428040c fa0000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v3, s16, v4                                   ; 10060810
	v_add_f32_e64 v8, s19, 0x41000000                           ; d5030008 0001fe13 41000000
	v_mac_f32_e32 v8, s18, v6                                   ; 3e100c12
	v_mac_f32_e32 v8, s17, v7                                   ; 3e100e11
	s_mov_b64 s[16:17], exec                                    ; be90047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e64 v8, -v3                                   ; d411007e 40020708
BB27:
	s_mov_b64 s[18:19], -1                                      ; be9204c1
	s_andn2_b64 exec, s[16:17], exec                            ; 8afe7e10
	s_cbranch_execz BB38                                        ; bf88001e
BB30:
	s_buffer_load_dwordx4 s[20:23], s[24:27], 0xd0              ; f428050c fa0000d0
	s_mov_b64 s[18:19], exec                                    ; be92047e
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v3, s20, v4                                   ; 10060814
	v_add_f32_e64 v8, s23, 0x41000000                           ; d5030008 0001fe17 41000000
	v_mac_f32_e32 v8, s22, v6                                   ; 3e100c16
	v_mac_f32_e32 v8, s21, v7                                   ; 3e100e15
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e64 v8, -v3                                   ; d411007e 40020708
BB31:
	s_mov_b64 s[20:21], -1                                      ; be9404c1
	s_andn2_b64 exec, s[18:19], exec                            ; 8afe7e12
	s_cbranch_execz BB36                                        ; bf88000c
BB34:
	s_buffer_load_dwordx4 s[20:23], s[24:27], 0xe0              ; f428050c fa0000e0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v3, s20, v4                                   ; 10060814
	v_add_f32_e64 v8, s23, 0x41000000                           ; d5030008 0001fe17 41000000
	v_mac_f32_e32 v8, s22, v6                                   ; 3e100c16
	v_mac_f32_e32 v8, s21, v7                                   ; 3e100e15
	v_cmp_lt_f32_e64 s[20:21], v8, -v3                          ; d4010014 40020708
	s_orn2_b64 s[20:21], s[20:21], exec                         ; 8b947e14
BB36:
	s_mov_b64 exec, s[18:19]                                    ; befe0412
	s_orn2_b64 s[18:19], s[20:21], exec                         ; 8b927e14
BB38:
	s_mov_b64 exec, s[16:17]                                    ; befe0410
	s_orn2_b64 s[16:17], s[18:19], exec                         ; 8b907e12
BB40:
	s_mov_b64 exec, s[14:15]                                    ; befe040e
	s_orn2_b64 s[14:15], s[16:17], exec                         ; 8b8e7e10
BB42:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_orn2_b64 s[12:13], s[14:15], exec                         ; 8b8c7e0e
BB44:
	s_mov_b64 exec, s[10:11]                                    ; befe040a
	s_and_b64 exec, s[12:13], exec                              ; 87fe7e0c
BB45:
	v_lshrrev_b64 v[2:3], 0, 0                                  ; d7000002 00010080
	v_lshrrev_b64 v[8:9], 0, 0                                  ; d7000008 00010080
	v_lshrrev_b64 v[10:11], 0, 0                                ; d700000a 00010080
	s_andn2_b64 exec, s[10:11], exec                            ; 8afe7e0a
	s_cbranch_execz BB58                                        ; bf88017a
BB48:
	s_buffer_load_dword s5, s[24:27], 0xf4                      ; f420014c fa0000f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cmp_lt_f32_e64 s[12:13], 0, s5                            ; d401000c 00000a80
	s_and_b64 s[12:13], s[12:13], exec                          ; 878c7e0c
	s_cbranch_scc0 BB50                                         ; bf84016d
BB49:
	s_waitcnt_vscnt null, 0x0                                   ; bbfd0000
	ds_read2_b32 v[8:9], v2 offset0:31 offset1:32               ; d8dc201f 08000002
	ds_read_b32 v3, v2 offset:132                               ; d8d80084 03000002
	s_clause 0x2                                                ; bfa10002
	s_buffer_load_dwordx16 s[32:47], s[24:27], 0x40             ; f430080c fa000040
	s_buffer_load_dwordx16 s[48:63], s[24:27], null             ; f4300c0c fa000000
	s_buffer_load_dwordx4 s[12:15], s[24:27], 0xf8              ; f428030c fa0000f8
	ds_read2_b32 v[10:11], v2 offset0:13 offset1:14             ; d8dc0e0d 0a000002
	ds_read_b32 v7, v2 offset:60                                ; d8d8003c 07000002
	s_waitcnt lgkmcnt(3)                                        ; bf8cc37f
	v_add_f32_e64 v12, v8, v4 div:2                             ; d503000c 18020908
	v_add_f32_e64 v13, v9, v5 div:2                             ; d503000d 18020b09
	v_sub_f32_e32 v14, v8, v4                                   ; 081c0908
	v_sub_f32_e32 v15, v9, v5                                   ; 081e0b09
	s_waitcnt lgkmcnt(2)                                        ; bf8cc27f
	v_add_f32_e64 v16, v3, v6 div:2                             ; d5030010 18020d03
	v_sub_f32_e32 v17, v3, v6                                   ; 08220d03
	v_mul_f32_e32 v15, v15, v15                                 ; 101e1f0f
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v18, s40, v16, s44                                ; d5410012 00b22028
	v_mad_f32 v19, s41, v16, s45                                ; d5410013 00b62029
	v_mad_f32 v20, s42, v16, s46                                ; d5410014 00ba202a
	v_mad_f32 v16, s43, v16, s47                                ; d5410010 00be202b
	v_rcp_f32_e32 v21, s14                                      ; 7e2a540e
	v_add_f32_e64 v24, v4, v10 div:2                            ; d5030018 18021504
	v_mac_f32_e32 v15, v17, v17                                 ; 3e1e2311
	v_add_f32_e64 v25, v5, v11 div:2                            ; d5030019 18021705
	v_mac_f32_e32 v18, s36, v13                                 ; 3e241a24
	v_mac_f32_e32 v19, s37, v13                                 ; 3e261a25
	v_mac_f32_e32 v20, s38, v13                                 ; 3e281a26
	v_add_f32_e64 v26, v6, v7 div:2                             ; d503001a 18020f06
	v_sub_f32_e32 v6, v6, v7                                    ; 080c0f06
	v_mac_f32_e32 v16, s39, v13                                 ; 3e201a27
	v_sub_f32_e32 v4, v4, v10                                   ; 08081504
	v_sub_f32_e32 v5, v5, v11                                   ; 080a1705
	v_mac_f32_e32 v15, v14, v14                                 ; 3e1e1d0e
	v_mac_f32_e32 v18, s32, v12                                 ; 3e241820
	v_mac_f32_e32 v19, s33, v12                                 ; 3e261821
	v_mac_f32_e32 v20, s34, v12                                 ; 3e281822
	v_mac_f32_e32 v16, s35, v12                                 ; 3e201823
	v_mul_f32_e32 v5, v5, v5                                    ; 100a0b05
	v_sqrt_f32_e64 v15, v15 div:2                               ; d5b3000f 1800010f
	v_mul_f32_e32 v23, s60, v16                                 ; 102e203c
	v_mul_f32_e32 v27, s61, v16                                 ; 1036203d
	v_mac_f32_e32 v5, v6, v6                                    ; 3e0a0d06
	v_mac_f32_e32 v23, s56, v20                                 ; 3e2e2838
	v_mac_f32_e32 v27, s57, v20                                 ; 3e362839
	v_mac_f32_e32 v5, v4, v4                                    ; 3e0a0904
	v_mul_f32_e32 v4, s62, v16                                  ; 1008203e
	v_mul_f32_e32 v16, s63, v16                                 ; 1020203f
	v_sub_f32_e32 v22, v18, v15                                 ; 082c1f12
	v_add_f32_e32 v18, v18, v15                                 ; 06241f12
	v_mac_f32_e32 v23, s52, v19                                 ; 3e2e2634
	v_mac_f32_e32 v27, s53, v19                                 ; 3e362635
	v_sqrt_f32_e64 v5, v5 div:2                                 ; d5b30005 18000105
	v_mac_f32_e32 v4, s58, v20                                  ; 3e08283a
	v_mac_f32_e32 v16, s59, v20                                 ; 3e20283b
	v_mad_f32 v6, s48, v22, v23                                 ; d5410006 045e2c30
	v_mac_f32_e32 v23, s48, v18                                 ; 3e2e2430
	v_mad_f32 v12, s49, v22, v27                                ; d541000c 046e2c31
	v_mac_f32_e32 v27, s49, v18                                 ; 3e362431
	v_mac_f32_e32 v4, s54, v19                                  ; 3e082636
	v_mac_f32_e32 v16, s55, v19                                 ; 3e202637
	v_mad_f32 v13, s50, v22, v4                                 ; d541000d 04122c32
	v_mac_f32_e32 v4, s50, v18                                  ; 3e082432
	v_mad_f32 v22, s51, v22, v16                                ; d5410016 04422c33
	v_mac_f32_e32 v16, s51, v18                                 ; 3e202433
	v_rcp_f32_e32 v14, v22                                      ; 7e1c5516
	v_rcp_f32_e32 v15, v16                                      ; 7e1e5510
	v_mul_f32_e32 v22, v22, v14                                 ; 102c1d16
	v_mul_f32_e32 v12, v12, v14                                 ; 10181d0c
	v_mul_f32_e32 v13, v13, v14                                 ; 101a1d0d
	v_mul_f32_e32 v6, v6, v14                                   ; 100c1d06
	v_mul_f32_e32 v23, v23, v15                                 ; 102e1f17
	v_mul_f32_e32 v27, v27, v15                                 ; 10361f1b
	v_mad_f32 v17, s41, v26, s45                                ; d5410011 00b63429
	v_mad_f32 v18, s42, v26, s46                                ; d5410012 00ba342a
	v_mad_f32 v16, v16, -v15, v22                               ; d5410010 445a1f10
	v_mul_f32_e32 v12, s13, v12                                 ; 1018180d
	v_mad_f32 v4, v4, -v15, v13                                 ; d5410004 44361f04
	v_mul_f32_e32 v6, s12, v6                                   ; 100c0c0c
	v_mac_f32_e32 v17, s37, v25                                 ; 3e223225
	v_mac_f32_e32 v18, s38, v25                                 ; 3e243226
	v_mad_f32 v27, s13, -v27, v12                               ; d541001b 4432360d
	v_mul_f32_e32 v4, v4, v4                                    ; 10080904
	v_mad_f32 v23, s12, -v23, v6                                ; d5410017 441a2e0c
	v_mac_f32_e32 v17, s33, v24                                 ; 3e223021
	v_mac_f32_e32 v18, s34, v24                                 ; 3e243022
	v_mac_f32_e32 v4, v16, v16                                  ; 3e082110
	v_mad_f32 v16, s40, v26, s44                                ; d5410010 00b23428
	v_mad_f32 v26, s43, v26, s47                                ; d541001a 00be342b
	v_mac_f32_e32 v4, v27, v27                                  ; 3e08371b
	v_mac_f32_e32 v16, s36, v25                                 ; 3e203224
	v_mac_f32_e32 v26, s39, v25                                 ; 3e343227
	v_mac_f32_e32 v4, v23, v23                                  ; 3e082f17
	v_mac_f32_e32 v16, s32, v24                                 ; 3e203020
	v_mac_f32_e32 v26, s35, v24                                 ; 3e343023
	ds_read2_b32 v[12:13], v2 offset0:22 offset1:23             ; d8dc1716 0c000002
	ds_read_b32 v2, v2 offset:96                                ; d8d80060 02000002
	v_sqrt_f32_e32 v4, v4                                       ; 7e086704
	v_sub_f32_e32 v19, v16, v5                                  ; 08260b10
	v_mul_f32_e32 v20, s60, v26                                 ; 1028343c
	v_mul_f32_e32 v23, s62, v26                                 ; 102e343e
	v_mul_f32_e32 v22, s61, v26                                 ; 102c343d
	v_mul_f32_e32 v26, s63, v26                                 ; 1034343f
	v_add_f32_e32 v16, v16, v5                                  ; 06200b10
	v_mac_f32_e32 v20, s56, v18                                 ; 3e282438
	v_mac_f32_e32 v23, s58, v18                                 ; 3e2e243a
	v_mac_f32_e32 v22, s57, v18                                 ; 3e2c2439
	v_mac_f32_e32 v26, s59, v18                                 ; 3e34243b
	v_mul_f32_e32 v4, v4, v21                                   ; 10082b04
	v_mac_f32_e32 v20, s52, v17                                 ; 3e282234
	v_mac_f32_e32 v23, s54, v17                                 ; 3e2e2236
	v_mac_f32_e32 v22, s53, v17                                 ; 3e2c2235
	v_mac_f32_e32 v26, s55, v17                                 ; 3e342237
	v_mul_f32_e32 v4, s5, v4                                    ; 10080805
	v_mad_f32 v24, s48, v19, v20                                ; d5410018 04522630
	v_mac_f32_e32 v20, s48, v16                                 ; 3e282030
	v_mad_f32 v27, s50, v19, v23                                ; d541001b 045e2632
	v_mac_f32_e32 v23, s50, v16                                 ; 3e2e2032
	v_mad_f32 v25, s49, v19, v22                                ; d5410019 045a2631
	v_mac_f32_e32 v22, s49, v16                                 ; 3e2c2031
	v_mad_f32 v19, s51, v19, v26                                ; d5410013 046a2633
	v_mac_f32_e32 v26, s51, v16                                 ; 3e342033
	v_rcp_f32_e32 v5, v19                                       ; 7e0a5513
	v_rcp_f32_e32 v6, v26                                       ; 7e0c551a
	v_mul_f32_e32 v19, v19, v5                                  ; 10260b13
	v_mul_f32_e32 v27, v27, v5                                  ; 10360b1b
	v_mul_f32_e32 v24, v24, v5                                  ; 10300b18
	v_mul_f32_e32 v25, v25, v5                                  ; 10320b19
	v_mul_f32_e32 v20, v20, v6                                  ; 10280d14
	s_waitcnt lgkmcnt(1)                                        ; bf8cc17f
	v_add_f32_e64 v14, v10, v12 div:2                           ; d503000e 1802190a
	v_mul_f32_e32 v22, v22, v6                                  ; 102c0d16
	v_add_f32_e64 v15, v11, v13 div:2                           ; d503000f 18021b0b
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e64 v16, v7, v2 div:2                             ; d5030010 18020507
	v_mad_f32 v26, v26, -v6, v19                                ; d541001a 444e0d1a
	v_mad_f32 v23, v23, -v6, v27                                ; d5410017 446e0d17
	v_sub_f32_e32 v10, v10, v12                                 ; 0814190a
	v_sub_f32_e32 v11, v11, v13                                 ; 08161b0b
	v_mul_f32_e32 v24, s12, v24                                 ; 1030300c
	v_mul_f32_e32 v25, s13, v25                                 ; 1032320d
	v_sub_f32_e32 v7, v7, v2                                    ; 080e0507
	v_mad_f32 v17, s40, v16, s44                                ; d5410011 00b22028
	v_mad_f32 v18, s41, v16, s45                                ; d5410012 00b62029
	v_mad_f32 v19, s42, v16, s46                                ; d5410013 00ba202a
	v_mul_f32_e32 v23, v23, v23                                 ; 102e2f17
	v_mad_f32 v16, s43, v16, s47                                ; d5410010 00be202b
	v_mul_f32_e32 v11, v11, v11                                 ; 1016170b
	v_mad_f32 v20, s12, -v20, v24                               ; d5410014 4462280c
	v_mad_f32 v22, s13, -v22, v25                               ; d5410016 44662c0d
	v_mac_f32_e32 v17, s36, v15                                 ; 3e221e24
	v_mac_f32_e32 v18, s37, v15                                 ; 3e241e25
	v_mac_f32_e32 v19, s38, v15                                 ; 3e261e26
	v_mac_f32_e32 v23, v26, v26                                 ; 3e2e351a
	v_mac_f32_e32 v16, s39, v15                                 ; 3e201e27
	v_mac_f32_e32 v11, v7, v7                                   ; 3e160f07
	v_mac_f32_e32 v17, s32, v14                                 ; 3e221c20
	v_mac_f32_e32 v18, s33, v14                                 ; 3e241c21
	v_mac_f32_e32 v19, s34, v14                                 ; 3e261c22
	v_mac_f32_e32 v23, v22, v22                                 ; 3e2e2d16
	v_mac_f32_e32 v16, s35, v14                                 ; 3e201c23
	v_mac_f32_e32 v11, v10, v10                                 ; 3e16150a
	v_mac_f32_e32 v23, v20, v20                                 ; 3e2e2914
	v_mul_f32_e32 v22, s60, v16                                 ; 102c203c
	v_mul_f32_e32 v25, s62, v16                                 ; 1032203e
	v_mul_f32_e32 v24, s61, v16                                 ; 1030203d
	v_mul_f32_e32 v16, s63, v16                                 ; 1020203f
	v_sqrt_f32_e64 v11, v11 div:2                               ; d5b3000b 1800010b
	v_sqrt_f32_e32 v23, v23                                     ; 7e2e6717
	v_mac_f32_e32 v22, s56, v19                                 ; 3e2c2638
	v_mac_f32_e32 v25, s58, v19                                 ; 3e32263a
	v_mac_f32_e32 v24, s57, v19                                 ; 3e302639
	v_mac_f32_e32 v16, s59, v19                                 ; 3e20263b
	v_sub_f32_e32 v20, v17, v11                                 ; 08281711
	v_add_f32_e32 v17, v17, v11                                 ; 06221711
	v_mac_f32_e32 v22, s52, v18                                 ; 3e2c2434
	v_mac_f32_e32 v25, s54, v18                                 ; 3e322436
	v_mac_f32_e32 v24, s53, v18                                 ; 3e302435
	v_mac_f32_e32 v16, s55, v18                                 ; 3e202437
	v_mul_f32_e32 v23, v23, v21                                 ; 102e2b17
	v_mad_f32 v26, s48, v20, v22                                ; d541001a 045a2830
	v_mac_f32_e32 v22, s48, v17                                 ; 3e2c2230
	v_mad_f32 v5, s50, v20, v25                                 ; d5410005 04662832
	v_mac_f32_e32 v25, s50, v17                                 ; 3e322232
	v_mad_f32 v27, s49, v20, v24                                ; d541001b 04622831
	v_mac_f32_e32 v24, s49, v17                                 ; 3e302231
	v_mad_f32 v20, s51, v20, v16                                ; d5410014 04422833
	v_mac_f32_e32 v16, s51, v17                                 ; 3e202233
	v_mul_f32_e32 v23, s5, v23                                  ; 102e2e05
	v_rcp_f32_e32 v6, v20                                       ; 7e0c5514
	v_rcp_f32_e32 v7, v16                                       ; 7e0e5510
	v_mul_f32_e32 v26, v26, v6                                  ; 10340d1a
	v_mul_f32_e32 v5, v5, v6                                    ; 100a0d05
	v_mul_f32_e32 v20, v20, v6                                  ; 10280d14
	v_mul_f32_e32 v27, v27, v6                                  ; 10360d1b
	v_mul_f32_e32 v22, v22, v7                                  ; 102c0f16
	v_mul_f32_e32 v24, v24, v7                                  ; 10300f18
	v_add_f32_e64 v10, v12, v8 div:2                            ; d503000a 1802110c
	v_add_f32_e64 v11, v13, v9 div:2                            ; d503000b 1802130d
	v_add_f32_e64 v14, v2, v3 div:2                             ; d503000e 18020702
	v_mul_f32_e32 v26, s12, v26                                 ; 1034340c
	v_mad_f32 v25, v25, -v7, v5                                 ; d5410019 44160f19
	v_sub_f32_e32 v12, v12, v8                                  ; 0818110c
	v_mad_f32 v16, v16, -v7, v20                                ; d5410010 44520f10
	v_sub_f32_e32 v13, v13, v9                                  ; 081a130d
	v_mul_f32_e32 v27, s13, v27                                 ; 1036360d
	v_sub_f32_e32 v2, v2, v3                                    ; 08040702
	v_mad_f32 v15, s40, v14, s44                                ; d541000f 00b21c28
	v_mad_f32 v17, s42, v14, s46                                ; d5410011 00ba1c2a
	v_mad_f32 v22, s12, -v22, v26                               ; d5410016 446a2c0c
	v_mul_f32_e32 v25, v25, v25                                 ; 10323319
	v_mul_f32_e32 v13, v13, v13                                 ; 101a1b0d
	v_mad_f32 v24, s13, -v24, v27                               ; d5410018 446e300d
	v_mac_f32_e32 v15, s36, v11                                 ; 3e1e1624
	v_mac_f32_e32 v17, s38, v11                                 ; 3e221626
	v_mac_f32_e32 v25, v16, v16                                 ; 3e322110
	v_mad_f32 v16, s41, v14, s45                                ; d5410010 00b61c29
	v_mad_f32 v14, s43, v14, s47                                ; d541000e 00be1c2b
	v_mac_f32_e32 v13, v2, v2                                   ; 3e1a0502
	v_mac_f32_e32 v15, s32, v10                                 ; 3e1e1420
	v_mac_f32_e32 v17, s34, v10                                 ; 3e221422
	v_mac_f32_e32 v25, v24, v24                                 ; 3e323118
	v_mac_f32_e32 v16, s37, v11                                 ; 3e201625
	v_mac_f32_e32 v14, s39, v11                                 ; 3e1c1627
	v_mac_f32_e32 v13, v12, v12                                 ; 3e1a190c
	v_mac_f32_e32 v25, v22, v22                                 ; 3e322d16
	v_mac_f32_e32 v16, s33, v10                                 ; 3e201421
	v_mac_f32_e32 v14, s35, v10                                 ; 3e1c1423
	v_sqrt_f32_e64 v13, v13 div:2                               ; d5b3000d 1800010d
	v_sqrt_f32_e32 v25, v25                                     ; 7e326719
	v_mul_f32_e32 v20, s61, v14                                 ; 10281c3d
	v_mul_f32_e32 v19, s60, v14                                 ; 10261c3c
	v_mul_f32_e32 v22, s62, v14                                 ; 102c1c3e
	v_mul_f32_e32 v14, s63, v14                                 ; 101c1c3f
	v_mac_f32_e32 v20, s57, v17                                 ; 3e282239
	v_sub_f32_e32 v18, v15, v13                                 ; 08241b0f
	v_add_f32_e32 v15, v15, v13                                 ; 061e1b0f
	v_mac_f32_e32 v19, s56, v17                                 ; 3e262238
	v_mac_f32_e32 v22, s58, v17                                 ; 3e2c223a
	v_mac_f32_e32 v14, s59, v17                                 ; 3e1c223b
	v_mul_f32_e32 v25, v25, v21                                 ; 10322b19
	v_mac_f32_e32 v20, s53, v16                                 ; 3e282035
	v_mac_f32_e32 v19, s52, v16                                 ; 3e262034
	v_mac_f32_e32 v22, s54, v16                                 ; 3e2c2036
	v_mac_f32_e32 v14, s55, v16                                 ; 3e1c2037
	v_mul_f32_e32 v25, s5, v25                                  ; 10323205
	v_mad_f32 v26, s49, v18, v20                                ; d541001a 04522431
	v_mac_f32_e32 v20, s49, v15                                 ; 3e281e31
	v_mad_f32 v24, s48, v18, v19                                ; d5410018 044e2430
	v_mac_f32_e32 v19, s48, v15                                 ; 3e261e30
	v_mad_f32 v27, s50, v18, v22                                ; d541001b 045a2432
	v_mac_f32_e32 v22, s50, v15                                 ; 3e2c1e32
	v_mad_f32 v18, s51, v18, v14                                ; d5410012 043a2433
	v_mac_f32_e32 v14, s51, v15                                 ; 3e1c1e33
	v_rcp_f32_e32 v2, v18                                       ; 7e045512
	v_rcp_f32_e32 v3, v14                                       ; 7e06550e
	v_mul_f32_e32 v18, v18, v2                                  ; 10240512
	v_mul_f32_e32 v26, v26, v2                                  ; 1034051a
	v_mul_f32_e32 v24, v24, v2                                  ; 10300518
	v_mul_f32_e32 v27, v27, v2                                  ; 1036051b
	v_mul_f32_e32 v19, v19, v3                                  ; 10260713
	v_mul_f32_e32 v20, v20, v3                                  ; 10280714
	v_mad_f32 v14, v14, -v3, v18                                ; d541000e 444a070e
	v_mul_f32_e32 v26, s13, v26                                 ; 1034340d
	v_mul_f32_e32 v24, s12, v24                                 ; 1030300c
	v_mad_f32 v22, v22, -v3, v27                                ; d5410016 446e0716
	v_mad_f32 v20, s13, -v20, v26                               ; d5410014 446a280d
	v_mad_f32 v19, s12, -v19, v24                               ; d5410013 4462260c
	v_mul_f32_e32 v22, v22, v22                                 ; 102c2d16
	v_mac_f32_e32 v22, v14, v14                                 ; 3e2c1d0e
	v_mac_f32_e32 v22, v20, v20                                 ; 3e2c2914
	v_mac_f32_e32 v22, v19, v19                                 ; 3e2c2713
	v_sqrt_f32_e32 v22, v22                                     ; 7e2c6716
	v_mul_f32_e32 v22, v22, v21                                 ; 102c2b16
	v_mul_f32_e32 v22, s5, v22                                  ; 102c2c05
	s_mov_b32 s5, 0x42800000                                    ; be8503ff 42800000
	v_med3_f32 v10, s5, 1.0, v25                                ; d557000a 0465e405
	v_med3_f32 v9, s5, 1.0, v23                                 ; d5570009 045de405
	v_med3_f32 v8, s5, 1.0, v4                                  ; d5570008 0411e405
	v_med3_f32 v11, s5, 1.0, v22                                ; d557000b 0459e405
	v_add_f32_e64 v3, v10, v9 div:2                             ; d5030003 1802130a
	v_add_f32_e64 v2, v8, v11 div:2                             ; d5030002 18021708
	s_branch BB58                                               ; bf820006
BB50:
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
	v_mov_b32_e32 v3, 1.0                                       ; 7e0602f2
	v_mov_b32_e32 v8, 1.0                                       ; 7e1002f2
	v_mov_b32_e32 v9, 1.0                                       ; 7e1202f2
	v_mov_b32_e32 v10, 1.0                                      ; 7e1402f2
	v_mov_b32_e32 v11, 1.0                                      ; 7e1602f2
BB58:
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	s_movk_i32 s5, 0x6c                                         ; b005006c
	v_mul_u32_u24_sdwa v4, s5, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 160802f9 00860605
	v_mad_u32_u24 v0, 36, v0, v4                                ; d5430000 041200a4
	s_waitcnt_vscnt null, 0x0                                   ; bbfd0000
	ds_read2_b32 v[4:5], v0 offset0:8 offset1:9                 ; d8dc0908 04000000
	ds_read2_b32 v[6:7], v0 offset0:10 offset1:11               ; d8dc0b0a 06000000
	ds_read2_b32 v[12:13], v0 offset0:4 offset1:5               ; d8dc0504 0c000000
	ds_read2_b32 v[14:15], v0 offset0:6 offset1:7               ; d8dc0706 0e000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_b64 exec, vcc, exec                                   ; 87fe7e6a
BB59:
	v_min3_f32 v0, v8, v9, v10                                  ; d5510000 042a1308
	v_max3_f32 v16, v8, v9, v10                                 ; d5540010 042a1308
	v_min_f32_e32 v0, v0, v11                                   ; 1e001700
	v_max3_f32 v16, v16, v11, v2                                ; d5540010 040a1710
	v_cmp_lt_f32_e64 s[10:11], 0, v0                            ; d401000a 00020080
	v_max_f32_e32 v16, v16, v3                                  ; 20200710
	v_cmp_ge_f32_e64 s[12:13], 1.0, v16                         ; d406000c 000220f2
	s_nand_b64 s[12:13], s[12:13], s[10:11]                     ; 8c8c0a0c
	s_not_b64 s[10:11], s[10:11]                                ; be8a080a
	s_andn2_b64 s[10:11], exec, s[10:11]                        ; 8a8a0a7e
	s_cselect_b64 s[10:11], -1, 0                               ; 858a80c1
	s_not_b64 s[10:11], s[10:11]                                ; be8a080a
	s_mov_b32 s5, src_scc                                       ; be8503fd
	s_and_b64 s[10:11], s[12:13], exec                          ; 878a7e0c
	s_cselect_b64 s[10:11], -1, 0                               ; 858a80c1
	s_not_b64 s[10:11], s[10:11]                                ; be8a080a
	s_lshl_b32 s10, src_scc, 1                                  ; 8f0a81fd
	s_or_b32 s5, s5, s10                                        ; 88050a05
	s_mov_b64 s[10:11], 15                                      ; be8a048f
	s_and_saveexec_b64 s[10:11], s[10:11]                       ; be8a240a
BB60:
	s_ff1_i32_b64 s12, exec                                     ; be8c147e
	s_lshl_b64 s[12:13], 1, s12                                 ; 8f8c0c81
	s_and_saveexec_b64 s[12:13], s[12:13]                       ; be8c240c
	s_cbranch_execz BB76                                        ; bf880004
BB61:
	v_mov_b32_e32 v0, s5                                        ; 7e000205
	v_mov_b32_e32 v16, 0                                        ; 7e200280
	ds_and_b32 v16, v0                                          ; d8240000 00000010
BB76:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_b64 exec, s[6:7], exec                                ; 87fe7e06
BB77:
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	ds_read_b32 v0, v0                                          ; d8d80000 00000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_readfirstlane_b32 s5, v0                                  ; 7e0a0500
BB82:
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	s_and_b64 exec, vcc, exec                                   ; 87fe7e6a
BB83:
	s_load_dwordx4 s[12:15], s[0:1], 0x50                       ; f4080300 fa000050
	v_mul_u32_u24_sdwa v0, 24, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 160002f9 00860698
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[8:11], v0, s[12:15], s4 offen glc    ; e0785000 04030800
	buffer_store_dwordx2 v[2:3], v0, s[12:15], s4 offen offset:16 glc ; e0745010 04030200
BB88:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	s_cmp_lg_i32 s5, 1                                          ; bf018105
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v8, 0, v12, vcc                           ; 02101880
	v_cndmask_b32_e32 v9, 0, v13, vcc                           ; 02121a80
	v_cndmask_b32_e32 v10, 0, v14, vcc                          ; 02141c80
	v_cndmask_b32_e32 v11, 0, v5, vcc                           ; 02160a80
	v_cndmask_b32_e32 v16, 0, v6, vcc                           ; 02200c80
	v_cndmask_b32_e32 v17, 0, v7, vcc                           ; 02220e80
	v_cndmask_b32_e32 v18, 0, v15, vcc                          ; 02241e80
	v_cndmask_b32_e32 v19, 0, v4, vcc                           ; 02260880
BB93:
	s_load_dwordx4 s[8:11], s[0:1], 0x60                        ; f4080200 fa000060
	s_mov_b64 exec, -1                                          ; befe04c1
	v_readfirstlane_b32 s0, v1                                  ; 7e000501
	s_bfe_u32 s0, s0, 0x80000                                   ; 9380ff00 00080000
	s_lshl_b32 s0, s0, 2                                        ; 8f008200
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
	s_and_b64 exec, s[0:1], s[4:5]                              ; 87fe0400
	s_cbranch_execz BB99                                        ; bf880007
BB94:
	v_lshlrev_b32_e32 v0, 4, v0                                 ; 34000084
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_waitcnt_vscnt null, 0x0                                   ; bbfd0000
	buffer_store_dwordx4 v[8:11], v0, s[8:11], s2 offen glc     ; e0785000 02020800
	buffer_store_dwordx4 v[16:19], v0, s[8:11], s2 offen offset:3072 glc ; e0785c00 02021000
BB99:
	s_endpgm                                                    ; bf810000
