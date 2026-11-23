# Vertex Shader as LS + Tessellation Control Shader
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_pack_ll_b32_b16 s5, 0, s3                                 ; 99050380
	s_bfe_u64 exec, -1, s5                                      ; 94fe05c1
	s_cbranch_execz BB60                                        ; bf88009e
BB1:
	s_mov_b32 s5, s9                                            ; be850309
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_load_dwordx4 s[12:15], s[8:9], null                       ; f4080304 fa000000
	v_add_nc_u32_e32 v2, s5, v2                                 ; 4a040405
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx3 v[2:4], v2, s[12:15], 0 idxen           ; e03c2000 80030202
	s_lshl_b32 s6, s3, 8                                        ; 8f068803
	s_bfe_u64 s[6:7], -1, s6                                    ; 948606c1
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_and_saveexec_b64 s[6:7], s[6:7]                           ; be862406
	s_cbranch_execz BB49                                        ; bf880070
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
	s_cbranch_execz BB8                                         ; bf880005
BB3:
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_mov_b32_e32 v5, 3                                         ; 7e0a0283
	s_waitcnt_vscnt null, 0x0                                   ; bbfd0000
	ds_write_b32 v0, v5                                         ; d8340000 00000500
BB8:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	v_bfe_u32 v0, v1, 8, 5                                      ; d5480000 02151101
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_eq_i32_e32 0, v0                                     ; 7d240080
	s_mov_b64 vcc, exec                                         ; beea047e
	s_cbranch_execz BB14                                        ; bf88000e
BB9:
	s_movk_i32 s11, 0x8000                                      ; b00b8000
	s_load_dwordx4 s[16:19], s[10:11], 0x10                     ; f4080405 fa000010
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s5, s[16:19], null                      ; f4200148 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cmp_lt_f32_e64 s[10:11], 0, s5                            ; d401000a 00000a80
	s_and_b64 s[10:11], s[10:11], exec                          ; 878a7e0a
	s_cselect_b32 s5, s5, 1.0                                   ; 8505f205
	s_mov_b32 s10, s5                                           ; be8a0305
	s_mov_b32 s11, s5                                           ; be8b0305
	s_mov_b32 s14, s5                                           ; be8e0305
BB14:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_b64 exec, vcc, exec                                   ; 87fe7e6a
BB15:
	v_min_f32_e64 v0, s5, s10                                   ; d50f0000 00001405
	v_max_f32_e64 v5, s5, s10                                   ; d5100005 00001405
	v_min_f32_e32 v0, s11, v0                                   ; 1e00000b
	v_max3_f32 v5, s11, v5, s14                                 ; d5540005 003a0a0b
	v_cmp_lt_f32_e64 s[16:17], 0, v0                            ; d4010010 00020080
	v_cmp_ge_f32_e64 s[18:19], 1.0, v5                          ; d4060012 00020af2
	s_nand_b64 s[18:19], s[18:19], s[16:17]                     ; 8c921012
	s_not_b64 s[16:17], s[16:17]                                ; be900810
	s_andn2_b64 s[16:17], exec, s[16:17]                        ; 8a90107e
	s_cselect_b64 s[16:17], -1, 0                               ; 859080c1
	s_not_b64 s[16:17], s[16:17]                                ; be900810
	s_mov_b32 s15, src_scc                                      ; be8f03fd
	s_and_b64 s[16:17], s[18:19], exec                          ; 87907e12
	s_cselect_b64 s[16:17], -1, 0                               ; 859080c1
	s_not_b64 s[16:17], s[16:17]                                ; be900810
	s_lshl_b32 s16, src_scc, 1                                  ; 8f1081fd
	s_or_b32 s15, s15, s16                                      ; 880f100f
	s_mov_b64 s[16:17], 7                                       ; be900487
	s_and_saveexec_b64 s[16:17], s[16:17]                       ; be902410
BB16:
	s_ff1_i32_b64 s18, exec                                     ; be92147e
	s_lshl_b64 s[18:19], 1, s18                                 ; 8f921281
	s_and_saveexec_b64 s[18:19], s[18:19]                       ; be922412
	s_cbranch_execz BB32                                        ; bf880005
BB17:
	v_mov_b32_e32 v0, s15                                       ; 7e00020f
	v_mov_b32_e32 v5, 0                                         ; 7e0a0280
	s_waitcnt_vscnt null, 0x0                                   ; bbfd0000
	ds_and_b32 v5, v0                                           ; d8240000 00000005
BB32:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_barrier                                                   ; bf8a0000
	s_and_b64 exec, s[8:9], exec                                ; 87fe7e08
BB33:
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	s_waitcnt_vscnt null, 0x0                                   ; bbfd0000
	ds_read_b32 v0, v0                                          ; d8d80000 00000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_readfirstlane_b32 s8, v0                                  ; 7e100500
BB38:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_and_b64 exec, vcc, exec                                   ; 87fe7e6a
BB39:
	s_load_dwordx4 s[16:19], s[0:1], 0x50                       ; f4080400 fa000050
	v_lshlrev_b32_sdwa v0, 4, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 340002f9 00860684
	v_mov_b32_e32 v8, s5                                        ; 7e100205
	v_lshrrev_b64 v[9:10], 0, s[10:11]                          ; d7000009 00001480
	v_mov_b32_e32 v11, s14                                      ; 7e16020e
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[8:11], v0, s[16:19], s4 offen glc    ; e0785000 04040800
BB44:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_cmp_lg_i32 s8, 1                                          ; bf018108
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cselect_b32 s4, 0, 0                                      ; 85048080
	s_cmp_lg_i32 s4, 0                                          ; bf018004
	s_cselect_b64 s[4:5], -1, 0                                 ; 858480c1
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v8, 0, v2, vcc                            ; 02100480
	v_cndmask_b32_e32 v9, 0, v3, vcc                            ; 02120680
	v_cndmask_b32_e32 v10, 0, v4, vcc                           ; 02140880
BB49:
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
	s_cmp_lg_i32 s8, 1                                          ; bf018108
	s_cselect_b64 s[8:9], -1, 0                                 ; 858880c1
	s_and_b64 s[0:1], s[0:1], s[8:9]                            ; 87800800
	s_and_b64 exec, s[0:1], exec                                ; 87fe7e00
	s_cbranch_execz BB60                                        ; bf880006
BB50:
	v_lshlrev_b32_e32 v0, 4, v0                                 ; 34000084
	v_cndmask_b32_e64 v11, 0, 1, s[4:5]                         ; d501000b 00110280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[8:11], v0, s[12:15], s2 offen glc    ; e0785000 02030800
BB60:
	s_endpgm                                                    ; bf810000
