# Tessellation Control Shader
BB0:
	s_lshl_b32 s5, s3, 8                                        ; 8f058803
	s_bfe_u64 s[6:7], -1, s5                                    ; 948605c1
	s_and_saveexec_b64 s[8:9], s[6:7]                           ; be882406
	s_cbranch_execz BB72                                        ; bf88016c
BB1:
	s_barrier                                                   ; bf8a0000
	s_and_saveexec_b64 s[6:7], s[6:7]                           ; be862406
	s_cbranch_execz BB61                                        ; bf880142
BB2:
	v_readfirstlane_b32 s5, v1                                  ; 7e0a0501
	s_bfe_u32 s10, s5, 0x50008                                  ; 938aff05 00050008
	s_bfe_u32 s5, s5, 0x80000                                   ; 9385ff05 00080000
	s_mul_i32 s5, s5, 3                                         ; 93058305
	s_add_u32 s5, s5, s10                                       ; 80050a05
	s_mov_b64 s[10:11], 1                                       ; be8a0481
	s_cmp_lt_u32 s5, 64                                         ; bf0ac005
	s_cselect_b64 s[12:13], -1, 0                               ; 858c80c1
	s_and_b64 s[12:13], s[12:13], s[10:11]                      ; 878c0a0c
	s_and_saveexec_b64 s[12:13], s[12:13]                       ; be8c240c
	s_cbranch_execz BB8                                         ; bf880004
BB3:
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_mov_b32_e32 v2, 3                                         ; 7e040283
	ds_write_b32 v0, v2                                         ; d8340000 00000200
BB8:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_bfe_u32 s17, s17, 0x60011                                 ; 9391ff11 00060011
	v_bfe_u32 v0, v1, 8, 5                                      ; d5480000 02151101
	v_bfe_u32 v2, v1, 0, 8                                      ; d5480002 02210101
	s_cselect_b32 s5, 4, 0                                      ; 85058084
	s_lshl4_add_u32 s17, s17, s5                                ; 98910511
	v_cmp_gt_i32_e32 vcc, 3, v0                                 ; 7d080083
	v_cmp_gt_i32_e64 s[18:19], 1, v0                            ; d4840012 00020081
	v_cmp_gt_i32_e64 s[20:21], 2, v0                            ; d4840014 00020082
	s_mul_i32 s15, 3, s17                                       ; 930f1183
	v_mul_u32_u24_e32 v3, s15, v2                               ; 1606040f
	v_add_nc_u32_e32 v12, s17, v3                               ; 4a180611
	v_lshl_add_u32 v13, s17, 1, v3                              ; d746000d 040d0211
	v_mad_u32_u24 v4, s17, v0, v3                               ; d5430004 040e0011
	ds_read2_b32 v[6:7], v4 offset0:4 offset1:5                 ; d8dc0504 06000004
	ds_read2_b32 v[4:5], v4 offset0:6 offset1:7                 ; d8dc0706 04000004
	ds_read2_b32 v[8:9], v3 offset0:4 offset1:5                 ; d8dc0504 08000003
	ds_read2_b32 v[10:11], v3 offset0:6 offset1:7               ; d8dc0706 0a000003
	ds_read2_b32 v[14:15], v12 offset0:4 offset1:5              ; d8dc0504 0e00000c
	ds_read2_b32 v[16:17], v12 offset0:6 offset1:7              ; d8dc0706 1000000c
	ds_read2_b32 v[18:19], v13 offset0:4 offset1:5              ; d8dc0504 1200000d
	ds_read2_b32 v[20:21], v13 offset0:6 offset1:7              ; d8dc0706 1400000d
	ds_read2_b32 v[22:23], v3 offset0:20 offset1:21             ; d8dc1514 16000003
	ds_read_b32 v3, v3 offset:88                                ; d8d80058 03000003
	ds_read2_b32 v[24:25], v12 offset0:20 offset1:21            ; d8dc1514 1800000c
	ds_read_b32 v12, v12 offset:88                              ; d8d80058 0c00000c
	ds_read2_b32 v[26:27], v13 offset0:20 offset1:21            ; d8dc1514 1a00000d
	ds_read_b32 v13, v13 offset:88                              ; d8d80058 0d00000d
	s_waitcnt lgkmcnt(11)                                       ; bf8ccb7f
	v_cndmask_b32_e64 v28, v9, v8, s[18:19]                     ; d501001c 004a1109
	s_waitcnt lgkmcnt(10)                                       ; bf8cca7f
	v_cndmask_b32_e32 v11, v11, v10, vcc                        ; 0216150b
	s_round_mode 0x0                                            ; bfa40000
	s_denorm_mode 12                                            ; bfa5000c
	s_waitcnt lgkmcnt(9)                                        ; bf8cc97f
	v_sub_f32_e32 v37, v9, v15                                  ; 084a1f09
	v_sub_f32_e32 v32, v15, v9                                  ; 0840130f
	v_sub_f32_e32 v31, v14, v8                                  ; 083e110e
	v_sub_f32_e32 v36, v8, v14                                  ; 08481d08
	v_cndmask_b32_e64 v29, v15, v14, s[18:19]                   ; d501001d 004a1d0f
	s_waitcnt lgkmcnt(8)                                        ; bf8cc87f
	v_sub_f32_e32 v38, v10, v16                                 ; 084c210a
	s_movk_i32 s15, 0x8000                                      ; b00f8000
	s_load_dword s14, s[14:15], null                            ; f4000387 fa000000
	s_movk_i32 s15, 0x8000                                      ; b00f8000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_load_dwordx4 s[24:27], s[14:15], null                     ; f4080607 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s16, s[24:27], 0x84                     ; f420040c fa000084
	v_cndmask_b32_e32 v17, v17, v16, vcc                        ; 02222111
	v_sub_f32_e32 v34, v16, v10                                 ; 08441510
	v_sub_f32_e32 v40, v18, v14                                 ; 08501d12
	v_sub_f32_e32 v41, v19, v15                                 ; 08521f13
	v_cndmask_b32_e64 v33, v19, v18, s[18:19]                   ; d5010021 004a2513
	v_sub_f32_e32 v42, v20, v16                                 ; 08542114
	v_cndmask_b32_e32 v21, v21, v20, vcc                        ; 022a2915
	v_cndmask_b32_e64 v11, v11, v28, s[20:21]                   ; d501000b 0052390b
	v_sub_f32_e32 v14, v14, v18                                 ; 081c250e
	v_sub_f32_e32 v16, v16, v20                                 ; 08202910
	v_sub_f32_e32 v45, v8, v18                                  ; 085a2508
	v_cndmask_b32_e64 v46, v3, v23, s[20:21]                    ; d501002e 00522f03
	v_cndmask_b32_e64 v17, v17, v29, s[20:21]                   ; d5010011 00523b11
	v_mul_f32_e32 v34, v34, v3                                  ; 10440722
	v_sub_f32_e32 v15, v15, v19                                 ; 081e270f
	v_sub_f32_e32 v47, v9, v19                                  ; 085e2709
	v_sub_f32_e32 v48, v10, v20                                 ; 0860290a
	v_cndmask_b32_e64 v49, v12, v25, s[20:21]                   ; d5010031 0052330c
	v_cndmask_b32_e64 v21, v21, v33, s[20:21]                   ; d5010015 00524315
	v_mul_f32_e32 v38, v38, v12                                 ; 104c1926
	v_cndmask_b32_e64 v46, v46, v22, s[18:19]                   ; d501002e 004a2d2e
	v_mad_f32 v30, 2.0, v11, v17                                ; d541001e 044616f4
	v_mul_f32_e32 v42, v42, v12                                 ; 1054192a
	v_mad_f32 v35, 2.0, v17, v11                                ; d5410023 042e22f4
	v_mac_f32_e32 v34, v32, v23                                 ; 3e442f20
	v_cndmask_b32_e64 v51, v13, v27, s[20:21]                   ; d5010033 0052370d
	v_cndmask_b32_e64 v49, v49, v24, s[18:19]                   ; d5010031 004a3131
	v_mad_f32 v50, 2.0, v11, v21                                ; d5410032 045616f4
	v_mad_f32 v43, 2.0, v21, v17                                ; d541002b 04462af4
	v_mad_f32 v39, 2.0, v17, v21                                ; d5410027 045622f4
	v_mad_f32 v44, 2.0, v21, v11                                ; d541002c 042e2af4
	v_mac_f32_e32 v38, v37, v25                                 ; 3e4c3325
	v_mul_f32_e32 v16, v16, v13                                 ; 10201b10
	v_mac_f32_e32 v42, v41, v25                                 ; 3e543329
	v_mul_f32_e32 v48, v48, v13                                 ; 10601b30
	v_mac_f32_e32 v34, v31, v22                                 ; 3e442d1f
	v_cndmask_b32_e64 v51, v51, v26, s[18:19]                   ; d5010033 004a3533
	v_sub_f32_e32 v18, v18, v8                                  ; 08241112
	v_sub_f32_e32 v19, v19, v9                                  ; 08261313
	v_sub_f32_e32 v20, v20, v10                                 ; 08281514
	v_mac_f32_e32 v38, v36, v24                                 ; 3e4c3124
	v_mac_f32_e32 v16, v15, v27                                 ; 3e20370f
	v_mac_f32_e32 v42, v40, v24                                 ; 3e543128
	v_mac_f32_e32 v48, v47, v27                                 ; 3e60372f
	v_mad_f32 v34, v34, -v46, v30                               ; d5410022 447a5d22
	v_add_f32_e32 v11, v11, v17                                 ; 0616230b
	v_mul_f32_e32 v20, v20, v3                                  ; 10280714
	v_mad_f32 v38, v38, -v49, v35                               ; d5410026 448e6326
	v_mac_f32_e32 v16, v14, v26                                 ; 3e20350e
	v_mad_f32 v42, v42, -v49, v39                               ; d541002a 449e632a
	v_mac_f32_e32 v48, v45, v26                                 ; 3e60352d
	v_add_f32_e32 v11, v11, v21                                 ; 06162b0b
	v_mac_f32_e32 v20, v19, v23                                 ; 3e282f13
	v_add_f32_e32 v52, v34, v38                                 ; 06684d22
	v_mad_f32 v16, v16, -v51, v43                               ; d5410010 44ae6710
	v_mad_f32 v48, v48, -v51, v44                               ; d5410030 44b26730
	v_mac_f32_e32 v20, v18, v22                                 ; 3e282d12
	v_add_f32_e32 v52, v42, v52                                 ; 0668692a
	v_mad_f32 v20, v20, -v46, v50                               ; d5410014 44ca5d14
	v_add_f32_e32 v52, v16, v52                                 ; 06686910
	v_add_f32_e32 v52, v48, v52                                 ; 06686930
	v_add_f32_e32 v52, v20, v52                                 ; 06686914
	v_mul_f32_e32 v52, 0x3d638e3a, v52                          ; 106868ff 3d638e3a
	v_mad_f32 v11, 0x3eaaaaab, -v11, v52 div:2                  ; d541000b 5cd216ff 3eaaaaab
	v_add_f32_e32 v52, v52, v11                                 ; 06681734
	s_and_b64 exec, s[20:21], exec                              ; 87fe7e14
	s_cbranch_execz BB17                                        ; bf880017
BB9:
	s_and_saveexec_b64 s[14:15], s[18:19]                       ; be8e2412
	s_cbranch_execz BB12                                        ; bf880008
BB10:
	s_mul_i32 s5, s17, 0xc0                                     ; 9305ff11 000000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mov_b32_e32 v8, s16                                       ; 7e100210
	v_mad_u32_u24 v3, 20, v2, s5                                ; d5430003 00160494
	ds_write_b32 v3, v8 offset:16                               ; d8340010 00000803
BB12:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_andn2_b64 exec, s[14:15], exec                            ; 8afe7e0e
	s_cbranch_execz BB15                                        ; bf880008
BB13:
	s_mul_i32 s5, s17, 0xc0                                     ; 9305ff11 000000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mov_b32_e32 v8, s16                                       ; 7e100210
	v_mad_u32_u24 v3, 20, v2, s5                                ; d5430003 00160494
	ds_write_b32 v3, v8 offset:20                               ; d8340014 00000803
BB15:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[14:15]                                    ; befe040e
BB17:
	s_andn2_b64 exec, s[12:13], exec                            ; 8afe7e0c
	s_cbranch_execz BB26                                        ; bf880015
BB18:
	s_and_saveexec_b64 s[14:15], vcc                            ; be8e246a
	s_cbranch_execz BB21                                        ; bf880008
BB19:
	s_mul_i32 s5, s17, 0xc0                                     ; 9305ff11 000000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mov_b32_e32 v8, s16                                       ; 7e100210
	v_mad_u32_u24 v3, 20, v2, s5                                ; d5430003 00160494
	ds_write_b32 v3, v8 offset:24                               ; d8340018 00000803
BB21:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_andn2_b64 exec, s[14:15], exec                            ; 8afe7e0e
	s_cbranch_execz BB26                                        ; bf880008
BB22:
	s_mul_i32 s5, s17, 0xc0                                     ; 9305ff11 000000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mov_b32_e32 v8, s16                                       ; 7e100210
	v_mad_u32_u24 v3, 20, v2, s5                                ; d5430003 00160494
	ds_write_b32 v3, v8 offset:28                               ; d834001c 00000803
BB26:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_eq_i32_e32 0, v0                                     ; 7d240080
	s_mov_b64 vcc, exec                                         ; beea047e
BB27:
	s_mulk_i32 s17, 0xc0                                        ; b81100c0
	v_mad_u32_u24 v0, 20, v2, s17                               ; d5430000 00460494
	ds_read2_b32 v[8:9], v0 offset0:4 offset1:5                 ; d8dc0504 08000000
	ds_read_b32 v14, v0 offset:24                               ; d8d80018 0e000000
	s_mov_b64 s[14:15], 7                                       ; be8e0487
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_min3_f32 v3, v8, v9, v14                                  ; d5510003 043a1308
	v_max3_f32 v10, v8, v9, v14                                 ; d554000a 043a1308
	v_cmp_lt_f32_e64 s[18:19], 0, v3                            ; d4010012 00020680
	v_max_f32_e32 v10, s16, v10                                 ; 20141410
	v_cmp_ge_f32_e64 s[20:21], 1.0, v10                         ; d4060014 000214f2
	s_nand_b64 s[20:21], s[20:21], s[18:19]                     ; 8c941214
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_andn2_b64 s[18:19], exec, s[18:19]                        ; 8a92127e
	s_cselect_b64 s[18:19], -1, 0                               ; 859280c1
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_mov_b32 s5, src_scc                                       ; be8503fd
	s_and_b64 s[18:19], s[20:21], exec                          ; 87927e14
	s_cselect_b64 s[18:19], -1, 0                               ; 859280c1
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_lshl_b32 s17, src_scc, 1                                  ; 8f1181fd
	s_or_b32 s5, s5, s17                                        ; 88051105
	s_and_saveexec_b64 s[14:15], s[14:15]                       ; be8e240e
BB28:
	s_ff1_i32_b64 s17, exec                                     ; be91147e
	s_lshl_b64 s[18:19], 1, s17                                 ; 8f921181
	s_and_saveexec_b64 s[18:19], s[18:19]                       ; be922412
	s_cbranch_execz BB44                                        ; bf880004
BB29:
	v_mov_b32_e32 v0, s5                                        ; 7e000205
	v_mov_b32_e32 v3, 0                                         ; 7e060280
	ds_and_b32 v3, v0                                           ; d8240000 00000003
BB44:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_b64 exec, s[10:11], exec                              ; 87fe7e0a
BB45:
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	ds_read_b32 v0, v0                                          ; d8d80000 00000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_readfirstlane_b32 s5, v0                                  ; 7e0a0500
BB50:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_and_b64 exec, vcc, exec                                   ; 87fe7e6a
BB51:
	s_load_dwordx4 s[20:23], s[0:1], 0x50                       ; f4080500 fa000050
	v_mov_b32_e32 v10, v14                                      ; 7e14030e
	v_mov_b32_e32 v11, s16                                      ; 7e160210
	v_lshlrev_b32_e32 v2, 4, v2                                 ; 34040484
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[8:11], v2, s[20:23], s4 offen glc    ; e0785000 04050802
BB56:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_cmp_lg_i32 s5, 1                                          ; bf018105
	s_mov_b32 s4, 0x3eaaaaab                                    ; be8403ff 3eaaaaab
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_mul_f32_e32 v48, s4, v48                                  ; 10606004
	v_mul_f32_e32 v20, s4, v20                                  ; 10282804
	v_mul_f32_e32 v34, s4, v34                                  ; 10444404
	v_mul_f32_e32 v38, s4, v38                                  ; 104c4c04
	v_mul_f32_e32 v42, s4, v42                                  ; 10545404
	v_mul_f32_e32 v16, s4, v16                                  ; 10202004
	v_cndmask_b32_e32 v14, 0, v52, vcc                          ; 021c6880
	v_cndmask_b32_e32 v8, 0, v6, vcc                            ; 02100c80
	v_cndmask_b32_e32 v9, 0, v7, vcc                            ; 02120e80
	v_cndmask_b32_e32 v10, 0, v4, vcc                           ; 02140880
	v_cndmask_b32_e32 v11, 0, v5, vcc                           ; 02160a80
	s_cselect_b32 s10, 0, 0                                     ; 850a8080
	v_cndmask_b32_e32 v12, 0, v48, vcc                          ; 02186080
	v_cndmask_b32_e32 v13, 0, v20, vcc                          ; 021a2880
	v_cndmask_b32_e32 v4, 0, v34, vcc                           ; 02084480
	v_cndmask_b32_e32 v5, 0, v38, vcc                           ; 020a4c80
	v_cndmask_b32_e32 v6, 0, v42, vcc                           ; 020c5480
	v_cndmask_b32_e32 v7, 0, v16, vcc                           ; 020e2080
	s_cmp_lg_i32 s10, 0                                         ; bf01800a
	s_cselect_b64 s[10:11], -1, 0                               ; 858a80c1
BB61:
	s_load_dwordx4 s[12:15], s[0:1], 0x60                       ; f4080300 fa000060
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
	s_cbranch_execz BB72                                        ; bf88000c
BB62:
	v_lshlrev_b32_e32 v0, 4, v0                                 ; 34000084
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[8:11], v0, s[12:15], s2 offen glc    ; e0785000 02030800
	buffer_store_dwordx4 v[4:7], v0, s[12:15], s2 offen offset:3072 glc ; e0785c00 02030400
	v_cndmask_b32_e64 v15, 0, 1, s[10:11]                       ; d501000f 00290280
	v_add_nc_u32_e32 v0, 0x1000, v0                             ; 4a0000ff 00001000
	buffer_store_dwordx4 v[12:15], v0, s[12:15], s2 offen offset:2048 glc ; e0785800 02030c00
BB72:
	s_endpgm                                                    ; bf810000
