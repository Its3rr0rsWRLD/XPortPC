# Vertex Shader as ES + Geometry Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s0, 0, s3                                 ; 99000380
	s_bfe_u64 exec, -1, s0                                      ; 94fe00c1
	s_cbranch_execz BB6                                         ; bf880082
BB1:
	s_mov_b32 s0, s9                                            ; be800309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_load_dwordx4 s[4:7], s[8:9], null                         ; f4080104 fa000000
	v_add_nc_u32_e32 v5, s0, v5                                 ; 4a0a0a00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx3 v[2:4], v5, s[4:7], 0 idxen             ; e03c2000 80010205
	s_mov_b32 s1, s11                                           ; be81030b
	s_movk_i32 s11, 0x8000                                      ; b00b8000
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_load_dwordx4 s[4:7], s[10:11], null                       ; f4080105 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[32:47], s[4:7], 0x40               ; f4300802 fa000040
	s_buffer_load_dwordx16 s[48:63], s[4:7], null               ; f4300c02 fa000000
	s_bfe_u32 s4, s3, 0x40018                                   ; 9384ff03 00040018
	s_lshl_b32 s4, s4, 6                                        ; 8f048604
	v_mbcnt_lo_u32_b32 v5, -1, s4                               ; d7650005 000008c1
	v_mbcnt_hi_u32_b32 v5, -1, v5                               ; d7660005 00020ac1
	v_mul_u32_u24_e32 v5, 20, v5                                ; 160a0a94
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v7, s45, s14                                  ; d5080007 00001c2d
	v_mul_f32_e64 v8, s46, s14                                  ; d5080008 00001c2e
	v_mul_f32_e64 v9, s44, s18                                  ; d5080009 0000242c
	v_mul_f32_e64 v10, s45, s18                                 ; d508000a 0000242d
	v_mul_f32_e64 v11, s46, s18                                 ; d508000b 0000242e
	v_mul_f32_e64 v6, s44, s14                                  ; d5080006 00001c2c
	v_mad_f32 v7, s41, s13, v7                                  ; d5410007 041c1a29
	v_mad_f32 v8, s42, s13, v8                                  ; d5410008 04201a2a
	v_mad_f32 v9, s40, s17, v9                                  ; d5410009 04242228
	v_mad_f32 v10, s41, s17, v10                                ; d541000a 04282229
	v_mul_f32_e64 v12, s44, s22                                 ; d508000c 00002c2c
	v_mul_f32_e64 v13, s45, s22                                 ; d508000d 00002c2d
	v_mad_f32 v11, s42, s17, v11                                ; d541000b 042c222a
	v_mad_f32 v6, s40, s13, v6                                  ; d5410006 04181a28
	v_mul_f32_e64 v14, s46, s22                                 ; d508000e 00002c2e
	v_mad_f32 v7, s37, s12, v7                                  ; d5410007 041c1825
	v_mad_f32 v8, s38, s12, v8                                  ; d5410008 04201826
	v_mad_f32 v9, s36, s16, v9                                  ; d5410009 04242024
	v_mad_f32 v10, s37, s16, v10                                ; d541000a 04282025
	v_mad_f32 v12, s40, s21, v12                                ; d541000c 04302a28
	v_mad_f32 v13, s41, s21, v13                                ; d541000d 04342a29
	v_mad_f32 v11, s38, s16, v11                                ; d541000b 042c2026
	v_mad_f32 v6, s36, s12, v6                                  ; d5410006 04181824
	v_mad_f32 v14, s42, s21, v14                                ; d541000e 04382a2a
	v_mad_f32 v7, s33, s1, v7                                   ; d5410007 041c0221
	v_mad_f32 v8, s34, s1, v8                                   ; d5410008 04200222
	v_mad_f32 v9, s32, s15, v9                                  ; d5410009 04241e20
	v_mad_f32 v10, s33, s15, v10                                ; d541000a 04281e21
	v_mad_f32 v12, s36, s20, v12                                ; d541000c 04302824
	v_mad_f32 v13, s37, s20, v13                                ; d541000d 04342825
	v_mad_f32 v11, s34, s15, v11                                ; d541000b 042c1e22
	v_mad_f32 v6, s32, s1, v6                                   ; d5410006 04180220
	v_mad_f32 v14, s38, s20, v14                                ; d541000e 04382826
	v_mad_f32 v12, s32, s19, v12                                ; d541000c 04302620
	v_mad_f32 v13, s33, s19, v13                                ; d541000d 04342621
	v_mad_f32 v14, s34, s19, v14                                ; d541000e 04382622
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v12, v12, v4                                  ; 1018090c
	v_mul_f32_e32 v14, v14, v4                                  ; 101c090e
	v_mul_f32_e32 v13, v13, v4                                  ; 101a090d
	v_mac_f32_e32 v12, v9, v3                                   ; 3e180709
	v_mac_f32_e32 v14, v11, v3                                  ; 3e1c070b
	v_mac_f32_e32 v13, v10, v3                                  ; 3e1a070a
	v_mac_f32_e32 v12, v6, v2                                   ; 3e180506
	v_mac_f32_e32 v14, v8, v2                                   ; 3e1c0508
	v_mac_f32_e32 v13, v7, v2                                   ; 3e1a0507
	v_mad_f32 v16, s57, v14, s61                                ; d5410010 00f61c39
	v_mad_f32 v15, s56, v14, s60                                ; d541000f 00f21c38
	v_mad_f32 v17, s58, v14, s62                                ; d5410011 00fa1c3a
	v_mad_f32 v14, s59, v14, s63                                ; d541000e 00fe1c3b
	v_mac_f32_e32 v16, s53, v13                                 ; 3e201a35
	v_mac_f32_e32 v15, s52, v13                                 ; 3e1e1a34
	v_mac_f32_e32 v17, s54, v13                                 ; 3e221a36
	v_mac_f32_e32 v14, s55, v13                                 ; 3e1c1a37
	v_mac_f32_e32 v16, s49, v12                                 ; 3e201831
	v_mac_f32_e32 v15, s48, v12                                 ; 3e1e1830
	v_mac_f32_e32 v17, s50, v12                                 ; 3e221832
	v_mac_f32_e32 v14, s51, v12                                 ; 3e1c1833
	ds_write2_b32 v5, v15, v16 offset1:1                        ; d8380100 00100f05
	ds_write2_b32 v5, v17, v14 offset0:2 offset1:3              ; d8380302 000e1105
BB6:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_lshl_b32 s0, s3, 8                                        ; 8f008803
	s_pack_ll_b32_b16 s23, s23, 0                               ; 99178017
	s_bfe_u64 s[0:1], -1, s0                                    ; 948000c1
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_cbranch_execz BB21                                        ; bf880047
BB7:
	v_mad_u32_u16 v2, 20, v0, 0                                 ; d7730002 02020094
	ds_read2_b32 v[4:5], v2 offset1:1                           ; d8dc0100 04000002
	ds_read2_b32 v[2:3], v2 offset0:2 offset1:3                 ; d8dc0302 02000002
	s_bfe_u32 s0, s3, 0x40018                                   ; 9380ff03 00040018
	v_mov_b32_e32 v7, 4                                         ; 7e0e0284
	v_mad_u32_u16 v0, 20, v0, 0 op_sel:[0,1,0,0]                ; d7731000 02020094
	v_mad_u32_u16 v1, 20, v1, 0                                 ; d7730001 02020294
	v_mov_b32_e32 v8, 5                                         ; 7e100285
	s_lshl_b32 s0, s0, 6                                        ; 8f008600
	s_bfe_u32 s24, s24, 0x30006                                 ; 9398ff18 00030006
	v_mbcnt_lo_u32_b32 v6, -1, s0                               ; d7650006 000000c1
	s_bitcmp1_b32 s24, 0                                        ; bf0d8018
	s_cselect_b64 s[0:1], -1, 0                                 ; 858080c1
	v_mbcnt_hi_u32_b32 v6, -1, v6                               ; d7660006 00020cc1
	v_mad_u32_u24 v6, 60, v6, s23                               ; d5430006 005e0cbc
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	ds_write2_b32 v6, v4, v5 offset0:1 offset1:2                ; d8380201 00050406
	ds_write2_b32 v6, v2, v3 offset0:3 offset1:4                ; d8380403 00030206
	ds_write_b8 v6, v7 offset:20                                ; d8780014 00000706
	ds_read2_b32 v[2:3], v0 offset1:1                           ; d8dc0100 02000000
	ds_read2_b32 v[4:5], v0 offset0:2 offset1:3                 ; d8dc0302 04000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	ds_write2_b32 v6, v2, v3 offset0:6 offset1:7                ; d8380706 00030206
	ds_write2_b32 v6, v4, v5 offset0:8 offset1:9                ; d8380908 00050406
	ds_write_b8 v6, v7 offset:40                                ; d8780028 00000706
	ds_read2_b32 v[2:3], v1 offset1:1                           ; d8dc0100 02000001
	ds_read2_b32 v[0:1], v1 offset0:2 offset1:3                 ; d8dc0302 00000001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	ds_write2_b32 v6, v2, v3 offset0:11 offset1:12              ; d8380c0b 00030206
	ds_write2_b32 v6, v0, v1 offset0:13 offset1:14              ; d8380e0d 00010006
	ds_write_b8 v6, v8 offset:60                                ; d878003c 00000806
	s_cbranch_scc0 BB21                                         ; bf840010
BB8:
	s_and_b64 s[4:5], -1, exec                                  ; 87847ec1
	s_bcnt1_i32_b64 s4, s[4:5]                                  ; be841004
	s_ff1_i32_b64 s5, exec                                      ; be85147e
	s_lshl_b64 s[6:7], 1, s5                                    ; 8f860581
	s_and_b64 s[0:1], s[0:1], s[6:7]                            ; 87800600
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_and_saveexec_b64 s[0:1], s[0:1]                           ; be802400
	s_cbranch_execz BB21                                        ; bf880008
BB9:
	s_movk_i32 m0, 0x100                                        ; b07c0100
	v_mov_b32_e32 v0, s4                                        ; 7e000204
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	ds_add_u32 v1, v0 gds                                       ; d8020000 00000001
	v_mov_b32_e32 v2, 4                                         ; 7e040284
	ds_add_u32 v2, v0 gds                                       ; d8020000 00000002
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
	v_mad_u32_u24 v1, 20, v0, s23                               ; d5430001 005e0094
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
	s_add_u32 s4, s23, s0                                       ; 80040017
	v_mov_b32_e32 v4, s1                                        ; 7e080201
	v_mov_b32_e32 v3, s4                                        ; 7e060204
	ds_write_b8 v3, v4                                          ; d8780000 00000403
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	v_mov_b32_e32 v5, s23                                       ; 7e0a0217
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
	s_cbranch_execz BB51                                        ; bf880007
BB46:
	v_mul_lo_u32 v3, 20, v5                                     ; d5690003 00020a94
	v_mov_b32_sdwa v4, v0 dst_sel:BYTE_0 dst_unused:UNUSED_PRESERVE src0_sel:BYTE_0 ; 7e0802f9 00001000
	v_add_nc_u32_e32 v3, s23, v3                                ; 4a060617
	ds_write_b8 v3, v4 offset:21                                ; d8780015 00000403
BB51:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, -1                                          ; befe04c1
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	v_cmpx_gt_i32_e32 s2, v0                                    ; 7d280002
	s_mov_b64 vcc, exec                                         ; beea047e
BB52:
	v_bfe_u32 v3, v2, 1, 1                                      ; d5480003 02050302
	v_not_b32_e32 v2, v2                                        ; 7e046f02
	v_sub_nc_u32_e32 v4, v5, v3                                 ; 4c080705
	v_add_lshl_u32 v3, v5, v3, 10                               ; d7470003 022a0705
	v_add_nc_u32_e32 v5, -2, v5                                 ; 4a0a0ac2
	v_lshlrev_b32_e32 v4, 20, v4                                ; 34080894
	v_add_nc_u32_e32 v3, 0xfffffc00, v3                         ; 4a0606ff fffffc00
	v_or3_b32 v4, v4, v5, v3                                    ; d7720004 040e0b04
	v_lshl_or_b32 v2, v2, 31, v4                                ; d76f0002 04113f02
BB57:
	s_mov_b64 exec, -1                                          ; befe04c1
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 s3, v0                                    ; 7d280003
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_cbranch_execz BB63                                        ; bf880009
BB58:
	ds_read_u8 v1, v1 offset:21                                 ; d8e80015 01000001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_u32_u24 v1, 20, v1, s23                               ; d5430001 005e0294
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
