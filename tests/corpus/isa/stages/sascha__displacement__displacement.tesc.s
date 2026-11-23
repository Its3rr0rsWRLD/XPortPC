# Tessellation Control Shader
BB0:
	s_lshl_b32 s5, s3, 8                                        ; 8f058803
	s_bfe_u64 s[6:7], -1, s5                                    ; 948605c1
	s_and_saveexec_b64 s[8:9], s[6:7]                           ; be882406
	s_cbranch_execz BB60                                        ; bf8800b7
BB1:
	s_barrier                                                   ; bf8a0000
	s_and_saveexec_b64 s[6:7], s[6:7]                           ; be862406
	s_cbranch_execz BB49                                        ; bf880089
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
	v_bfe_u32 v0, v1, 8, 5                                      ; d5480000 02151101
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_eq_i32_e32 0, v0                                     ; 7d240080
	s_mov_b64 vcc, exec                                         ; beea047e
	s_cbranch_execz BB14                                        ; bf88000e
BB9:
	s_movk_i32 s15, 0x8000                                      ; b00f8000
	s_load_dword s14, s[14:15], null                            ; f4000387 fa000000
	s_movk_i32 s15, 0x8000                                      ; b00f8000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_load_dwordx4 s[20:23], s[14:15], null                     ; f4080507 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s5, s[20:23], 0x98                      ; f420014a fa000098
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_mov_b32 s14, s5                                           ; be8e0305
	s_mov_b32 s15, s5                                           ; be8f0305
	s_mov_b32 s16, s5                                           ; be900305
BB14:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_bfe_u32 s17, s17, 0x60011                                 ; 9391ff11 00060011
	s_cselect_b32 s18, 4, 0                                     ; 85128084
	s_lshl4_add_u32 s17, s17, s18                               ; 98911211
	s_mul_i32 s19, 3, s17                                       ; 93131183
	v_mul_u32_u24_sdwa v2, s19, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 160402f9 00860613
	v_mad_u32_u24 v0, s17, v0, v2                               ; d5430000 040a0011
	ds_read2_b32 v[2:3], v0 offset0:4 offset1:5                 ; d8dc0504 02000000
	ds_read2_b32 v[4:5], v0 offset0:6 offset1:7                 ; d8dc0706 04000000
	ds_read2_b32 v[6:7], v0 offset0:24 offset1:25               ; d8dc1918 06000000
	ds_read2_b32 v[8:9], v0 offset0:20 offset1:21               ; d8dc1514 08000000
	ds_read_b32 v0, v0 offset:88                                ; d8d80058 00000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_b64 exec, vcc, exec                                   ; 87fe7e6a
BB15:
	s_round_mode 0x0                                            ; bfa40000
	s_denorm_mode 12                                            ; bfa5000c
	v_min_f32_e64 v10, s5, s14                                  ; d50f000a 00001c05
	v_max_f32_e64 v11, s5, s14                                  ; d510000b 00001c05
	v_min_f32_e32 v10, s15, v10                                 ; 1e14140f
	v_max3_f32 v11, s15, v11, s16                               ; d554000b 0042160f
	v_cmp_lt_f32_e64 s[18:19], 0, v10                           ; d4010012 00021480
	v_cmp_ge_f32_e64 s[20:21], 1.0, v11                         ; d4060014 000216f2
	s_nand_b64 s[20:21], s[20:21], s[18:19]                     ; 8c941214
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_andn2_b64 s[18:19], exec, s[18:19]                        ; 8a92127e
	s_cselect_b64 s[18:19], -1, 0                               ; 859280c1
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_mov_b32 s17, src_scc                                      ; be9103fd
	s_and_b64 s[18:19], s[20:21], exec                          ; 87927e14
	s_cselect_b64 s[18:19], -1, 0                               ; 859280c1
	s_not_b64 s[18:19], s[18:19]                                ; be920812
	s_lshl_b32 s18, src_scc, 1                                  ; 8f1281fd
	s_or_b32 s17, s17, s18                                      ; 88111211
	s_mov_b64 s[18:19], 7                                       ; be920487
	s_and_saveexec_b64 s[18:19], s[18:19]                       ; be922412
BB16:
	s_ff1_i32_b64 s20, exec                                     ; be94147e
	s_lshl_b64 s[20:21], 1, s20                                 ; 8f941481
	s_and_saveexec_b64 s[20:21], s[20:21]                       ; be942414
	s_cbranch_execz BB32                                        ; bf880004
BB17:
	v_mov_b32_e32 v10, s17                                      ; 7e140211
	v_mov_b32_e32 v11, 0                                        ; 7e160280
	ds_and_b32 v11, v10                                         ; d8240000 00000a0b
BB32:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_b64 exec, s[10:11], exec                              ; 87fe7e0a
BB33:
	v_mov_b32_e32 v10, 0                                        ; 7e140280
	ds_read_b32 v10, v10                                        ; d8d80000 0a00000a
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_readfirstlane_b32 s10, v10                                ; 7e14050a
BB38:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_and_b64 exec, vcc, exec                                   ; 87fe7e6a
BB39:
	s_load_dwordx4 s[20:23], s[0:1], 0x50                       ; f4080500 fa000050
	v_lshlrev_b32_sdwa v10, 4, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 341402f9 00860684
	v_mov_b32_e32 v12, s5                                       ; 7e180205
	v_lshrrev_b64 v[13:14], 0, s[14:15]                         ; d700000d 00001c80
	v_mov_b32_e32 v15, s16                                      ; 7e1e0210
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[12:15], v10, s[20:23], s4 offen glc  ; e0785000 04050c0a
BB44:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_cmp_lg_i32 s10, 1                                         ; bf01810a
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cselect_b32 s4, 0, 0                                      ; 85048080
	v_cndmask_b32_e32 v12, 0, v2, vcc                           ; 02180480
	v_cndmask_b32_e32 v13, 0, v3, vcc                           ; 021a0680
	v_cndmask_b32_e32 v14, 0, v4, vcc                           ; 021c0880
	v_cndmask_b32_e32 v15, 0, v5, vcc                           ; 021e0a80
	v_cndmask_b32_e32 v16, 0, v8, vcc                           ; 02201080
	v_cndmask_b32_e32 v17, 0, v9, vcc                           ; 02221280
	v_cndmask_b32_e32 v18, 0, v0, vcc                           ; 02240080
	v_cndmask_b32_e32 v19, 0, v6, vcc                           ; 02260c80
	v_cndmask_b32_e32 v4, 0, v7, vcc                            ; 02080e80
	s_cmp_lg_i32 s4, 0                                          ; bf018004
	s_cselect_b64 s[4:5], -1, 0                                 ; 858480c1
	s_mov_b64 s[14:15], s[4:5]                                  ; be8e0404
	s_mov_b64 s[12:13], s[4:5]                                  ; be8c0404
BB49:
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
	s_cmp_lg_i32 s10, 1                                         ; bf01810a
	s_cselect_b64 s[10:11], -1, 0                               ; 858a80c1
	s_and_b64 s[0:1], s[0:1], s[10:11]                          ; 87800a00
	s_and_b64 exec, s[0:1], exec                                ; 87fe7e00
	s_cbranch_execz BB60                                        ; bf880010
BB50:
	v_lshlrev_b32_e32 v0, 4, v0                                 ; 34000084
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[12:15], v0, s[16:19], s2 offen glc   ; e0785000 02040c00
	buffer_store_dwordx4 v[16:19], v0, s[16:19], s2 offen offset:3072 glc ; e0785c00 02041000
	v_cndmask_b32_e64 v7, 0, 1, s[14:15]                        ; d5010007 00390280
	v_cndmask_b32_e64 v6, 0, 1, s[12:13]                        ; d5010006 00310280
	v_cndmask_b32_e64 v5, 0, 1, s[4:5]                          ; d5010005 00110280
	v_add_nc_u32_e32 v0, 0x1000, v0                             ; 4a0000ff 00001000
	buffer_store_dwordx4 v[4:7], v0, s[16:19], s2 offen offset:2048 glc ; e0785800 02040400
BB60:
	s_endpgm                                                    ; bf810000
