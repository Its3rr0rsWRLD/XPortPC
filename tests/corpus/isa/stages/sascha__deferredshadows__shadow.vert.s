# Vertex Shader as ES + Geometry Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s0, 0, s3                                 ; 99000380
	s_bfe_u64 exec, -1, s0                                      ; 94fe00c1
	s_cbranch_execz BB6                                         ; bf880018
BB1:
	s_mov_b32 s0, s9                                            ; be800309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_load_dwordx4 s[4:7], s[8:9], null                         ; f4080104 fa000000
	v_add_nc_u32_e32 v5, s0, v5                                 ; 4a0a0a00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx4 v[4:7], v5, s[4:7], 0 idxen             ; e0382000 80010405
	v_add_nc_u32_e32 v8, s10, v8                                ; 4a10100a
	s_bfe_u32 s1, s3, 0x40018                                   ; 9381ff03 00040018
	s_lshl_b32 s1, s1, 6                                        ; 8f018601
	v_mbcnt_lo_u32_b32 v2, -1, s1                               ; d7650002 000002c1
	v_mbcnt_hi_u32_b32 v2, -1, v2                               ; d7660002 000204c1
	v_mul_u32_u24_e32 v2, 36, v2                                ; 160404a4
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	ds_write_b32 v2, v8 offset:16                               ; d8340010 00000802
	ds_write2_b32 v2, v4, v5 offset1:1                          ; d8380100 00050402
	ds_write2_b32 v2, v6, v7 offset0:2 offset1:3                ; d8380302 00070602
BB6:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_lshl_b32 s0, s3, 8                                        ; 8f008803
	s_pack_ll_b32_b16 s12, s12, 0                               ; 990c800c
	s_bfe_u64 s[0:1], -1, s0                                    ; 948000c1
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_cbranch_execz BB21                                        ; bf8800a6
BB7:
	v_mad_u32_u16 v2, 36, v0, 0                                 ; d7730002 020200a4
	ds_read_b32 v4, v2 offset:16                                ; d8d80010 04000002
	s_mov_b32 s0, s11                                           ; be80030b
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_load_dwordx4 s[4:7], s[0:1], null                         ; f4080100 fa000000
	v_and_b32_e32 v3, 31, v3                                    ; 3606069f
	v_lshlrev_b32_e32 v5, 6, v3                                 ; 340a0686
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_lshlrev_b32_e32 v4, 4, v4                                 ; 34080884
	s_clause 0x4                                                ; bfa10004
	buffer_load_dwordx4 v[8:11], v4, s[4:7], 0 offen offset:192 ; e03810c0 80010804
	buffer_load_dwordx4 v[12:15], v5, s[4:7], 0 offen offset:48 ; e0381030 80010c05
	buffer_load_dwordx4 v[16:19], v5, s[4:7], 0 offen offset:32 ; e0381020 80011005
	buffer_load_dwordx4 v[20:23], v5, s[4:7], 0 offen offset:16 ; e0381010 80011405
	buffer_load_dwordx4 v[4:7], v5, s[4:7], 0 offen             ; e0381000 80010405
	ds_read2_b32 v[24:25], v2 offset1:1                         ; d8dc0100 18000002
	ds_read2_b32 v[26:27], v2 offset0:2 offset1:3               ; d8dc0302 1a000002
	s_bfe_u32 s0, s3, 0x40018                                   ; 9380ff03 00040018
	v_mov_b32_e32 v29, 4                                        ; 7e3a0284
	v_mad_u32_u16 v0, 36, v0, 0 op_sel:[0,1,0,0]                ; d7731000 020200a4
	v_mad_u32_u16 v1, 36, v1, 0                                 ; d7730001 020202a4
	v_mov_b32_e32 v30, 5                                        ; 7e3c0285
	s_lshl_b32 s0, s0, 6                                        ; 8f008600
	s_bfe_u32 s13, s13, 0x30006                                 ; 938dff0d 00030006
	v_mbcnt_lo_u32_b32 v28, -1, s0                              ; d765001c 000000c1
	s_bitcmp1_b32 s13, 0                                        ; bf0d800d
	s_cselect_b64 s[0:1], -1, 0                                 ; 858080c1
	v_mbcnt_hi_u32_b32 v28, -1, v28                             ; d766001c 000238c1
	v_mad_u32_u24 v28, 0x54, v28, s12                           ; d543001c 003238ff 00000054
	s_waitcnt vmcnt(4) lgkmcnt(1)                               ; bf8c0174
	v_add_f32_e32 v24, v24, v8                                  ; 06301118
	v_add_f32_e32 v25, v25, v9                                  ; 06321319
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v26, v26, v10                                 ; 0634151a
	v_add_f32_e32 v27, v27, v11                                 ; 0636171b
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mul_f32_e32 v32, v13, v27                                 ; 1040370d
	v_mul_f32_e32 v33, v14, v27                                 ; 1042370e
	v_mul_f32_e32 v31, v12, v27                                 ; 103e370c
	v_mul_f32_e32 v27, v15, v27                                 ; 1036370f
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v32, v17, v26                                 ; 3e403511
	v_mac_f32_e32 v33, v18, v26                                 ; 3e423512
	v_mac_f32_e32 v31, v16, v26                                 ; 3e3e3510
	v_mac_f32_e32 v27, v19, v26                                 ; 3e363513
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v32, v21, v25                                 ; 3e403315
	v_mac_f32_e32 v33, v22, v25                                 ; 3e423316
	v_mac_f32_e32 v31, v20, v25                                 ; 3e3e3314
	v_mac_f32_e32 v27, v23, v25                                 ; 3e363317
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v32, v5, v24                                  ; 3e403105
	v_mac_f32_e32 v33, v6, v24                                  ; 3e423106
	v_mac_f32_e32 v31, v4, v24                                  ; 3e3e3104
	v_mac_f32_e32 v27, v7, v24                                  ; 3e363107
	ds_write2_b32 v28, v31, v32 offset0:1 offset1:2             ; d8380201 00201f1c
	ds_write2_b32 v28, v33, v27 offset0:3 offset1:4             ; d8380403 001b211c
	ds_write_b32 v28, v3 offset:20                              ; d8340014 0000031c
	ds_write_b8 v28, v29 offset:24                              ; d8780018 00001d1c
	ds_read2_b32 v[24:25], v0 offset1:1                         ; d8dc0100 18000000
	ds_read2_b32 v[26:27], v0 offset0:2 offset1:3               ; d8dc0302 1a000000
	s_waitcnt lgkmcnt(1)                                        ; bf8cc17f
	v_add_f32_e32 v25, v25, v9                                  ; 06321319
	v_add_f32_e32 v24, v24, v8                                  ; 06301118
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v27, v27, v11                                 ; 0636171b
	v_add_f32_e32 v26, v26, v10                                 ; 0634151a
	v_mul_f32_e32 v35, v13, v27                                 ; 1046370d
	v_mul_f32_e32 v34, v12, v27                                 ; 1044370c
	v_mul_f32_e32 v36, v14, v27                                 ; 1048370e
	v_mul_f32_e32 v27, v15, v27                                 ; 1036370f
	v_mac_f32_e32 v35, v17, v26                                 ; 3e463511
	v_mac_f32_e32 v34, v16, v26                                 ; 3e443510
	v_mac_f32_e32 v36, v18, v26                                 ; 3e483512
	v_mac_f32_e32 v27, v19, v26                                 ; 3e363513
	v_mac_f32_e32 v35, v21, v25                                 ; 3e463315
	v_mac_f32_e32 v34, v20, v25                                 ; 3e443314
	v_mac_f32_e32 v36, v22, v25                                 ; 3e483316
	v_mac_f32_e32 v27, v23, v25                                 ; 3e363317
	v_mac_f32_e32 v35, v5, v24                                  ; 3e463105
	v_mac_f32_e32 v34, v4, v24                                  ; 3e443104
	v_mac_f32_e32 v36, v6, v24                                  ; 3e483106
	v_mac_f32_e32 v27, v7, v24                                  ; 3e363107
	ds_write2_b32 v28, v34, v35 offset0:8 offset1:9             ; d8380908 0023221c
	ds_write2_b32 v28, v36, v27 offset0:10 offset1:11           ; d8380b0a 001b241c
	ds_write_b32 v28, v3 offset:48                              ; d8340030 0000031c
	ds_write_b8 v28, v29 offset:52                              ; d8780034 00001d1c
	ds_read2_b32 v[24:25], v1 offset1:1                         ; d8dc0100 18000001
	ds_read2_b32 v[0:1], v1 offset0:2 offset1:3                 ; d8dc0302 00000001
	s_waitcnt lgkmcnt(1)                                        ; bf8cc17f
	v_add_f32_e32 v24, v24, v8                                  ; 06301118
	v_add_f32_e32 v25, v25, v9                                  ; 06321319
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v0, v0, v10                                   ; 06001500
	v_add_f32_e32 v1, v1, v11                                   ; 06021701
	v_mul_f32_e32 v12, v12, v1                                  ; 1018030c
	v_mul_f32_e32 v15, v15, v1                                  ; 101e030f
	v_mul_f32_e32 v14, v14, v1                                  ; 101c030e
	v_mul_f32_e32 v13, v13, v1                                  ; 101a030d
	v_mac_f32_e32 v12, v16, v0                                  ; 3e180110
	v_mac_f32_e32 v15, v19, v0                                  ; 3e1e0113
	v_mac_f32_e32 v14, v18, v0                                  ; 3e1c0112
	v_mac_f32_e32 v13, v17, v0                                  ; 3e1a0111
	v_mac_f32_e32 v12, v20, v25                                 ; 3e183314
	v_mac_f32_e32 v15, v23, v25                                 ; 3e1e3317
	v_mac_f32_e32 v14, v22, v25                                 ; 3e1c3316
	v_mac_f32_e32 v13, v21, v25                                 ; 3e1a3315
	v_mac_f32_e32 v12, v4, v24                                  ; 3e183104
	v_mac_f32_e32 v15, v7, v24                                  ; 3e1e3107
	v_mac_f32_e32 v14, v6, v24                                  ; 3e1c3106
	v_mac_f32_e32 v13, v5, v24                                  ; 3e1a3105
	ds_write2_b32 v28, v12, v13 offset0:15 offset1:16           ; d838100f 000d0c1c
	ds_write2_b32 v28, v14, v15 offset0:17 offset1:18           ; d8381211 000f0e1c
	ds_write_b32 v28, v3 offset:76                              ; d834004c 0000031c
	ds_write_b8 v28, v30 offset:80                              ; d8780050 00001e1c
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
	v_mad_u32_u24 v1, 28, v0, s12                               ; d5430001 0032009c
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 s2, v0                                    ; 7d280002
	s_cbranch_execz BB25                                        ; bf880002
BB22:
	ds_read_u8 v2, v1 offset:24                                 ; d8e80018 02000001
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
	s_add_u32 s4, s12, s0                                       ; 8004000c
	v_mov_b32_e32 v4, s1                                        ; 7e080201
	v_mov_b32_e32 v3, s4                                        ; 7e060204
	ds_write_b8 v3, v4                                          ; d8780000 00000403
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	v_mov_b32_e32 v5, s12                                       ; 7e0a020c
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
	v_mul_lo_u32 v3, 28, v5                                     ; d5690003 00020a9c
	v_mov_b32_sdwa v4, v0 dst_sel:BYTE_0 dst_unused:UNUSED_PRESERVE src0_sel:BYTE_0 ; 7e0802f9 00001000
	v_add_nc_u32_e32 v3, s12, v3                                ; 4a06060c
	ds_write_b8 v3, v4 offset:25                                ; d8780019 00000403
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
	s_cbranch_execz BB63                                        ; bf88000b
BB58:
	ds_read_u8 v1, v1 offset:25                                 ; d8e80019 01000001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_u32_u24 v1, 28, v1, s12                               ; d5430001 0032029c
	ds_read2_b32 v[4:5], v1 offset0:1 offset1:2                 ; d8dc0201 04000001
	ds_read2_b32 v[6:7], v1 offset0:3 offset1:4                 ; d8dc0403 06000001
	ds_read_b32 v1, v1 offset:20                                ; d8d80014 01000001
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
	exp pos0 v4, v5, v6, v7 vm                                  ; f80010cf 07060504
	exp pos1 off, off, v1, off done                             ; f80008d4 80018080
BB75:
	s_endpgm                                                    ; bf810000
