# Vertex Shader as LS + Tessellation Control Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s5, 0, s3                                 ; 99050380
	s_bfe_u64 exec, -1, s5                                      ; 94fe05c1
	s_cbranch_execz BB24                                        ; bf88009b
BB1:
	s_mov_b32 s5, s9                                            ; be850309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[16:23], s[8:9], null                       ; f40c0404 fa000000
	s_load_dwordx4 s[24:27], s[8:9], 0x20                       ; f4080604 fa000020
	v_add_nc_u32_e32 v2, s5, v2                                 ; 4a040405
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx3 v[3:5], v2, s[16:19], 0 idxen           ; e03c2000 80040302
	buffer_load_dwordx3 v[6:8], v2, s[20:23], 0 idxen offset:16 ; e03c2010 80050602
	buffer_load_dwordx3 v[9:11], v2, s[24:27], 0 idxen offset:32 ; e03c2020 80060902
	s_mov_b32 s6, s11                                           ; be86030b
	s_movk_i32 s11, 0x8000                                      ; b00b8000
	s_load_dwordx4 s[8:11], s[10:11], null                      ; f4080205 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x2                                                ; bfa10002
	s_buffer_load_dwordx16 s[16:31], s[8:11], 0x40              ; f4300404 fa000040
	s_buffer_load_dwordx16 s[32:47], s[8:11], null              ; f4300804 fa000000
	s_buffer_load_dwordx4 s[8:11], s[8:11], 0x80                ; f4280204 fa000080
	s_lshl_b32 s7, s3, 8                                        ; 8f078803
	s_bfe_u64 s[14:15], -1, s7                                  ; 948e07c1
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v3, s6, v3                                    ; 06060606
	v_add_f32_e32 v4, s12, v4                                   ; 0608080c
	v_add_f32_e32 v5, s13, v5                                   ; 060a0a0d
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v12, s24, v5, s28                                 ; d541000c 00720a18
	v_mad_f32 v13, s25, v5, s29                                 ; d541000d 00760a19
	v_mad_f32 v5, s26, v5, s30                                  ; d5410005 007a0a1a
	v_mac_f32_e32 v12, s20, v4                                  ; 3e180814
	v_mac_f32_e32 v13, s21, v4                                  ; 3e1a0815
	v_mac_f32_e32 v5, s22, v4                                   ; 3e0a0816
	v_mac_f32_e32 v12, s16, v3                                  ; 3e180610
	v_mac_f32_e32 v13, s17, v3                                  ; 3e1a0611
	v_mac_f32_e32 v5, s18, v3                                   ; 3e0a0612
	v_mad_f32 v18, s24, v5, s28                                 ; d5410012 00720a18
	v_mad_f32 v19, s25, v5, s29                                 ; d5410013 00760a19
	v_mad_f32 v14, s40, v5, s44                                 ; d541000e 00b20a28
	v_mad_f32 v15, s41, v5, s45                                 ; d541000f 00b60a29
	v_mad_f32 v16, s42, v5, s46                                 ; d5410010 00ba0a2a
	v_mad_f32 v17, s43, v5, s47                                 ; d5410011 00be0a2b
	v_mad_f32 v5, s26, v5, s30                                  ; d5410005 007a0a1a
	v_mac_f32_e32 v18, s20, v13                                 ; 3e241a14
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v20, s24, v8                                  ; 10281018
	v_mac_f32_e32 v19, s21, v13                                 ; 3e261a15
	v_mul_f32_e32 v21, s25, v8                                  ; 102a1019
	v_mac_f32_e32 v14, s36, v13                                 ; 3e1c1a24
	v_mul_f32_e32 v8, s26, v8                                   ; 1010101a
	v_mac_f32_e32 v15, s37, v13                                 ; 3e1e1a25
	v_mac_f32_e32 v16, s38, v13                                 ; 3e201a26
	v_mac_f32_e32 v17, s39, v13                                 ; 3e221a27
	v_mac_f32_e32 v5, s22, v13                                  ; 3e0a1a16
	v_mac_f32_e32 v18, s16, v12                                 ; 3e241810
	v_mac_f32_e32 v20, s20, v7                                  ; 3e280e14
	v_mac_f32_e32 v19, s17, v12                                 ; 3e261811
	v_mac_f32_e32 v21, s21, v7                                  ; 3e2a0e15
	v_mac_f32_e32 v14, s32, v12                                 ; 3e1c1820
	v_mac_f32_e32 v8, s22, v7                                   ; 3e100e16
	v_mac_f32_e32 v15, s33, v12                                 ; 3e1e1821
	v_mac_f32_e32 v16, s34, v12                                 ; 3e201822
	v_mac_f32_e32 v17, s35, v12                                 ; 3e221823
	v_mac_f32_e32 v5, s18, v12                                  ; 3e0a1812
	v_sub_f32_e32 v25, s8, v18                                  ; 08322408
	v_mul_f32_e32 v30, -1.0, v18                                ; 103c24f3
	v_mac_f32_e32 v20, s16, v6                                  ; 3e280c10
	v_sub_f32_e32 v26, s9, v19                                  ; 08342609
	v_mul_f32_e32 v31, -1.0, v19                                ; 103e26f3
	v_mac_f32_e32 v21, s17, v6                                  ; 3e2a0c11
	v_mac_f32_e32 v8, s18, v6                                   ; 3e100c12
	v_sub_f32_e32 v27, s10, v5                                  ; 08360a0a
	v_mul_f32_e32 v24, -1.0, v5                                 ; 10300af3
	s_and_saveexec_b64 s[6:7], s[14:15]                         ; be86240e
	s_cbranch_execz BB13                                        ; bf880011
BB2:
	v_bfe_u32 v0, v1, 8, 5                                      ; d5480000 02151101
	v_cmp_eq_i32_e32 vcc, 0, v0                                 ; 7d040080
	v_cndmask_b32_e64 v4, 0, 1.0, vcc                           ; d5010004 01a9e480
	v_cndmask_b32_e64 v7, 0, 2.0, vcc                           ; d5010007 01a9e880
	s_and_saveexec_b64 s[8:9], vcc                              ; be88246a
BB3:
	s_load_dwordx4 s[12:15], s[0:1], 0x50                       ; f4080300 fa000050
	v_lshlrev_b32_sdwa v0, 4, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 340002f9 00860684
	v_mov_b32_e32 v5, v4                                        ; 7e0a0304
	v_mov_b32_e32 v6, v4                                        ; 7e0c0304
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[4:7], v0, s[12:15], s4 offen glc     ; e0785000 04030400
BB13:
	s_load_dwordx4 s[8:11], s[0:1], 0x60                        ; f4080200 fa000060
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
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
	s_and_b64 s[0:1], s[0:1], -1                                ; 8780c100
	s_and_b64 exec, s[0:1], exec                                ; 87fe7e00
	s_cbranch_execz BB24                                        ; bf880013
BB14:
	v_lshlrev_b32_e32 v0, 4, v0                                 ; 34000084
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_lshrrev_b64 v[22:23], 0, v[8:9]                           ; d7000016 00021080
	v_lshrrev_b64 v[28:29], 0, v[10:11]                         ; d700001c 00021480
	v_add_nc_u32_e32 v1, 0x1000, v0                             ; 4a0200ff 00001000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[14:17], v0, s[8:11], s2 offen glc    ; e0785000 02020e00
	buffer_store_dwordx4 v[20:23], v0, s[8:11], s2 offen offset:3072 glc ; e0785c00 02021400
	buffer_store_dwordx4 v[28:31], v1, s[8:11], s2 offen offset:2048 glc ; e0785800 02021c01
	v_add_nc_u32_e32 v0, 0x2000, v0                             ; 4a0000ff 00002000
	buffer_store_dwordx4 v[24:27], v0, s[8:11], s2 offen offset:1024 glc ; e0785400 02021800
BB24:
	s_endpgm                                                    ; bf810000
