# Tessellation Control Shader
BB0:
	s_lshl_b32 s5, s3, 8                                        ; 8f058803
	s_bfe_u64 s[6:7], -1, s5                                    ; 948605c1
	s_and_saveexec_b64 s[8:9], s[6:7]                           ; be882406
	s_cbranch_execz BB24                                        ; bf880040
BB1:
	s_barrier                                                   ; bf8a0000
	s_and_saveexec_b64 s[6:7], s[6:7]                           ; be862406
	s_cbranch_execz BB13                                        ; bf88001e
BB2:
	v_bfe_u32 v0, v1, 8, 5                                      ; d5480000 02151101
	s_bfe_u32 s17, s17, 0x60011                                 ; 9391ff11 00060011
	s_cselect_b32 s5, 4, 0                                      ; 85058084
	v_cmp_eq_i32_e32 vcc, 0, v0                                 ; 7d040080
	s_lshl4_add_u32 s17, s17, s5                                ; 98910511
	s_mul_i32 s10, 3, s17                                       ; 930a1183
	v_mul_u32_u24_sdwa v2, s10, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 160402f9 0086060a
	v_mad_u32_u24 v0, s17, v0, v2                               ; d5430000 040a0011
	ds_read2_b32 v[2:3], v0 offset0:4 offset1:5                 ; d8dc0504 02000000
	ds_read2_b32 v[6:7], v0 offset0:6 offset1:7                 ; d8dc0706 06000000
	v_cndmask_b32_e64 v4, 0, 1.0, vcc                           ; d5010004 01a9e480
	s_and_saveexec_b64 s[10:11], vcc                            ; be8a246a
BB3:
	s_load_dwordx4 s[12:15], s[0:1], 0x50                       ; f4080300 fa000050
	v_lshlrev_b32_sdwa v0, 4, v1 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:BYTE_0 ; 340002f9 00860684
	v_mov_b32_e32 v8, v4                                        ; 7e100304
	v_mov_b32_e32 v9, v4                                        ; 7e120304
	v_mov_b32_e32 v10, v4                                       ; 7e140304
	v_mov_b32_e32 v11, v4                                       ; 7e160304
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[8:11], v0, s[12:15], s4 offen glc    ; e0785000 04030800
BB13:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
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
	s_and_b64 exec, s[0:1], exec                                ; 87fe7e00
	s_cbranch_execz BB24                                        ; bf880006
BB14:
	v_lshlrev_b32_e32 v0, 4, v0                                 ; 34000084
	v_lshrrev_b64 v[4:5], 0, v[2:3]                             ; d7000004 00020480
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dwordx4 v[4:7], v0, s[12:15], s2 offen glc     ; e0785000 02030400
BB24:
	s_endpgm                                                    ; bf810000
