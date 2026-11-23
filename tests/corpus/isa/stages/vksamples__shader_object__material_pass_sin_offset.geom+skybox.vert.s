# Vertex Shader as ES + Geometry Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s0, 0, s3                                 ; 99000380
	s_bfe_u64 exec, -1, s0                                      ; 94fe00c1
	s_cbranch_execz BB6                                         ; bf880072
BB1:
	s_mov_b32 s0, s9                                            ; be800309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_load_dwordx4 s[4:7], s[8:9], null                         ; f4080104 fa000000
	v_add_nc_u32_e32 v5, s0, v5                                 ; 4a0a0a00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx3 v[2:4], v5, s[4:7], 0 idxen offset:16   ; e03c2010 80010205
	s_mov_b32 s0, s10                                           ; be80030a
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_load_dwordx4 s[4:7], s[0:1], null                         ; f4080100 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx4 s[32:35], s[4:7], 0x60                ; f4280802 fa000060
	s_buffer_load_dwordx8 s[40:47], s[4:7], 0x40                ; f42c0a02 fa000040
	s_bfe_u32 s1, s3, 0x40018                                   ; 9381ff03 00040018
	s_lshl_b32 s1, s1, 6                                        ; 8f018601
	v_mbcnt_lo_u32_b32 v5, -1, s1                               ; d7650005 000002c1
	v_mbcnt_hi_u32_b32 v5, -1, v5                               ; d7660005 00020ac1
	v_mul_u32_u24_e32 v5, 20, v5                                ; 160a0a94
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v6, s34, s21                                  ; d5080006 00002a22
	v_mul_f32_e64 v7, s46, s20                                  ; d5080007 0000282e
	v_mul_f32_e64 v8, s42, s19                                  ; d5080008 0000262a
	v_mul_f32_e64 v9, s24, s43                                  ; d5080009 00005618
	v_mul_f32_e64 v10, s25, s43                                 ; d508000a 00005619
	v_mul_f32_e64 v11, s23, s47                                 ; d508000b 00005e17
	v_mul_f32_e64 v12, s25, s47                                 ; d508000c 00005e19
	v_mad_f32 v7, s24, s47, v7                                  ; d5410007 041c5e18
	v_mad_f32 v8, s23, s43, v8                                  ; d5410008 04205617
	v_mad_f32 v9, s20, s42, v9                                  ; d5410009 04245414
	v_mad_f32 v10, s21, s42, v10                                ; d541000a 04285415
	v_mul_f32_e64 v13, s23, s35                                 ; d508000d 00004617
	v_mul_f32_e64 v14, s24, s35                                 ; d508000e 00004618
	v_mad_f32 v11, s19, s46, v11                                ; d541000b 042c5c13
	v_mad_f32 v12, s21, s46, v12                                ; d541000c 04305c15
	v_mad_f32 v7, s45, s16, v7                                  ; d5410007 041c202d
	v_mad_f32 v8, s41, s15, v8                                  ; d5410008 04201e29
	v_mad_f32 v6, s25, s35, v6                                  ; d5410006 04184619
	v_mad_f32 v9, s16, s41, v9                                  ; d5410009 04245210
	v_mad_f32 v10, s17, s41, v10                                ; d541000a 04285211
	v_mad_f32 v13, s19, s34, v13                                ; d541000d 04344413
	v_mad_f32 v14, s20, s34, v14                                ; d541000e 04384414
	v_mad_f32 v11, s15, s45, v11                                ; d541000b 042c5a0f
	v_mad_f32 v12, s17, s45, v12                                ; d541000c 04305a11
	v_mad_f32 v7, s44, s12, v7                                  ; d5410007 041c182c
	v_mad_f32 v8, s40, s11, v8                                  ; d5410008 04201628
	v_mad_f32 v6, s33, s17, v6                                  ; d5410006 04182221
	v_mad_f32 v9, s12, s40, v9                                  ; d5410009 0424500c
	v_mad_f32 v10, s13, s40, v10                                ; d541000a 0428500d
	v_mad_f32 v13, s15, s33, v13                                ; d541000d 0434420f
	v_mad_f32 v14, s16, s33, v14                                ; d541000e 04384210
	v_mad_f32 v11, s11, s44, v11                                ; d541000b 042c580b
	v_mad_f32 v12, s13, s44, v12                                ; d541000c 0430580d
	v_mad_f32 v6, s32, s13, v6                                  ; d5410006 04181a20
	v_mad_f32 v13, s11, s32, v13                                ; d541000d 0434400b
	v_mad_f32 v14, s12, s32, v14                                ; d541000e 0438400c
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v14, v14, v4                                  ; 101c090e
	v_mul_f32_e32 v13, v13, v4                                  ; 101a090d
	v_mul_f32_e32 v6, v6, v4                                    ; 100c0906
	v_mac_f32_e32 v14, v7, v3                                   ; 3e1c0707
	v_mac_f32_e32 v13, v11, v3                                  ; 3e1a070b
	v_mac_f32_e32 v6, v12, v3                                   ; 3e0c070c
	v_mac_f32_e32 v14, v9, v2                                   ; 3e1c0509
	v_mac_f32_e32 v13, v8, v2                                   ; 3e1a0508
	v_mac_f32_e32 v6, v10, v2                                   ; 3e0c050a
	ds_write2_b32 v5, v13, v14 offset1:1                        ; d8380100 000e0d05
	ds_write_b32 v5, v6 offset:8                                ; d8340008 00000605
BB6:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_lshl_b32 s0, s3, 8                                        ; 8f008803
	s_pack_ll_b32_b16 s27, s27, 0                               ; 991b801b
	s_bfe_u64 s[0:1], -1, s0                                    ; 948000c1
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_cbranch_execz BB21                                        ; bf88009c
BB7:
	v_mad_u32_u16 v2, 20, v0, 0                                 ; d7730002 02020094
	ds_read2_b32 v[4:5], v2 offset1:1                           ; d8dc0100 04000002
	ds_read_b32 v2, v2 offset:8                                 ; d8d80008 02000002
	s_movk_i32 s11, 0x8000                                      ; b00b8000
	s_load_dwordx4 s[4:7], s[10:11], null                       ; f4080105 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx16 s[32:47], s[4:7], 0x80               ; f4300802 fa000080
	v_mul_f32_e64 v3, s26, 0x40a00000                           ; d5080003 0001fe1a 40a00000
	s_mov_b32 s0, 0x3e4ccccd                                    ; be8003ff 3e4ccccd
	s_bfe_u32 s1, s3, 0x40018                                   ; 9381ff03 00040018
	v_mov_b32_e32 v9, 4                                         ; 7e120284
	v_mul_f32_e32 v6, 2.0, v4                                   ; 100c08f4
	v_mad_u32_u16 v0, 20, v0, 0 op_sel:[0,1,0,0]                ; d7731000 02020094
	v_mad_u32_u16 v1, 20, v1, 0                                 ; d7730001 02020294
	v_mov_b32_e32 v10, 5                                        ; 7e140285
	s_lshl_b32 s1, s1, 6                                        ; 8f018601
	s_bfe_u32 s28, s28, 0x30006                                 ; 939cff1c 00030006
	v_mad_f32 v6, |v6|, |v5|, v3                                ; d5410306 040e0b06
	v_mbcnt_lo_u32_b32 v8, -1, s1                               ; d7650008 000002c1
	s_bitcmp1_b32 s28, 0                                        ; bf0d801c
	s_cselect_b64 s[4:5], -1, 0                                 ; 858480c1
	v_mul_f32_e32 v6, 0.15915494, v6                            ; 100c0cf8
	v_mbcnt_hi_u32_b32 v8, -1, v8                               ; d7660008 000210c1
	v_sin_f32_e32 v7, v6                                        ; 7e0e6b06
	v_cos_f32_e32 v6, v6                                        ; 7e0c6d06
	v_mad_u32_u24 v8, 60, v8, s27                               ; d5430008 006e10bc
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v12, s41, v2, s45                                 ; d541000c 00b60429
	v_mad_f32 v13, s42, v2, s46                                 ; d541000d 00ba042a
	v_mad_f32 v11, s40, v2, s44                                 ; d541000b 00b20428
	v_mad_f32 v2, s43, v2, s47                                  ; d5410002 00be042b
	v_mac_f32_e32 v4, s0, v7                                    ; 3e080e00
	v_mac_f32_e32 v5, s0, v6                                    ; 3e0a0c00
	v_mac_f32_e32 v13, s38, v5                                  ; 3e1a0a26
	v_mac_f32_e32 v2, s39, v5                                   ; 3e040a27
	v_mac_f32_e32 v12, s37, v5                                  ; 3e180a25
	v_mac_f32_e32 v11, s36, v5                                  ; 3e160a24
	v_mac_f32_e32 v13, s34, v4                                  ; 3e1a0822
	v_mac_f32_e32 v2, s35, v4                                   ; 3e040823
	v_mac_f32_e32 v12, s33, v4                                  ; 3e180821
	v_mac_f32_e32 v11, s32, v4                                  ; 3e160820
	ds_write2_b32 v8, v11, v12 offset0:1 offset1:2              ; d8380201 000c0b08
	ds_write2_b32 v8, v13, v2 offset0:3 offset1:4               ; d8380403 00020d08
	ds_write_b8 v8, v9 offset:20                                ; d8780014 00000908
	ds_read2_b32 v[4:5], v0 offset1:1                           ; d8dc0100 04000000
	ds_read_b32 v0, v0 offset:8                                 ; d8d80008 00000000
	s_waitcnt lgkmcnt(1)                                        ; bf8cc17f
	v_mul_f32_e32 v14, 2.0, v4                                  ; 101c08f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v16, s40, v0, s44                                 ; d5410010 00b20028
	v_mad_f32 v18, s42, v0, s46                                 ; d5410012 00ba002a
	v_mad_f32 v17, s41, v0, s45                                 ; d5410011 00b60029
	v_mad_f32 v0, s43, v0, s47                                  ; d5410000 00be002b
	v_mad_f32 v14, |v14|, |v5|, v3                              ; d541030e 040e0b0e
	v_mul_f32_e32 v14, 0.15915494, v14                          ; 101c1cf8
	v_sin_f32_e32 v15, v14                                      ; 7e1e6b0e
	v_cos_f32_e32 v14, v14                                      ; 7e1c6d0e
	v_mac_f32_e32 v4, s0, v15                                   ; 3e081e00
	v_mac_f32_e32 v5, s0, v14                                   ; 3e0a1c00
	v_mac_f32_e32 v17, s37, v5                                  ; 3e220a25
	v_mac_f32_e32 v18, s38, v5                                  ; 3e240a26
	v_mac_f32_e32 v0, s39, v5                                   ; 3e000a27
	v_mac_f32_e32 v16, s36, v5                                  ; 3e200a24
	v_mac_f32_e32 v17, s33, v4                                  ; 3e220821
	v_mac_f32_e32 v18, s34, v4                                  ; 3e240822
	v_mac_f32_e32 v0, s35, v4                                   ; 3e000823
	v_mac_f32_e32 v16, s32, v4                                  ; 3e200820
	ds_write2_b32 v8, v16, v17 offset0:6 offset1:7              ; d8380706 00111008
	ds_write2_b32 v8, v18, v0 offset0:8 offset1:9               ; d8380908 00001208
	ds_write_b8 v8, v9 offset:40                                ; d8780028 00000908
	ds_read2_b32 v[4:5], v1 offset1:1                           ; d8dc0100 04000001
	ds_read_b32 v1, v1 offset:8                                 ; d8d80008 01000001
	s_waitcnt lgkmcnt(1)                                        ; bf8cc17f
	v_mul_f32_e32 v19, 2.0, v4                                  ; 102608f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v21, s40, v1, s44                                 ; d5410015 00b20228
	v_mad_f32 v22, s41, v1, s45                                 ; d5410016 00b60229
	v_mad_f32 v23, s42, v1, s46                                 ; d5410017 00ba022a
	v_mad_f32 v1, s43, v1, s47                                  ; d5410001 00be022b
	v_mad_f32 v19, |v19|, |v5|, v3                              ; d5410313 040e0b13
	v_mul_f32_e32 v19, 0.15915494, v19                          ; 102626f8
	v_sin_f32_e32 v20, v19                                      ; 7e286b13
	v_cos_f32_e32 v19, v19                                      ; 7e266d13
	v_mac_f32_e32 v4, s0, v20                                   ; 3e082800
	v_mac_f32_e32 v5, s0, v19                                   ; 3e0a2600
	v_mac_f32_e32 v22, s37, v5                                  ; 3e2c0a25
	v_mac_f32_e32 v21, s36, v5                                  ; 3e2a0a24
	v_mac_f32_e32 v23, s38, v5                                  ; 3e2e0a26
	v_mac_f32_e32 v1, s39, v5                                   ; 3e020a27
	v_mac_f32_e32 v22, s33, v4                                  ; 3e2c0821
	v_mac_f32_e32 v21, s32, v4                                  ; 3e2a0820
	v_mac_f32_e32 v23, s34, v4                                  ; 3e2e0822
	v_mac_f32_e32 v1, s35, v4                                   ; 3e020823
	ds_write2_b32 v8, v21, v22 offset0:11 offset1:12            ; d8380c0b 00161508
	ds_write2_b32 v8, v23, v1 offset0:13 offset1:14             ; d8380e0d 00011708
	ds_write_b8 v8, v10 offset:60                               ; d878003c 00000a08
	s_cbranch_scc0 BB21                                         ; bf840010
BB8:
	s_and_b64 s[0:1], -1, exec                                  ; 87807ec1
	s_bcnt1_i32_b64 s0, s[0:1]                                  ; be801000
	s_ff1_i32_b64 s1, exec                                      ; be81147e
	s_lshl_b64 s[6:7], 1, s1                                    ; 8f860181
	s_and_b64 s[4:5], s[4:5], s[6:7]                            ; 87840604
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_and_saveexec_b64 s[4:5], s[4:5]                           ; be842404
	s_cbranch_execz BB21                                        ; bf880008
BB9:
	s_movk_i32 m0, 0x100                                        ; b07c0100
	v_mov_b32_e32 v0, s0                                        ; 7e000200
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
	v_mad_u32_u24 v1, 20, v0, s27                               ; d5430001 006e0094
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
	s_add_u32 s4, s27, s0                                       ; 8004001b
	v_mov_b32_e32 v4, s1                                        ; 7e080201
	v_mov_b32_e32 v3, s4                                        ; 7e060204
	ds_write_b8 v3, v4                                          ; d8780000 00000403
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	v_mov_b32_e32 v5, s27                                       ; 7e0a021b
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
	v_add_nc_u32_e32 v3, s27, v3                                ; 4a06061b
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
	v_mad_u32_u24 v1, 20, v1, s27                               ; d5430001 006e0294
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
