# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_not_b64 s[8:9], 0                                         ; be880880
	s_and_saveexec_b64 s[8:9], s[8:9]                           ; be882408
	s_cbranch_execz BB12                                        ; bf880012
BB1:
	s_bcnt1_i32_b64 s1, exec                                    ; be81107e
	s_ff1_i32_b64 s10, exec                                     ; be8a147e
	s_lshl_b64 s[10:11], 1, s10                                 ; 8f8a0a81
	s_and_saveexec_b64 s[10:11], s[10:11]                       ; be8a240a
	s_cbranch_execz BB7                                         ; bf880004
BB2:
	v_mov_b32_e32 v0, s1                                        ; 7e000201
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_atomic_add v0, off, s[4:7], 0 glc                    ; e0c84000 80010080
BB7:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[10:11]                                    ; befe040a
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_readfirstlane_b32 s1, v0                                  ; 7e020500
	v_mbcnt_lo_u32_b32 v0, exec_lo, 0                           ; d7650000 0001007e
	v_mbcnt_hi_u32_b32 v0, exec_hi, v0                          ; d7660000 0002007f
	v_add_nc_u32_e32 v0, s1, v0                                 ; 4a000001
BB12:
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_load_dwordx4 s[4:7], s[2:3], 0x20                         ; f4080101 fa000020
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s1, s[4:7], 0x88                        ; f4200042 fa000088
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_u32_e32 s1, v0                                    ; 7da80001
	s_cbranch_execz BB13                                        ; bf88001f
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x40                         ; f4080101 fa000040
	v_mov_b32_e32 v1, v0                                        ; 7e020300
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_atomic_swap v1, v3, s[8:15] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm glc a16 ; f03c3108 40020103
	s_mov_b32 m0, s0                                            ; befc0300
	v_lshlrev_b32_e32 v0, 4, v0                                 ; 34000084
	v_interp_mov_f32_e32 v9, p0, attr0.w                        ; c8260302
	v_interp_mov_f32_e32 v3, p0, attr0.x                        ; c80e0002
	v_interp_mov_f32_e32 v7, p0, attr0.y                        ; c81e0102
	v_interp_mov_f32_e32 v8, p0, attr0.z                        ; c8220202
	v_cvt_u32_f32_e32 v5, v3                                    ; 7e0a0f03
	v_mov_b32_e32 v3, v2                                        ; 7e060302
	v_cvt_u32_f32_sdwa v5, v7 dst_sel:BYTE_1 dst_unused:UNUSED_PRESERVE src0_sel:DWORD ; 7e0a0ef9 00061107
	v_cvt_u32_f32_sdwa v5, v8 dst_sel:BYTE_2 dst_unused:UNUSED_PRESERVE src0_sel:DWORD ; 7e0a0ef9 00061208
	v_cvt_u32_f32_sdwa v5, v9 dst_sel:BYTE_3 dst_unused:UNUSED_PRESERVE src0_sel:DWORD ; 7e0a0ef9 00061309
	v_pack_b32_f16 v2, v5, v5 op_sel:[0,1,0]                    ; d7111002 00020b05
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	buffer_store_dwordx3 v[1:3], v0, s[4:7], 0 offen            ; e07c1000 80010100
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
BB13:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
