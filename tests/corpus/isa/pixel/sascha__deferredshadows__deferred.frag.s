# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x6                                                ; bfa10006
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_load_dwordx8 s[16:23], s[2:3], 0x80                       ; f40c0401 fa000080
	s_load_dwordx4 s[24:27], s[2:3], 0xd0                       ; f4080601 fa0000d0
	s_load_dwordx8 s[32:39], s[2:3], 0xe0                       ; f40c0801 fa0000e0
	s_load_dwordx4 s[28:31], s[2:3], 0x130                      ; f4080701 fa000130
	s_load_dwordx4 s[40:43], s[2:3], null                       ; f4080a01 fa000000
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[3:5], [v0, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220300 00000002
	image_sample  v[6:8], [v0, v2], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00c40600 00000002
	image_sample  v[12:15], [v0, v2], s[32:39], s[28:31] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00e80c00 00000002
	s_buffer_load_dword s1, s[40:43], 0x164                     ; f4200054 fa000164
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_lt_i32 0, s1                                          ; bf040180
	s_cbranch_scc0 BB149                                        ; bf8402e5
BB1:
	s_cmp_eq_i32 s1, 1                                          ; bf008101
	s_cbranch_scc0 BB148                                        ; bf8402cb
BB2:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_load_dwordx8 s[8:15], s[2:3], 0x140                       ; f40c0201 fa000140
	s_buffer_load_dwordx16 s[16:31], s[40:43], 0x40             ; f4300414 fa000040
	s_bfm_b32 s0, 8, 22                                         ; 92009688
	s_waitcnt vmcnt(2) lgkmcnt(0)                               ; bf8c0072
	v_mad_f32 v0, s24, v5, s28                                  ; d5410000 00720a18
	v_mad_f32 v1, s25, v5, s29                                  ; d5410001 00760a19
	v_mad_f32 v2, s26, v5, s30                                  ; d5410002 007a0a1a
	v_mad_f32 v9, s27, v5, s31                                  ; d5410009 007e0a1b
	v_mac_f32_e32 v0, s20, v4                                   ; 3e000814
	v_mac_f32_e32 v1, s21, v4                                   ; 3e020815
	v_mac_f32_e32 v2, s22, v4                                   ; 3e040816
	v_mac_f32_e32 v9, s23, v4                                   ; 3e120817
	v_mad_f32 v0, s16, v3, v0 div:2                             ; d5410000 1c020610
	v_mad_f32 v1, s17, v3, v1 div:2                             ; d5410001 1c060611
	v_mac_f32_e32 v2, s18, v3                                   ; 3e040612
	v_mac_f32_e32 v9, s19, v3                                   ; 3e120613
	v_rcp_f32_e32 v10, v9                                       ; 7e145509
	v_mul_f32_e32 v2, v2, v10                                   ; 10041502
	v_mul_f32_e32 v9, v9, v10                                   ; 10121509
	v_mad_f32 v16, v0, v10, 0.5                                 ; d5410010 03c21500
	v_mad_f32 v20, v1, v10, 0.5                                 ; d5410014 03c21501
	v_cmp_lt_f32_e32 vcc, -1.0, v2                              ; 7c0204f3
	v_cmp_gt_f32_e64 s[4:5], 1.0, v2                            ; d4040004 000204f2
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	s_bfe_u32 s6, s9, 0x2001e                                   ; 9386ff09 0002001e
	s_add_u32 s6, s6, 1                                         ; 80068106
	s_and_b32 s7, s10, 0x3fff                                   ; 8707ff0a 00003fff
	s_lshl2_add_u32 s7, s7, s6                                  ; 97870607
	s_bfe_u32 s19, s11, 0x4000c                                 ; 9393ff0b 0004000c
	s_lshr_b32 s7, s7, s19                                      ; 90071307
	s_bfe_u32 s18, s10, 0x10000e                                ; 9392ff0a 0010000e
	s_add_u32 s18, s18, 1                                       ; 80128112
	s_lshr_b32 s18, s18, s19                                    ; 90121312
	s_max_u32 s7, s7, 1                                         ; 84878107
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_cselect_b32 s7, 0, s7                                     ; 85070780
	s_max_u32 s18, s18, 1                                       ; 84928112
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	v_cvt_f32_i32_e32 v22, s7                                   ; 7e2c0a07
	s_cselect_b32 s18, 0, s18                                   ; 85121280
	v_cvt_f32_i32_e32 v23, s18                                  ; 7e2e0a12
	v_rcp_f32_e32 v22, v22                                      ; 7e2c5516
	v_rcp_f32_e32 v23, v23                                      ; 7e2e5517
	s_and_saveexec_b64 s[6:7], s[4:5]                           ; be862404
	s_cbranch_execz BB6                                         ; bf88001c
BB3:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v22, v16                                ; d5410011 44422c00
	v_mov_b32_e32 v19, 0                                        ; 7e260280
	v_mad_f32 v18, s0, -v23, v20                                ; d5410012 44522e00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v18, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821211
	image_sample  v17, [v17, v20, v19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00821111 00001314
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cmp_lt_f32_e64 s[16:17], v18, v2                          ; d4010010 00020512
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v21, 1.0, 0x3e800000, s[16:17]            ; d5010015 0041fef2 3e800000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB6:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
	v_mov_b32_e32 v21, 1.0                                      ; 7e2a02f2
BB8:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v21, v21, v0                                  ; 062a0115
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB12                                        ; bf880012
BB9:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v22, v16                                ; d5410011 44422c00
	v_mad_f32 v18, s0, v23, v20                                 ; d5410012 04522e00
	v_mov_b32_e32 v19, 0                                        ; 7e260280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821111
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB12:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB14:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v21, v21, v0                                  ; 062a0115
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB18                                        ; bf880010
BB15:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v23, v20                                ; d5410011 44522e00
	v_mov_b32_e32 v18, 0                                        ; 7e240280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[16:18], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821110
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB18:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB20:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v21, v21, v0                                  ; 062a0115
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB24                                        ; bf88000f
BB21:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v16, v20, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820010 00000014
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v2                           ; d4010010 00020500
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v1, 1.0, 0x3e800000, s[16:17]             ; d5010001 0041fef2 3e800000
BB24:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v1, 1.0                                       ; 7e0202f2
BB26:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v21, v21, v1                                  ; 062a0315
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB30                                        ; bf880010
BB27:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, v23, v20                                 ; d5410011 04522e00
	v_mov_b32_e32 v18, 0                                        ; 7e240280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[16:18], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821110
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB30:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB32:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v21, v21, v0                                  ; 062a0115
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB36                                        ; bf880012
BB33:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, v22, v16                                 ; d5410011 04422c00
	v_mad_f32 v18, s0, -v23, v20                                ; d5410012 44522e00
	v_mov_b32_e32 v19, 0                                        ; 7e260280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821111
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB36:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB38:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v21, v21, v0                                  ; 062a0115
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB42                                        ; bf880011
BB39:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v0, s0, v22, v16                                  ; d5410000 04422c00
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v20, v1], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820000 00000114
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v2                           ; d4010010 00020500
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v10, 1.0, 0x3e800000, s[16:17]            ; d501000a 0041fef2 3e800000
BB42:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v10, 1.0                                      ; 7e1402f2
BB44:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v21, v21, v10                                 ; 062a1515
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB48                                        ; bf880011
BB45:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mac_f32_e32 v16, s0, v22                                  ; 3e202c00
	v_mac_f32_e32 v20, s0, v23                                  ; 3e282e00
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v16, [v16, v20, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00821010 00000014
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[4:5], v16, v2                            ; d4010004 00020510
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	v_cndmask_b32_e64 v1, 1.0, 0x3e800000, s[4:5]               ; d5010001 0011fef2 3e800000
BB48:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v1, 1.0                                       ; 7e0202f2
BB50:
	s_buffer_load_dwordx16 s[16:31], s[40:43], 0xb0             ; f4300414 fa0000b0
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v21, v21, v1                                  ; 062a0315
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v0, s24, v5, s28                                  ; d5410000 00720a18
	v_mad_f32 v1, s25, v5, s29                                  ; d5410001 00760a19
	v_mad_f32 v2, s26, v5, s30                                  ; d5410002 007a0a1a
	v_mad_f32 v9, s27, v5, s31                                  ; d5410009 007e0a1b
	v_mac_f32_e32 v0, s20, v4                                   ; 3e000814
	v_mac_f32_e32 v1, s21, v4                                   ; 3e020815
	v_mac_f32_e32 v2, s22, v4                                   ; 3e040816
	v_mac_f32_e32 v9, s23, v4                                   ; 3e120817
	v_mad_f32 v0, s16, v3, v0 div:2                             ; d5410000 1c020610
	v_mad_f32 v1, s17, v3, v1 div:2                             ; d5410001 1c060611
	v_mac_f32_e32 v2, s18, v3                                   ; 3e040612
	v_mac_f32_e32 v9, s19, v3                                   ; 3e120613
	v_rcp_f32_e32 v10, v9                                       ; 7e145509
	v_mul_f32_e32 v9, v9, v10                                   ; 10121509
	v_mul_f32_e32 v2, v2, v10                                   ; 10041502
	v_mad_f32 v16, v0, v10, 0.5                                 ; d5410010 03c21500
	v_mad_f32 v1, v1, v10, 0.5                                  ; d5410001 03c21501
	v_cmp_lt_f32_e32 vcc, -1.0, v2                              ; 7c0204f3
	v_cmp_gt_f32_e64 s[4:5], 1.0, v2                            ; d4040004 000204f2
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB54                                        ; bf88001c
BB51:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v22, v16                                ; d5410011 44422c00
	v_mad_f32 v18, s0, -v23, v1                                 ; d5410012 44062e00
	v_mov_b32_e32 v19, 1.0                                      ; 7e2602f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v18, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821211
	image_sample  v17, [v17, v1, v19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00821111 00001301
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cmp_lt_f32_e64 s[16:17], v18, v2                          ; d4010010 00020512
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v20, 1.0, 0x3e800000, s[16:17]            ; d5010014 0041fef2 3e800000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB54:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
	v_mov_b32_e32 v20, 1.0                                      ; 7e2802f2
BB56:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB60                                        ; bf880012
BB57:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v22, v16                                ; d5410011 44422c00
	v_mad_f32 v18, s0, v23, v1                                  ; d5410012 04062e00
	v_mov_b32_e32 v19, 1.0                                      ; 7e2602f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821111
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB60:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB62:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB66                                        ; bf880010
BB63:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v23, v1                                 ; d5410011 44062e00
	v_mov_b32_e32 v18, 1.0                                      ; 7e2402f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[16:18], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821110
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB66:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB68:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB72                                        ; bf88000f
BB69:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v16, v1, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820010 00000001
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v2                           ; d4010010 00020500
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v10, 1.0, 0x3e800000, s[16:17]            ; d501000a 0041fef2 3e800000
BB72:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v10, 1.0                                      ; 7e1402f2
BB74:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v10                                 ; 06281514
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB78                                        ; bf880010
BB75:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, v23, v1                                  ; d5410011 04062e00
	v_mov_b32_e32 v18, 1.0                                      ; 7e2402f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[16:18], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821110
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB78:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB80:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB84                                        ; bf880012
BB81:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, v22, v16                                 ; d5410011 04422c00
	v_mad_f32 v18, s0, -v23, v1                                 ; d5410012 44062e00
	v_mov_b32_e32 v19, 1.0                                      ; 7e2602f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821111
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB84:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB86:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB90                                        ; bf880011
BB87:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v0, s0, v22, v16                                  ; d5410000 04422c00
	v_mov_b32_e32 v10, 1.0                                      ; 7e1402f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v1, v10], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820000 00000a01
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v2                           ; d4010010 00020500
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v11, 1.0, 0x3e800000, s[16:17]            ; d501000b 0041fef2 3e800000
BB90:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v11, 1.0                                      ; 7e1602f2
BB92:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v11                                 ; 06281714
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB96                                        ; bf880011
BB93:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mac_f32_e32 v16, s0, v22                                  ; 3e202c00
	v_mac_f32_e32 v1, s0, v23                                   ; 3e022e00
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v16, [v16, v1, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00821010 00000001
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[4:5], v16, v2                            ; d4010004 00020510
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	v_cndmask_b32_e64 v1, 1.0, 0x3e800000, s[4:5]               ; d5010001 0011fef2 3e800000
BB96:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v1, 1.0                                       ; 7e0202f2
BB98:
	s_buffer_load_dwordx16 s[16:31], s[40:43], 0x120            ; f4300414 fa000120
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_mul_f32_e32 v21, 0x3de38e39, v21                          ; 102a2aff 3de38e39
	v_add_f32_e32 v20, v20, v1                                  ; 06280314
	v_mul_f32_e32 v20, 0x3de38e39, v20                          ; 102828ff 3de38e39
	v_mul_f32_e32 v21, v21, v20                                 ; 102a2915
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v0, s24, v5, s28                                  ; d5410000 00720a18
	v_mad_f32 v1, s25, v5, s29                                  ; d5410001 00760a19
	v_mad_f32 v2, s26, v5, s30                                  ; d5410002 007a0a1a
	v_mad_f32 v9, s27, v5, s31                                  ; d5410009 007e0a1b
	v_mac_f32_e32 v0, s20, v4                                   ; 3e000814
	v_mac_f32_e32 v1, s21, v4                                   ; 3e020815
	v_mac_f32_e32 v2, s22, v4                                   ; 3e040816
	v_mac_f32_e32 v9, s23, v4                                   ; 3e120817
	v_mad_f32 v0, s16, v3, v0 div:2                             ; d5410000 1c020610
	v_mad_f32 v1, s17, v3, v1 div:2                             ; d5410001 1c060611
	v_mac_f32_e32 v2, s18, v3                                   ; 3e040612
	v_mac_f32_e32 v9, s19, v3                                   ; 3e120613
	v_rcp_f32_e32 v10, v9                                       ; 7e145509
	v_mul_f32_e32 v2, v2, v10                                   ; 10041502
	v_mul_f32_e32 v9, v9, v10                                   ; 10121509
	v_mad_f32 v16, v0, v10, 0.5                                 ; d5410010 03c21500
	v_mad_f32 v1, v1, v10, 0.5                                  ; d5410001 03c21501
	v_cmp_lt_f32_e32 vcc, -1.0, v2                              ; 7c0204f3
	v_cmp_gt_f32_e64 s[4:5], 1.0, v2                            ; d4040004 000204f2
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB102                                       ; bf88001c
BB99:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v22, v16                                ; d5410011 44422c00
	v_mad_f32 v18, s0, -v23, v1                                 ; d5410012 44062e00
	v_mov_b32_e32 v19, 2.0                                      ; 7e2602f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v18, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821211
	image_sample  v17, [v17, v1, v19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00821111 00001301
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cmp_lt_f32_e64 s[16:17], v18, v2                          ; d4010010 00020512
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v20, 1.0, 0x3e800000, s[16:17]            ; d5010014 0041fef2 3e800000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB102:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
	v_mov_b32_e32 v20, 1.0                                      ; 7e2802f2
BB104:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB108                                       ; bf880012
BB105:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v22, v16                                ; d5410011 44422c00
	v_mad_f32 v18, s0, v23, v1                                  ; d5410012 04062e00
	v_mov_b32_e32 v19, 2.0                                      ; 7e2602f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821111
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB108:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB110:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB114                                       ; bf880010
BB111:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, -v23, v1                                 ; d5410011 44062e00
	v_mov_b32_e32 v18, 2.0                                      ; 7e2402f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[16:18], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821110
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB114:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB116:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB120                                       ; bf88000f
BB117:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mov_b32_e32 v0, 2.0                                       ; 7e0002f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v16, v1, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820010 00000001
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v2                           ; d4010010 00020500
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v10, 1.0, 0x3e800000, s[16:17]            ; d501000a 0041fef2 3e800000
BB120:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v10, 1.0                                      ; 7e1402f2
BB122:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v10                                 ; 06281514
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB126                                       ; bf880010
BB123:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, v23, v1                                  ; d5410011 04062e00
	v_mov_b32_e32 v18, 2.0                                      ; 7e2402f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[16:18], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821110
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB126:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB128:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB132                                       ; bf880012
BB129:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v17, s0, v22, v16                                 ; d5410011 04422c00
	v_mad_f32 v18, s0, -v23, v1                                 ; d5410012 44062e00
	v_mov_b32_e32 v19, 2.0                                      ; 7e2602f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v17, v[17:19], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00821111
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v17, v2                          ; d4010010 00020511
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB132:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB134:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB138                                       ; bf880011
BB135:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v0, s0, v22, v16                                  ; d5410000 04422c00
	v_mov_b32_e32 v10, 2.0                                      ; 7e1402f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v1, v10], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820000 00000a01
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v2                           ; d4010010 00020500
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v11, 1.0, 0x3e800000, s[16:17]            ; d501000b 0041fef2 3e800000
BB138:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v11, 1.0                                      ; 7e1602f2
BB140:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v11                                 ; 06281714
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB144                                       ; bf880011
BB141:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mac_f32_e32 v16, s0, v22                                  ; 3e202c00
	v_mac_f32_e32 v1, s0, v23                                   ; 3e022e00
	v_mov_b32_e32 v0, 2.0                                       ; 7e0002f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v16, [v16, v1, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00821010 00000001
	v_cmp_lt_f32_e32 vcc, 0, v9                                 ; 7c021280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[2:3], v16, v2                            ; d4010002 00020510
	s_and_b64 s[2:3], vcc, s[2:3]                               ; 8782026a
	v_cndmask_b32_e64 v1, 1.0, 0x3e800000, s[2:3]               ; d5010001 0009fef2 3e800000
BB144:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v1, 1.0                                       ; 7e0202f2
BB146:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v20, v20, v1                                  ; 06280314
	v_mul_f32_e32 v20, 0x3de38e39, v20                          ; 102828ff 3de38e39
	v_mul_f32_e32 v21, v21, v20                                 ; 102a2915
	v_mov_b32_e32 v0, v21                                       ; 7e000315
	v_mov_b32_e32 v1, v21                                       ; 7e020315
BB148:
	s_cmp_eq_i32 s1, 2                                          ; bf008201
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_eq_i32 s1, 3                                          ; bf008301
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_cndmask_b32_e32 v1, v1, v3, vcc                           ; 02020701
	v_cndmask_b32_e32 v0, v0, v4, vcc                           ; 02000900
	v_cndmask_b32_e32 v21, v21, v5, vcc                         ; 022a0b15
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_eq_i32 s1, 4                                          ; bf008401
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cndmask_b32_e32 v1, v1, v6, vcc                           ; 02020d01
	v_cndmask_b32_e32 v0, v0, v7, vcc                           ; 02000f00
	v_cndmask_b32_e32 v21, v21, v8, vcc                         ; 022a1115
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_eq_i32 s1, 5                                          ; bf008501
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v1, v1, v12, vcc                          ; 02021901
	v_cndmask_b32_e32 v0, v0, v13, vcc                          ; 02001b00
	v_cndmask_b32_e32 v21, v21, v14, vcc                        ; 022a1d15
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v1, v1, v15, vcc                          ; 02021f01
	v_cndmask_b32_e32 v0, v0, v15, vcc                          ; 02001f00
	v_cndmask_b32_e32 v21, v21, v15, vcc                        ; 022a1f15
	s_branch BB297                                              ; bf8203dd
BB149:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[16:31], s[40:43], null             ; f4300414 fa000000
	s_buffer_load_dwordx8 s[8:15], s[40:43], 0x80               ; f42c0214 fa000080
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v0, v7, v7                                    ; 10000f07
	v_mac_f32_e32 v0, v8, v8                                    ; 3e001108
	v_mac_f32_e32 v0, v6, v6                                    ; 3e000d06
	v_rsq_f32_e32 v0, v0                                        ; 7e005d00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e32 v16, s16, v3                                  ; 08200610
	v_sub_f32_e32 v17, s17, v4                                  ; 08220811
	v_sub_f32_e32 v18, s18, v5                                  ; 08240a12
	v_sub_f32_e32 v1, s20, v3                                   ; 08020614
	v_sub_f32_e32 v2, s21, v4                                   ; 08040815
	v_sub_f32_e32 v9, s22, v5                                   ; 08120a16
	v_mul_f32_e32 v6, v6, v0                                    ; 100c0106
	v_mul_f32_e32 v7, v7, v0                                    ; 100e0107
	v_mul_f32_e32 v8, v8, v0                                    ; 10100108
	v_mul_f32_e32 v19, v17, v17                                 ; 10262311
	v_sub_f32_e64 v20, s20, s24                                 ; d5040014 00003014
	v_sub_f32_e64 v21, s21, s25                                 ; d5040015 00003215
	v_sub_f32_e64 v22, s22, s26                                 ; d5040016 00003416
	v_mul_f32_e32 v10, v2, v2                                   ; 10140502
	v_mac_f32_e32 v19, v18, v18                                 ; 3e262512
	v_mul_f32_e32 v23, v21, v21                                 ; 102e2b15
	v_mac_f32_e32 v10, v9, v9                                   ; 3e141309
	v_mac_f32_e32 v19, v16, v16                                 ; 3e262110
	v_mac_f32_e32 v23, v22, v22                                 ; 3e2e2d16
	v_mac_f32_e32 v10, v1, v1                                   ; 3e140301
	v_rsq_f32_e32 v19, v19                                      ; 7e265d13
	v_mac_f32_e32 v23, v20, v20                                 ; 3e2e2914
	v_rsq_f32_e32 v11, v10                                      ; 7e165d0a
	v_rsq_f32_e32 v23, v23                                      ; 7e2e5d17
	v_mul_f32_e32 v18, v18, v19                                 ; 10242712
	v_mul_f32_e32 v16, v16, v19                                 ; 10202710
	v_mul_f32_e32 v17, v17, v19                                 ; 10222711
	v_sqrt_f32_e32 v10, v10                                     ; 7e14670a
	v_mul_f32_e32 v1, v1, v11                                   ; 10021701
	v_mul_f32_e32 v9, v9, v11                                   ; 10121709
	v_mul_f32_e32 v2, v2, v11                                   ; 10041702
	v_mul_f32_e32 v20, v20, v23                                 ; 10282f14
	v_mul_f32_e32 v21, v21, v23                                 ; 102a2f15
	v_mul_f32_e32 v22, v22, v23                                 ; 102c2f16
	v_add_f32_e32 v10, 0xc2c80000, v10                          ; 061414ff c2c80000
	v_madak_f32 v22, v9, v22, 0xbf6803ca                        ; 422c2d09 bf6803ca
	v_mul_f32_e64 v10, 0xbc23d70a, v10 clamp                    ; d508800a 000214ff bc23d70a
	v_mac_f32_e32 v22, v2, v21                                  ; 3e2c2b02
	v_mac_f32_e32 v22, v1, v20                                  ; 3e2c2901
	v_mul_f32_e64 v22, 0x4186300b, v22 clamp                    ; d5088016 00022cff 4186300b
	v_madak_f32 v23, -2.0, v22, 0x40400000                      ; 422e2cf5 40400000
	v_mul_f32_e32 v23, v22, v23                                 ; 102e2f16
	v_mul_f32_e32 v22, v22, v23                                 ; 102c2f16
	v_madak_f32 v23, -2.0, v10, 0x40400000                      ; 422e14f5 40400000
	v_mul_f32_e32 v23, v10, v23                                 ; 102e2f0a
	v_mul_f32_e32 v10, v10, v23                                 ; 10142f0a
	v_mul_f32_e32 v23, v8, v9                                   ; 102e1308
	v_mad_f32 v0, v7, v2, v23                                   ; d5410000 045e0507
	v_mad_f32 v23, v7, -v2, -v23                                ; d5410017 c45e0507
	v_mac_f32_e32 v0, v6, v1                                    ; 3e000306
	v_mad_f32 v23, v6, -v1, v23 mul:2                           ; d5410017 4c5e0306
	v_max_f32_e32 v0, 0, v0                                     ; 20000080
	v_mad_f32 v1, v6, -v23, -v1                                 ; d5410001 c4062f06
	v_mad_f32 v2, v7, -v23, -v2                                 ; d5410002 c40a2f07
	v_mad_f32 v23, v8, -v23, -v9                                ; d5410017 c4262f08
	v_sub_f32_e32 v9, s10, v5                                   ; 08120a0a
	v_mul_f32_e32 v23, v23, v18                                 ; 102e2517
	v_mac_f32_e32 v23, v2, v17                                  ; 3e2e2302
	v_sub_f32_e32 v2, s9, v4                                    ; 08040809
	v_mac_f32_e32 v23, v1, v16                                  ; 3e2e2101
	v_sub_f32_e32 v1, s8, v3                                    ; 08020608
	v_sub_f32_e64 v19, s8, s12                                  ; d5040013 00001808
	v_sub_f32_e64 v20, s9, s13                                  ; d5040014 00001a09
	v_sub_f32_e64 v21, s10, s14                                 ; d5040015 00001c0a
	v_max_f32_e32 v23, 0, v23                                   ; 202e2e80
	v_log_f32_e32 v23, v23                                      ; 7e2e4f17
	v_mul_f32_e32 v23, 0x41800000, v23                          ; 102e2eff 41800000
	v_exp_f32_e32 v23, v23                                      ; 7e2e4b17
	v_mul_f32_e32 v23, 0x40200000, v23                          ; 102e2eff 40200000
	s_buffer_load_dwordx4 s[4:7], s[40:43], 0xa0                ; f4280114 fa0000a0
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v0, v23, v15                                  ; 3e001f17
	v_mul_f32_e32 v0, v0, v22                                   ; 10002d00
	v_mul_f32_e32 v22, v20, v20                                 ; 102c2914
	v_mul_f32_e32 v0, v0, v10                                   ; 10001500
	v_mul_f32_e32 v10, v2, v2                                   ; 10140502
	v_mac_f32_e32 v22, v21, v21                                 ; 3e2c2b15
	v_mac_f32_e32 v10, v9, v9                                   ; 3e141309
	s_buffer_load_dwordx8 s[8:15], s[40:43], 0xf0               ; f42c0214 fa0000f0
	v_mac_f32_e32 v22, v19, v19                                 ; 3e2c2713
	v_mac_f32_e32 v10, v1, v1                                   ; 3e140301
	v_rsq_f32_e32 v22, v22                                      ; 7e2c5d16
	v_rsq_f32_e32 v11, v10                                      ; 7e165d0a
	v_sqrt_f32_e32 v10, v10                                     ; 7e14670a
	v_mul_f32_e32 v20, v20, v22                                 ; 10282d14
	v_mul_f32_e32 v19, v19, v22                                 ; 10262d13
	v_mul_f32_e32 v21, v21, v22                                 ; 102a2d15
	v_mul_f32_e32 v2, v2, v11                                   ; 10041702
	v_mul_f32_e32 v9, v9, v11                                   ; 10121709
	v_mul_f32_e32 v1, v1, v11                                   ; 10021701
	v_add_f32_e32 v10, 0xc2c80000, v10                          ; 061414ff c2c80000
	v_madak_f32 v21, v9, v21, 0xbf6803ca                        ; 422a2b09 bf6803ca
	v_mul_f32_e64 v10, 0xbc23d70a, v10 clamp                    ; d508800a 000214ff bc23d70a
	v_mac_f32_e32 v21, v2, v20                                  ; 3e2a2902
	v_mac_f32_e32 v21, v1, v19                                  ; 3e2a2701
	v_mul_f32_e64 v21, 0x4186300b, v21 clamp                    ; d5088015 00022aff 4186300b
	v_madak_f32 v23, -2.0, v21, 0x40400000                      ; 422e2af5 40400000
	v_mul_f32_e32 v23, v21, v23                                 ; 102e2f15
	v_mul_f32_e32 v21, v21, v23                                 ; 102a2f15
	v_madak_f32 v23, -2.0, v10, 0x40400000                      ; 422e14f5 40400000
	v_mul_f32_e32 v23, v10, v23                                 ; 102e2f0a
	v_mul_f32_e32 v10, v10, v23                                 ; 10142f0a
	v_mul_f32_e32 v23, v8, v9                                   ; 102e1308
	v_mad_f32 v11, v7, v2, v23                                  ; d541000b 045e0507
	v_mad_f32 v23, v7, -v2, -v23                                ; d5410017 c45e0507
	v_mac_f32_e32 v11, v6, v1                                   ; 3e160306
	v_mad_f32 v23, v6, -v1, v23 mul:2                           ; d5410017 4c5e0306
	v_madak_f32 v19, s28, v0, 0x3dcccccd                        ; 4226001c 3dcccccd
	v_max_f32_e32 v11, 0, v11                                   ; 20161680
	v_madak_f32 v20, s29, v0, 0x3dcccccd                        ; 4228001d 3dcccccd
	v_mad_f32 v1, v6, -v23, -v1                                 ; d5410001 c4062f06
	v_mad_f32 v2, v7, -v23, -v2                                 ; d5410002 c40a2f07
	v_mad_f32 v23, v8, -v23, -v9                                ; d5410017 c4262f08
	v_madak_f32 v0, s30, v0, 0x3dcccccd                         ; 4200001e 3dcccccd
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e32 v22, s9, v4                                   ; 082c0809
	v_mul_f32_e32 v23, v23, v18                                 ; 102e2517
	v_mac_f32_e32 v23, v2, v17                                  ; 3e2e2302
	v_mac_f32_e32 v23, v1, v16                                  ; 3e2e2101
	v_mul_f32_e32 v1, v22, v22                                  ; 10022d16
	v_max_f32_e32 v23, 0, v23                                   ; 202e2e80
	v_log_f32_e32 v23, v23                                      ; 7e2e4f17
	v_mul_f32_e32 v23, 0x41800000, v23                          ; 102e2eff 41800000
	v_exp_f32_e32 v23, v23                                      ; 7e2e4b17
	v_sub_f32_e64 v9, s8, s12                                   ; d5040009 00001808
	v_mul_f32_e32 v23, 0x40200000, v23                          ; 102e2eff 40200000
	v_mac_f32_e32 v11, v23, v15                                 ; 3e161f17
	v_sub_f32_e32 v23, s10, v5                                  ; 082e0a0a
	v_mul_f32_e32 v11, v11, v21                                 ; 10162b0b
	v_sub_f32_e32 v21, s8, v3                                   ; 082a0608
	v_mac_f32_e32 v1, v23, v23                                  ; 3e022f17
	v_mul_f32_e32 v11, v11, v10                                 ; 1016150b
	v_mac_f32_e32 v20, s5, v11                                  ; 3e281605
	v_mac_f32_e32 v19, s4, v11                                  ; 3e261604
	v_mac_f32_e32 v0, s6, v11                                   ; 3e001606
	s_buffer_load_dwordx4 s[4:7], s[40:43], 0x110               ; f4280114 fa000110
	v_sub_f32_e64 v10, s9, s13                                  ; d504000a 00001a09
	v_sub_f32_e64 v11, s10, s14                                 ; d504000b 00001c0a
	v_mac_f32_e32 v1, v21, v21                                  ; 3e022b15
	v_rsq_f32_e32 v2, v1                                        ; 7e045d01
	s_buffer_load_dword s0, s[40:43], 0x160                     ; f4200014 fa000160
	v_mul_f32_e32 v23, v23, v2                                  ; 102e0517
	v_mul_f32_e32 v22, v22, v2                                  ; 102c0516
	v_mul_f32_e32 v21, v21, v2                                  ; 102a0515
	v_mul_f32_e32 v2, v10, v10                                  ; 1004150a
	v_sqrt_f32_e32 v1, v1                                       ; 7e026701
	v_mac_f32_e32 v2, v11, v11                                  ; 3e04170b
	v_mac_f32_e32 v2, v9, v9                                    ; 3e041309
	v_add_f32_e32 v1, 0xc2c80000, v1                            ; 060202ff c2c80000
	v_rsq_f32_e32 v2, v2                                        ; 7e045d02
	v_mul_f32_e64 v1, 0xbc23d70a, v1 clamp                      ; d5088001 000202ff bc23d70a
	v_mul_f32_e32 v9, v9, v2                                    ; 10120509
	v_mul_f32_e32 v10, v10, v2                                  ; 1014050a
	v_mul_f32_e32 v11, v11, v2                                  ; 1016050b
	v_mul_f32_e32 v2, v8, v23                                   ; 10042f08
	v_madak_f32 v11, v23, v11, 0xbf6803ca                       ; 42161717 bf6803ca
	v_mac_f32_e32 v11, v22, v10                                 ; 3e161516
	v_madak_f32 v10, -2.0, v1, 0x40400000                       ; 421402f5 40400000
	v_mac_f32_e32 v11, v21, v9                                  ; 3e161315
	v_mul_f32_e32 v10, v1, v10                                  ; 10141501
	v_mul_f32_e64 v11, 0x4186300b, v11 clamp                    ; d508800b 000216ff 4186300b
	v_mul_f32_e32 v1, v1, v10                                   ; 10021501
	v_madak_f32 v9, -2.0, v11, 0x40400000                       ; 421216f5 40400000
	v_mul_f32_e32 v9, v11, v9                                   ; 1012130b
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mad_f32 v9, v7, v22, v2                                   ; d5410009 040a2d07
	v_mad_f32 v2, v7, -v22, -v2                                 ; d5410002 c40a2d07
	v_mac_f32_e32 v9, v6, v21                                   ; 3e122b06
	v_mad_f32 v2, v6, -v21, v2 mul:2                            ; d5410002 4c0a2b06
	v_max_f32_e32 v9, 0, v9                                     ; 20121280
	v_mad_f32 v6, v6, -v2, -v21                                 ; d5410006 c4560506
	v_mad_f32 v8, v8, -v2, -v23                                 ; d5410008 c45e0508
	v_mad_f32 v7, v7, -v2, -v22                                 ; d5410007 c45a0507
	v_mul_f32_e32 v8, v8, v18                                   ; 10102508
	v_mac_f32_e32 v8, v7, v17                                   ; 3e102307
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_lt_i32 0, s0                                          ; bf040080
	v_mac_f32_e32 v8, v6, v16                                   ; 3e102106
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_log_f32_e32 v8, v8                                        ; 7e104f08
	v_mul_f32_e32 v8, 0x41800000, v8                            ; 101010ff 41800000
	v_exp_f32_e32 v8, v8                                        ; 7e104b08
	v_mul_f32_e32 v8, 0x40200000, v8                            ; 101010ff 40200000
	v_mac_f32_e32 v9, v8, v15                                   ; 3e121f08
	v_mul_f32_e32 v9, v9, v11                                   ; 10121709
	v_mul_f32_e32 v9, v9, v1                                    ; 10120309
	v_mac_f32_e32 v19, s4, v9                                   ; 3e261204
	v_mac_f32_e32 v20, s5, v9                                   ; 3e281205
	v_mac_f32_e32 v0, s6, v9                                    ; 3e001206
	v_mul_f32_e32 v1, v12, v19                                  ; 1002270c
	v_mul_f32_e32 v13, v13, v20                                 ; 101a290d
	v_mul_f32_e32 v21, v14, v0                                  ; 102a010e
	s_cbranch_scc0 BB295                                        ; bf8402cf
BB150:
	s_load_dwordx8 s[8:15], s[2:3], 0x140                       ; f40c0201 fa000140
	s_buffer_load_dwordx16 s[16:31], s[40:43], 0x40             ; f4300414 fa000040
	s_bfm_b32 s0, 8, 22                                         ; 92009688
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v0, s24, v5, s28                                  ; d5410000 00720a18
	v_mad_f32 v2, s25, v5, s29                                  ; d5410002 00760a19
	v_mad_f32 v6, s26, v5, s30                                  ; d5410006 007a0a1a
	v_mad_f32 v7, s27, v5, s31                                  ; d5410007 007e0a1b
	v_mac_f32_e32 v0, s20, v4                                   ; 3e000814
	v_mac_f32_e32 v2, s21, v4                                   ; 3e040815
	v_mac_f32_e32 v6, s22, v4                                   ; 3e0c0816
	v_mac_f32_e32 v7, s23, v4                                   ; 3e0e0817
	v_mad_f32 v0, s16, v3, v0 div:2                             ; d5410000 1c020610
	v_mad_f32 v2, s17, v3, v2 div:2                             ; d5410002 1c0a0611
	v_mac_f32_e32 v6, s18, v3                                   ; 3e0c0612
	v_mac_f32_e32 v7, s19, v3                                   ; 3e0e0613
	v_rcp_f32_e32 v8, v7                                        ; 7e105507
	v_mul_f32_e32 v6, v6, v8                                    ; 100c1106
	v_mul_f32_e32 v7, v7, v8                                    ; 100e1107
	v_mad_f32 v9, v0, v8, 0.5                                   ; d5410009 03c21100
	v_mad_f32 v15, v2, v8, 0.5                                  ; d541000f 03c21102
	v_cmp_lt_f32_e32 vcc, -1.0, v6                              ; 7c020cf3
	v_cmp_gt_f32_e64 s[4:5], 1.0, v6                            ; d4040004 00020cf2
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	s_bfe_u32 s1, s9, 0x2001e                                   ; 9381ff09 0002001e
	s_add_u32 s1, s1, 1                                         ; 80018101
	s_and_b32 s6, s10, 0x3fff                                   ; 8706ff0a 00003fff
	s_lshl2_add_u32 s6, s6, s1                                  ; 97860106
	s_bfe_u32 s19, s11, 0x4000c                                 ; 9393ff0b 0004000c
	s_lshr_b32 s6, s6, s19                                      ; 90061306
	s_bfe_u32 s18, s10, 0x10000e                                ; 9392ff0a 0010000e
	s_add_u32 s18, s18, 1                                       ; 80128112
	s_lshr_b32 s18, s18, s19                                    ; 90121312
	s_max_u32 s6, s6, 1                                         ; 84868106
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_cselect_b32 s6, 0, s6                                     ; 85060680
	s_max_u32 s18, s18, 1                                       ; 84928112
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	v_cvt_f32_i32_e32 v17, s6                                   ; 7e220a06
	s_cselect_b32 s18, 0, s18                                   ; 85121280
	v_cvt_f32_i32_e32 v18, s18                                  ; 7e240a12
	v_rcp_f32_e32 v17, v17                                      ; 7e225511
	v_rcp_f32_e32 v18, v18                                      ; 7e245512
	s_and_saveexec_b64 s[6:7], s[4:5]                           ; be862404
	s_cbranch_execz BB154                                       ; bf88001c
BB151:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, -v17, v9                                 ; d541000a 44262200
	v_mov_b32_e32 v12, 0                                        ; 7e180280
	v_mad_f32 v11, s0, -v18, v15                                ; d541000b 443e2400
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v11, v[10:12], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820b0a
	image_sample  v10, [v10, v15, v12], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820a0a 00000c0f
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cmp_lt_f32_e64 s[16:17], v11, v6                          ; d4010010 00020d0b
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v14, 1.0, 0x3e800000, s[16:17]            ; d501000e 0041fef2 3e800000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v16, 1.0, 0x3e800000, s[16:17]            ; d5010010 0041fef2 3e800000
BB154:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v14, 1.0                                      ; 7e1c02f2
	v_mov_b32_e32 v16, 1.0                                      ; 7e2002f2
BB156:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v16                                 ; 061c210e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB160                                       ; bf880012
BB157:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, -v17, v9                                 ; d541000a 44262200
	v_mad_f32 v11, s0, v18, v15                                 ; d541000b 043e2400
	v_mov_b32_e32 v12, 0                                        ; 7e180280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[10:12], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820a0a
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v16, 1.0, 0x3e800000, s[16:17]            ; d5010010 0041fef2 3e800000
BB160:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v16, 1.0                                      ; 7e2002f2
BB162:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v16                                 ; 061c210e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB166                                       ; bf880010
BB163:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, -v18, v15                                ; d541000a 443e2400
	v_mov_b32_e32 v11, 0                                        ; 7e160280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[9:11], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820a09
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB166:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB168:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v0                                  ; 061c010e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB172                                       ; bf88000f
BB169:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v9, v15, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820009 0000000f
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v6                           ; d4010010 00020d00
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v2, 1.0, 0x3e800000, s[16:17]             ; d5010002 0041fef2 3e800000
BB172:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
BB174:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v2                                  ; 061c050e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB178                                       ; bf880010
BB175:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, v18, v15                                 ; d541000a 043e2400
	v_mov_b32_e32 v11, 0                                        ; 7e160280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[9:11], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820a09
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB178:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB180:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v0                                  ; 061c010e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB184                                       ; bf880012
BB181:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, v17, v9                                  ; d541000a 04262200
	v_mad_f32 v11, s0, -v18, v15                                ; d541000b 443e2400
	v_mov_b32_e32 v12, 0                                        ; 7e180280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[10:12], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820a0a
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v16, 1.0, 0x3e800000, s[16:17]            ; d5010010 0041fef2 3e800000
BB184:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v16, 1.0                                      ; 7e2002f2
BB186:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v16                                 ; 061c210e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB190                                       ; bf880011
BB187:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v0, s0, v17, v9                                   ; d5410000 04262200
	v_mov_b32_e32 v2, 0                                         ; 7e040280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v15, v2], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820000 0000020f
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v6                           ; d4010010 00020d00
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v8, 1.0, 0x3e800000, s[16:17]             ; d5010008 0041fef2 3e800000
BB190:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v8, 1.0                                       ; 7e1002f2
BB192:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v8                                  ; 061c110e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB196                                       ; bf880011
BB193:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mac_f32_e32 v9, s0, v17                                   ; 3e122200
	v_mac_f32_e32 v15, s0, v18                                  ; 3e1e2400
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v9, [v9, v15, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820909 0000000f
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[4:5], v9, v6                             ; d4010004 00020d09
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	v_cndmask_b32_e64 v2, 1.0, 0x3e800000, s[4:5]               ; d5010002 0011fef2 3e800000
BB196:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
BB198:
	s_buffer_load_dwordx16 s[16:31], s[40:43], 0xb0             ; f4300414 fa0000b0
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v2                                  ; 061c050e
	v_mul_f32_e32 v14, 0x3de38e39, v14                          ; 101c1cff 3de38e39
	v_mul_f32_e32 v1, v1, v14                                   ; 10021d01
	v_mul_f32_e32 v13, v13, v14                                 ; 101a1d0d
	v_mul_f32_e32 v21, v21, v14                                 ; 102a1d15
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v0, s24, v5, s28                                  ; d5410000 00720a18
	v_mad_f32 v2, s25, v5, s29                                  ; d5410002 00760a19
	v_mad_f32 v6, s26, v5, s30                                  ; d5410006 007a0a1a
	v_mad_f32 v7, s27, v5, s31                                  ; d5410007 007e0a1b
	v_mac_f32_e32 v0, s20, v4                                   ; 3e000814
	v_mac_f32_e32 v2, s21, v4                                   ; 3e040815
	v_mac_f32_e32 v6, s22, v4                                   ; 3e0c0816
	v_mac_f32_e32 v7, s23, v4                                   ; 3e0e0817
	v_mad_f32 v0, s16, v3, v0 div:2                             ; d5410000 1c020610
	v_mad_f32 v2, s17, v3, v2 div:2                             ; d5410002 1c0a0611
	v_mac_f32_e32 v6, s18, v3                                   ; 3e0c0612
	v_mac_f32_e32 v7, s19, v3                                   ; 3e0e0613
	v_rcp_f32_e32 v8, v7                                        ; 7e105507
	v_mul_f32_e32 v6, v6, v8                                    ; 100c1106
	v_mul_f32_e32 v7, v7, v8                                    ; 100e1107
	v_mad_f32 v9, v0, v8, 0.5                                   ; d5410009 03c21100
	v_mad_f32 v15, v2, v8, 0.5                                  ; d541000f 03c21102
	v_cmp_lt_f32_e32 vcc, -1.0, v6                              ; 7c020cf3
	v_cmp_gt_f32_e64 s[4:5], 1.0, v6                            ; d4040004 00020cf2
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB202                                       ; bf88001c
BB199:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, -v17, v9                                 ; d541000a 44262200
	v_mad_f32 v11, s0, -v18, v15                                ; d541000b 443e2400
	v_mov_b32_e32 v12, 1.0                                      ; 7e1802f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v11, v[10:12], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820b0a
	image_sample  v10, [v10, v15, v12], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820a0a 00000c0f
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cmp_lt_f32_e64 s[16:17], v11, v6                          ; d4010010 00020d0b
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v14, 1.0, 0x3e800000, s[16:17]            ; d501000e 0041fef2 3e800000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v16, 1.0, 0x3e800000, s[16:17]            ; d5010010 0041fef2 3e800000
BB202:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v14, 1.0                                      ; 7e1c02f2
	v_mov_b32_e32 v16, 1.0                                      ; 7e2002f2
BB204:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v16                                 ; 061c210e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB208                                       ; bf880012
BB205:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, -v17, v9                                 ; d541000a 44262200
	v_mad_f32 v11, s0, v18, v15                                 ; d541000b 043e2400
	v_mov_b32_e32 v12, 1.0                                      ; 7e1802f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[10:12], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820a0a
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v16, 1.0, 0x3e800000, s[16:17]            ; d5010010 0041fef2 3e800000
BB208:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v16, 1.0                                      ; 7e2002f2
BB210:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v16                                 ; 061c210e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB214                                       ; bf880010
BB211:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, -v18, v15                                ; d541000a 443e2400
	v_mov_b32_e32 v11, 1.0                                      ; 7e1602f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[9:11], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820a09
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB214:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB216:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v0                                  ; 061c010e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB220                                       ; bf88000f
BB217:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v9, v15, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820009 0000000f
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v6                           ; d4010010 00020d00
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v2, 1.0, 0x3e800000, s[16:17]             ; d5010002 0041fef2 3e800000
BB220:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
BB222:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v2                                  ; 061c050e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB226                                       ; bf880010
BB223:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, v18, v15                                 ; d541000a 043e2400
	v_mov_b32_e32 v11, 1.0                                      ; 7e1602f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[9:11], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820a09
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB226:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB228:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v0                                  ; 061c010e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB232                                       ; bf880012
BB229:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v10, s0, v17, v9                                  ; d541000a 04262200
	v_mad_f32 v11, s0, -v18, v15                                ; d541000b 443e2400
	v_mov_b32_e32 v12, 1.0                                      ; 7e1802f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[10:12], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820a0a
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v10, v6                          ; d4010010 00020d0a
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v16, 1.0, 0x3e800000, s[16:17]            ; d5010010 0041fef2 3e800000
BB232:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v16, 1.0                                      ; 7e2002f2
BB234:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v16                                 ; 061c210e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB238                                       ; bf880011
BB235:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v0, s0, v17, v9                                   ; d5410000 04262200
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v15, v2], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820000 0000020f
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v6                           ; d4010010 00020d00
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v8, 1.0, 0x3e800000, s[16:17]             ; d5010008 0041fef2 3e800000
BB238:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v8, 1.0                                       ; 7e1002f2
BB240:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v8                                  ; 061c110e
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB244                                       ; bf880011
BB241:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mac_f32_e32 v9, s0, v17                                   ; 3e122200
	v_mac_f32_e32 v15, s0, v18                                  ; 3e1e2400
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v9, [v9, v15, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820909 0000000f
	v_cmp_lt_f32_e32 vcc, 0, v7                                 ; 7c020e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[4:5], v9, v6                             ; d4010004 00020d09
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	v_cndmask_b32_e64 v2, 1.0, 0x3e800000, s[4:5]               ; d5010002 0011fef2 3e800000
BB244:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
BB246:
	s_buffer_load_dwordx16 s[16:31], s[40:43], 0x120            ; f4300414 fa000120
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v14, v14, v2                                  ; 061c050e
	v_mul_f32_e32 v14, 0x3de38e39, v14                          ; 101c1cff 3de38e39
	v_mul_f32_e32 v1, v1, v14                                   ; 10021d01
	v_mul_f32_e32 v13, v13, v14                                 ; 101a1d0d
	v_mul_f32_e32 v21, v21, v14                                 ; 102a1d15
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v0, s24, v5, s28                                  ; d5410000 00720a18
	v_mad_f32 v2, s25, v5, s29                                  ; d5410002 00760a19
	v_mad_f32 v6, s26, v5, s30                                  ; d5410006 007a0a1a
	v_mad_f32 v5, s27, v5, s31                                  ; d5410005 007e0a1b
	v_mac_f32_e32 v0, s20, v4                                   ; 3e000814
	v_mac_f32_e32 v2, s21, v4                                   ; 3e040815
	v_mac_f32_e32 v6, s22, v4                                   ; 3e0c0816
	v_mac_f32_e32 v5, s23, v4                                   ; 3e0a0817
	v_mad_f32 v0, s16, v3, v0 div:2                             ; d5410000 1c020610
	v_mad_f32 v2, s17, v3, v2 div:2                             ; d5410002 1c0a0611
	v_mac_f32_e32 v6, s18, v3                                   ; 3e0c0612
	v_mac_f32_e32 v5, s19, v3                                   ; 3e0a0613
	v_rcp_f32_e32 v7, v5                                        ; 7e0e5505
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v5, v5, v7                                    ; 100a0f05
	v_mad_f32 v8, v0, v7, 0.5                                   ; d5410008 03c20f00
	v_mad_f32 v15, v2, v7, 0.5                                  ; d541000f 03c20f02
	v_cmp_lt_f32_e32 vcc, -1.0, v6                              ; 7c020cf3
	v_cmp_gt_f32_e64 s[4:5], 1.0, v6                            ; d4040004 00020cf2
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB250                                       ; bf88001c
BB247:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v2, s0, -v17, v8                                  ; d5410002 44222200
	v_mad_f32 v3, s0, -v18, v15                                 ; d5410003 443e2400
	v_mov_b32_e32 v4, 2.0                                       ; 7e0802f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v3, v[2:4], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820302
	image_sample  v2, [v2, v15, v4], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820202 0000040f
	v_cmp_lt_f32_e32 vcc, 0, v5                                 ; 7c020a80
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cmp_lt_f32_e64 s[16:17], v3, v6                           ; d4010010 00020d03
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v7, 1.0, 0x3e800000, s[16:17]             ; d5010007 0041fef2 3e800000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v2, v6                           ; d4010010 00020d02
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v9, 1.0, 0x3e800000, s[16:17]             ; d5010009 0041fef2 3e800000
BB250:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v7, 1.0                                       ; 7e0e02f2
	v_mov_b32_e32 v9, 1.0                                       ; 7e1202f2
BB252:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v7, v7, v9                                    ; 060e1307
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB256                                       ; bf880012
BB253:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v2, s0, -v17, v8                                  ; d5410002 44222200
	v_mad_f32 v3, s0, v18, v15                                  ; d5410003 043e2400
	v_mov_b32_e32 v4, 2.0                                       ; 7e0802f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v2, v[2:4], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820202
	v_cmp_lt_f32_e32 vcc, 0, v5                                 ; 7c020a80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v2, v6                           ; d4010010 00020d02
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v9, 1.0, 0x3e800000, s[16:17]             ; d5010009 0041fef2 3e800000
BB256:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v9, 1.0                                       ; 7e1202f2
BB258:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v7, v7, v9                                    ; 060e1307
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB262                                       ; bf880010
BB259:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v9, s0, -v18, v15                                 ; d5410009 443e2400
	v_mov_b32_e32 v10, 2.0                                      ; 7e1402f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v9, v[8:10], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820908
	v_cmp_lt_f32_e32 vcc, 0, v5                                 ; 7c020a80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v9, v6                           ; d4010010 00020d09
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB262:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB264:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v7, v7, v0                                    ; 060e0107
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB268                                       ; bf88000f
BB265:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mov_b32_e32 v0, 2.0                                       ; 7e0002f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v8, v15, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820008 0000000f
	v_cmp_lt_f32_e32 vcc, 0, v5                                 ; 7c020a80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v0, v6                           ; d4010010 00020d00
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v2, 1.0, 0x3e800000, s[16:17]             ; d5010002 0041fef2 3e800000
BB268:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
BB270:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v7, v7, v2                                    ; 060e0507
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB274                                       ; bf880010
BB271:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v9, s0, v18, v15                                  ; d5410009 043e2400
	v_mov_b32_e32 v10, 2.0                                      ; 7e1402f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v9, v[8:10], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820908
	v_cmp_lt_f32_e32 vcc, 0, v5                                 ; 7c020a80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v9, v6                           ; d4010010 00020d09
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB274:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB276:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v7, v7, v0                                    ; 060e0107
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB280                                       ; bf880012
BB277:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v2, s0, v17, v8                                   ; d5410002 04222200
	v_mad_f32 v3, s0, -v18, v15                                 ; d5410003 443e2400
	v_mov_b32_e32 v4, 2.0                                       ; 7e0802f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v2, v[2:4], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820202
	v_cmp_lt_f32_e32 vcc, 0, v5                                 ; 7c020a80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v2, v6                           ; d4010010 00020d02
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v9, 1.0, 0x3e800000, s[16:17]             ; d5010009 0041fef2 3e800000
BB280:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v9, 1.0                                       ; 7e1202f2
BB282:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v7, v7, v9                                    ; 060e1307
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB286                                       ; bf880010
BB283:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mad_f32 v14, s0, v17, v8                                  ; d541000e 04222200
	v_mov_b32_e32 v16, 2.0                                      ; 7e2002f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v14, v[14:16], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00820e0e
	v_cmp_lt_f32_e32 vcc, 0, v5                                 ; 7c020a80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[16:17], v14, v6                          ; d4010010 00020d0e
	s_and_b64 s[16:17], vcc, s[16:17]                           ; 8790106a
	v_cndmask_b32_e64 v0, 1.0, 0x3e800000, s[16:17]             ; d5010000 0041fef2 3e800000
BB286:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
BB288:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v7, v7, v0                                    ; 060e0107
	s_and_b64 exec, s[4:5], exec                                ; 87fe7e04
	s_cbranch_execz BB292                                       ; bf880011
BB289:
	s_load_dwordx4 s[16:19], s[2:3], 0x190                      ; f4080401 fa000190
	v_mac_f32_e32 v8, s0, v17                                   ; 3e102200
	v_mac_f32_e32 v15, s0, v18                                  ; 3e1e2400
	v_mov_b32_e32 v0, 2.0                                       ; 7e0002f4
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v8, [v8, v15, v0], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00820808 0000000f
	v_cmp_lt_f32_e32 vcc, 0, v5                                 ; 7c020a80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[0:1], v8, v6                             ; d4010000 00020d08
	s_and_b64 s[0:1], vcc, s[0:1]                               ; 8780006a
	v_cndmask_b32_e64 v2, 1.0, 0x3e800000, s[0:1]               ; d5010002 0001fef2 3e800000
BB292:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
BB294:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_add_f32_e32 v7, v7, v2                                    ; 060e0507
	v_mul_f32_e32 v7, 0x3de38e39, v7                            ; 100e0eff 3de38e39
	v_mul_f32_e32 v1, v1, v7                                    ; 10020f01
	v_mul_f32_e32 v0, v13, v7                                   ; 10000f0d
	v_mul_f32_e32 v21, v21, v7                                  ; 102a0f15
	s_branch BB297                                              ; bf820001
BB295:
	v_mov_b32_e32 v0, v13                                       ; 7e00030d
BB297:
	v_cvt_pkrtz_f16_f32_e64 v21, v21, 1.0                       ; d52f0015 0001e515
	v_cvt_pkrtz_f16_f32_e32 v1, v1, v0                          ; 5e020101
	exp mrt0 v1, v1, v21, v21 done compr vm                     ; f8001c0f 80801501
	s_endpgm                                                    ; bf810000
