# Pixel Shader
BB0:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx4 s[4:7], s[2:3], 0x40                         ; f4080101 fa000040
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x20                       ; f4080401 fa000020
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_store_dword v0, off, s[4:7], 0                       ; e0700000 80010080
	image_load v1, v2, s[8:15] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm a16 ; f0001108 40020102
	v_mov_b32_e32 v3, -1                                        ; 7e0602c1
	image_store v3, v2, s[8:15] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm a16 ; f0201108 40020302
	s_buffer_load_dword s0, s[16:19], 0x84                      ; f4200008 fa000084
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	s_cbranch_scc0 BB315                                        ; bf840487
BB1:
	s_buffer_load_dword s0, s[16:19], 0x8c                      ; f4200008 fa00008c
	s_mov_b64 s[4:5], exec                                      ; be84047e
	s_mov_b32 s1, 0                                             ; be810380
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_lshrrev_b64 v[2:3], 0, 0                                  ; d7000002 00010080
	v_mov_b32_e32 v4, 0                                         ; 7e080280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_min_u32 s0, s0, 16                                        ; 83809000
BB2:
	s_mov_b64 s[6:7], exec                                      ; be86047e
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_eq_i32_e32 -1, v1                                    ; 7d2402c1
BB3:
	v_mov_b32_e32 v1, s1                                        ; 7e020201
	s_andn2_b64 s[6:7], s[6:7], exec                            ; 8a867e06
	s_cbranch_scc0 BB208                                        ; bf840264
BB10:
	s_load_dwordx4 s[8:11], s[2:3], 0x30                        ; f4080201 fa000030
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_lshlrev_b32_e32 v1, 4, v1                                 ; 34020284
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx3 v[37:39], v1, s[8:11], 0 offen          ; e03c1000 80022501
	s_cmp_lt_u32 s1, s0                                         ; bf0a0001
	s_cbranch_scc0 BB106                                        ; bf840111
BB11:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b32 s8, s1                                            ; be880301
BB12:
	s_cmp_lg_i32 s8, 0                                          ; bf018008
	s_cbranch_scc0 BB23                                         ; bf840031
BB13:
	s_add_u32 s9, s8, -1                                        ; 8009c108
	s_cmp_lt_i32 s9, 8                                          ; bf048809
	s_cbranch_scc0 BB18                                         ; bf840016
BB14:
	s_cmp_lt_i32 s9, 4                                          ; bf048409
	s_cbranch_scc0 BB16                                         ; bf84000a
BB15:
	s_cmp_lt_i32 s9, 1                                          ; bf048109
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 3                                          ; bf048309
	v_cndmask_b32_e32 v1, v7, v5, vcc                           ; 02020b07
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 2                                          ; bf048209
	v_cndmask_b32_e32 v40, v11, v9, vcc                         ; 0250130b
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v40, v40, v1, vcc                         ; 02500328
	s_branch BB22                                               ; bf82001f
BB16:
	s_cmp_lt_i32 s9, 5                                          ; bf048509
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 7                                          ; bf048709
	v_cndmask_b32_e32 v1, v15, v13, vcc                         ; 02021b0f
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 6                                          ; bf048609
	v_cndmask_b32_e32 v40, v19, v17, vcc                        ; 02502313
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v40, v40, v1, vcc                         ; 02500328
	s_branch BB22                                               ; bf820015
BB18:
	s_cmp_lt_i32 s9, 12                                         ; bf048c09
	s_cbranch_scc0 BB20                                         ; bf84000a
BB19:
	s_cmp_lt_i32 s9, 9                                          ; bf048909
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 11                                         ; bf048b09
	v_cndmask_b32_e32 v1, v23, v21, vcc                         ; 02022b17
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 10                                         ; bf048a09
	v_cndmask_b32_e32 v40, v27, v25, vcc                        ; 0250331b
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v40, v40, v1, vcc                         ; 02500328
	s_branch BB22                                               ; bf820009
BB20:
	s_cmp_lt_i32 s9, 13                                         ; bf048d09
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 15                                         ; bf048f09
	v_cndmask_b32_e32 v1, v31, v29, vcc                         ; 02023b1f
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 14                                         ; bf048e09
	v_cndmask_b32_e32 v40, v35, v33, vcc                        ; 02504323
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v40, v40, v1, vcc                         ; 02500328
BB22:
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_u32_e32 vcc, v39, v40                              ; 7d825127
	s_branch BB24                                               ; bf820001
BB23:
	s_mov_b64 vcc, 0                                            ; beea0480
BB24:
	s_not_b64 s[10:11], vcc                                     ; be8a086a
	s_and_saveexec_b64 s[10:11], s[10:11]                       ; be8a240a
BB25:
	v_mov_b32_e32 v1, s8                                        ; 7e020208
	s_andn2_b64 s[10:11], s[10:11], exec                        ; 8a8a7e0a
	s_cbranch_scc0 BB63                                         ; bf840082
BB32:
	s_mov_b64 exec, s[10:11]                                    ; befe040a
	s_add_u32 s9, s8, -1                                        ; 8009c108
	s_cmp_lt_i32 s9, 8                                          ; bf048809
	s_cbranch_scc0 BB37                                         ; bf84001c
BB33:
	s_cmp_lt_i32 s9, 4                                          ; bf048409
	s_cbranch_scc0 BB35                                         ; bf84000d
BB34:
	s_cmp_lt_i32 s9, 1                                          ; bf048109
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 3                                          ; bf048309
	v_cndmask_b32_e32 v1, v8, v6, vcc                           ; 02020d08
	v_cndmask_b32_e32 v40, v7, v5, vcc                          ; 02500b07
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 2                                          ; bf048209
	v_cndmask_b32_e32 v41, v12, v10, vcc                        ; 0252150c
	v_cndmask_b32_e32 v42, v11, v9, vcc                         ; 0254130b
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v41, v41, v1, vcc                         ; 02520329
	v_cndmask_b32_e32 v42, v42, v40, vcc                        ; 0254512a
	s_branch BB41                                               ; bf820028
BB35:
	s_cmp_lt_i32 s9, 5                                          ; bf048509
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 7                                          ; bf048709
	v_cndmask_b32_e32 v1, v16, v14, vcc                         ; 02021d10
	v_cndmask_b32_e32 v40, v15, v13, vcc                        ; 02501b0f
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 6                                          ; bf048609
	v_cndmask_b32_e32 v41, v20, v18, vcc                        ; 02522514
	v_cndmask_b32_e32 v42, v19, v17, vcc                        ; 02542313
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v41, v41, v1, vcc                         ; 02520329
	v_cndmask_b32_e32 v42, v42, v40, vcc                        ; 0254512a
	s_branch BB41                                               ; bf82001b
BB37:
	s_cmp_lt_i32 s9, 12                                         ; bf048c09
	s_cbranch_scc0 BB39                                         ; bf84000d
BB38:
	s_cmp_lt_i32 s9, 9                                          ; bf048909
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 11                                         ; bf048b09
	v_cndmask_b32_e32 v1, v24, v22, vcc                         ; 02022d18
	v_cndmask_b32_e32 v40, v23, v21, vcc                        ; 02502b17
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 10                                         ; bf048a09
	v_cndmask_b32_e32 v41, v28, v26, vcc                        ; 0252351c
	v_cndmask_b32_e32 v42, v27, v25, vcc                        ; 0254331b
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v41, v41, v1, vcc                         ; 02520329
	v_cndmask_b32_e32 v42, v42, v40, vcc                        ; 0254512a
	s_branch BB41                                               ; bf82000c
BB39:
	s_cmp_lt_i32 s9, 13                                         ; bf048d09
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 15                                         ; bf048f09
	v_cndmask_b32_e32 v1, v32, v30, vcc                         ; 02023d20
	v_cndmask_b32_e32 v40, v31, v29, vcc                        ; 02503b1f
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s9, 14                                         ; bf048e09
	v_cndmask_b32_e32 v41, v36, v34, vcc                        ; 02524524
	v_cndmask_b32_e32 v42, v35, v33, vcc                        ; 02544323
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v41, v41, v1, vcc                         ; 02520329
	v_cndmask_b32_e32 v42, v42, v40, vcc                        ; 0254512a
BB41:
	s_cmp_lt_i32 s8, 8                                          ; bf048808
	s_cbranch_scc0 BB52                                         ; bf840022
BB42:
	s_cmp_lt_i32 s8, 4                                          ; bf048408
	s_cbranch_scc0 BB47                                         ; bf840010
BB43:
	s_cmp_lt_i32 s8, 2                                          ; bf048208
	s_cbranch_scc0 BB45                                         ; bf840007
BB44:
	s_cmp_lt_i32 s8, 1                                          ; bf048108
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v8, v41, v8, vcc                          ; 02101129
	v_cndmask_b32_e32 v7, v42, v7, vcc                          ; 020e0f2a
	v_cndmask_b32_e32 v6, v6, v41, vcc                          ; 020c5306
	v_cndmask_b32_e32 v5, v5, v42, vcc                          ; 020a5505
	s_branch BB62                                               ; bf820038
BB45:
	s_cmp_lt_i32 s8, 3                                          ; bf048308
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v12, v41, v12, vcc                        ; 02181929
	v_cndmask_b32_e32 v11, v42, v11, vcc                        ; 0216172a
	v_cndmask_b32_e32 v10, v10, v41, vcc                        ; 0214530a
	v_cndmask_b32_e32 v9, v9, v42, vcc                          ; 02125509
	s_branch BB62                                               ; bf820031
BB47:
	s_cmp_lt_i32 s8, 6                                          ; bf048608
	s_cbranch_scc0 BB49                                         ; bf840007
BB48:
	s_cmp_lt_i32 s8, 5                                          ; bf048508
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v16, v41, v16, vcc                        ; 02202129
	v_cndmask_b32_e32 v15, v42, v15, vcc                        ; 021e1f2a
	v_cndmask_b32_e32 v14, v14, v41, vcc                        ; 021c530e
	v_cndmask_b32_e32 v13, v13, v42, vcc                        ; 021a550d
	s_branch BB62                                               ; bf820028
BB49:
	s_cmp_lt_i32 s8, 7                                          ; bf048708
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v20, v41, v20, vcc                        ; 02282929
	v_cndmask_b32_e32 v19, v42, v19, vcc                        ; 0226272a
	v_cndmask_b32_e32 v18, v18, v41, vcc                        ; 02245312
	v_cndmask_b32_e32 v17, v17, v42, vcc                        ; 02225511
	s_branch BB62                                               ; bf820021
BB52:
	s_cmp_lt_i32 s8, 12                                         ; bf048c08
	s_cbranch_scc0 BB57                                         ; bf840010
BB53:
	s_cmp_lt_i32 s8, 10                                         ; bf048a08
	s_cbranch_scc0 BB55                                         ; bf840007
BB54:
	s_cmp_lt_i32 s8, 9                                          ; bf048908
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v24, v41, v24, vcc                        ; 02303129
	v_cndmask_b32_e32 v23, v42, v23, vcc                        ; 022e2f2a
	v_cndmask_b32_e32 v22, v22, v41, vcc                        ; 022c5316
	v_cndmask_b32_e32 v21, v21, v42, vcc                        ; 022a5515
	s_branch BB62                                               ; bf820016
BB55:
	s_cmp_lt_i32 s8, 11                                         ; bf048b08
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v28, v41, v28, vcc                        ; 02383929
	v_cndmask_b32_e32 v27, v42, v27, vcc                        ; 0236372a
	v_cndmask_b32_e32 v26, v26, v41, vcc                        ; 0234531a
	v_cndmask_b32_e32 v25, v25, v42, vcc                        ; 02325519
	s_branch BB62                                               ; bf82000f
BB57:
	s_cmp_lt_i32 s8, 14                                         ; bf048e08
	s_cbranch_scc0 BB59                                         ; bf840007
BB58:
	s_cmp_lt_i32 s8, 13                                         ; bf048d08
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v32, v41, v32, vcc                        ; 02404129
	v_cndmask_b32_e32 v31, v42, v31, vcc                        ; 023e3f2a
	v_cndmask_b32_e32 v30, v30, v41, vcc                        ; 023c531e
	v_cndmask_b32_e32 v29, v29, v42, vcc                        ; 023a551d
	s_branch BB62                                               ; bf820006
BB59:
	s_cmp_lt_i32 s8, 15                                         ; bf048f08
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v36, v41, v36, vcc                        ; 02484929
	v_cndmask_b32_e32 v35, v42, v35, vcc                        ; 0246472a
	v_cndmask_b32_e32 v34, v34, v41, vcc                        ; 02445322
	v_cndmask_b32_e32 v33, v33, v42, vcc                        ; 02425521
BB62:
	s_mov_b32 s8, s9                                            ; be880309
	s_branch BB12                                               ; bf82ff45
BB63:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 8, v1                                     ; 7d280288
	s_cbranch_execz BB84                                        ; bf880026
BB64:
	s_mov_b64 s[8:9], exec                                      ; be88047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 4, v1                                     ; 7d280284
	s_cbranch_execz BB73                                        ; bf880010
BB65:
	s_mov_b64 s[10:11], exec                                    ; be8a047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 2, v1                                     ; 7d280282
BB66:
	v_cmp_gt_i32_e32 vcc, 1, v1                                 ; 7d080281
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v8, v38, v8, vcc                          ; 02101126
	v_cndmask_b32_e32 v7, v39, v7, vcc                          ; 020e0f27
	v_cndmask_b32_e32 v6, v6, v38, vcc                          ; 020c4d06
	v_cndmask_b32_e32 v5, v5, v39, vcc                          ; 020a4f05
	s_andn2_b64 exec, s[10:11], exec                            ; 8afe7e0a
BB69:
	v_cmp_gt_i32_e32 vcc, 3, v1                                 ; 7d080283
	v_cndmask_b32_e32 v12, v38, v12, vcc                        ; 02181926
	v_cndmask_b32_e32 v11, v39, v11, vcc                        ; 02161727
	v_cndmask_b32_e32 v10, v10, v38, vcc                        ; 02144d0a
	v_cndmask_b32_e32 v9, v9, v39, vcc                          ; 02124f09
BB71:
	s_mov_b64 exec, s[10:11]                                    ; befe040a
BB73:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	s_cbranch_execz BB82                                        ; bf88000f
BB74:
	s_mov_b64 s[10:11], exec                                    ; be8a047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 6, v1                                     ; 7d280286
BB75:
	v_cmp_gt_i32_e32 vcc, 5, v1                                 ; 7d080285
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v16, v38, v16, vcc                        ; 02202126
	v_cndmask_b32_e32 v15, v39, v15, vcc                        ; 021e1f27
	v_cndmask_b32_e32 v14, v14, v38, vcc                        ; 021c4d0e
	v_cndmask_b32_e32 v13, v13, v39, vcc                        ; 021a4f0d
	s_andn2_b64 exec, s[10:11], exec                            ; 8afe7e0a
BB78:
	v_cmp_gt_i32_e32 vcc, 7, v1                                 ; 7d080287
	v_cndmask_b32_e32 v20, v38, v20, vcc                        ; 02282926
	v_cndmask_b32_e32 v19, v39, v19, vcc                        ; 02262727
	v_cndmask_b32_e32 v18, v18, v38, vcc                        ; 02244d12
	v_cndmask_b32_e32 v17, v17, v39, vcc                        ; 02224f11
BB82:
	s_mov_b64 exec, s[8:9]                                      ; befe0408
BB84:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	s_cbranch_execz BB105                                       ; bf880025
BB85:
	s_mov_b64 s[8:9], exec                                      ; be88047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 12, v1                                    ; 7d28028c
	s_cbranch_execz BB94                                        ; bf880010
BB86:
	s_mov_b64 s[10:11], exec                                    ; be8a047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 10, v1                                    ; 7d28028a
BB87:
	v_cmp_gt_i32_e32 vcc, 9, v1                                 ; 7d080289
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v24, v38, v24, vcc                        ; 02303126
	v_cndmask_b32_e32 v23, v39, v23, vcc                        ; 022e2f27
	v_cndmask_b32_e32 v22, v22, v38, vcc                        ; 022c4d16
	v_cndmask_b32_e32 v21, v21, v39, vcc                        ; 022a4f15
	s_andn2_b64 exec, s[10:11], exec                            ; 8afe7e0a
BB90:
	v_cmp_gt_i32_e32 vcc, 11, v1                                ; 7d08028b
	v_cndmask_b32_e32 v28, v38, v28, vcc                        ; 02383926
	v_cndmask_b32_e32 v27, v39, v27, vcc                        ; 02363727
	v_cndmask_b32_e32 v26, v26, v38, vcc                        ; 02344d1a
	v_cndmask_b32_e32 v25, v25, v39, vcc                        ; 02324f19
BB92:
	s_mov_b64 exec, s[10:11]                                    ; befe040a
BB94:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	s_cbranch_execz BB105                                       ; bf88000f
BB95:
	s_mov_b64 s[10:11], exec                                    ; be8a047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 14, v1                                    ; 7d28028e
BB96:
	v_cmp_gt_i32_e32 vcc, 13, v1                                ; 7d08028d
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cndmask_b32_e32 v32, v38, v32, vcc                        ; 02404126
	v_cndmask_b32_e32 v31, v39, v31, vcc                        ; 023e3f27
	v_cndmask_b32_e32 v30, v30, v38, vcc                        ; 023c4d1e
	v_cndmask_b32_e32 v29, v29, v39, vcc                        ; 023a4f1d
	s_andn2_b64 exec, s[10:11], exec                            ; 8afe7e0a
BB99:
	v_cmp_gt_i32_e32 vcc, 15, v1                                ; 7d08028f
	v_cndmask_b32_e32 v36, v38, v36, vcc                        ; 02484926
	v_cndmask_b32_e32 v35, v39, v35, vcc                        ; 02464727
	v_cndmask_b32_e32 v34, v34, v38, vcc                        ; 02444d22
	v_cndmask_b32_e32 v33, v33, v39, vcc                        ; 02424f21
BB105:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	s_add_u32 s1, s1, 1                                         ; 80018101
	s_branch BB207                                              ; bf820148
BB106:
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 v5, v39                                   ; 7da24f05
	s_cbranch_execz BB203                                       ; bf880126
BB107:
	v_cvt_f32_ubyte3_e32 v1, v6                                 ; 7e022906
	s_mov_b32 s8, 0x3b808081                                    ; be8803ff 3b808081
	v_cvt_f32_ubyte0_e32 v42, v6                                ; 7e542306
	v_cvt_f32_ubyte1_e32 v43, v6                                ; 7e562506
	v_cvt_f32_ubyte2_e32 v44, v6                                ; 7e582706
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v3, v3, v0                                    ; 10060103
	v_mul_f32_e32 v2, v2, v0                                    ; 10040102
	v_mul_f32_e32 v1, s8, v1                                    ; 10020208
	v_mul_f32_e32 v42, s8, v42                                  ; 10545408
	s_add_u32 s9, s0, -1                                        ; 8009c100
	v_mul_f32_e32 v43, s8, v43                                  ; 10565608
	s_mov_b64 s[10:11], exec                                    ; be8a047e
	v_mul_f32_e32 v44, s8, v44                                  ; 10585808
	s_mov_b32 s8, 0                                             ; be880380
	v_sub_f32_e32 v40, 1.0, v1                                  ; 085002f2
	v_mul_f32_e32 v42, v42, v1                                  ; 1054032a
	v_mul_f32_e32 v43, v43, v1                                  ; 1056032b
	v_mul_f32_e32 v44, v44, v1                                  ; 1058032c
	v_mad_f32 v41, v0, v40, v1                                  ; d5410029 04065100
	v_mac_f32_e32 v42, v4, v40                                  ; 3e545104
	v_mac_f32_e32 v43, v3, v40                                  ; 3e565103
	v_mac_f32_e32 v44, v2, v40                                  ; 3e585102
	v_rcp_f32_e32 v45, v41                                      ; 7e5a5529
	v_mul_f32_e32 v2, v44, v45                                  ; 10045b2c
	v_mul_f32_e32 v4, v42, v45                                  ; 10085b2a
	v_mul_f32_e32 v3, v43, v45                                  ; 10065b2b
BB108:
	s_cmp_lt_u32 s8, s9                                         ; bf0a0908
	s_cbranch_scc0 BB119                                        ; bf840030
BB109:
	s_add_u32 s12, s8, 1                                        ; 800c8108
	s_cmp_lt_i32 s12, 8                                         ; bf04880c
	s_cbranch_scc0 BB114                                        ; bf840016
BB110:
	s_cmp_lt_i32 s12, 4                                         ; bf04840c
	s_cbranch_scc0 BB112                                        ; bf84000a
BB111:
	s_cmp_lt_i32 s12, 1                                         ; bf04810c
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 3                                         ; bf04830c
	v_cndmask_b32_e32 v0, v7, v5, vcc                           ; 02000b07
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 2                                         ; bf04820c
	v_cndmask_b32_e32 v1, v11, v9, vcc                          ; 0202130b
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v1, v1, v0, vcc                           ; 02020101
	s_branch BB118                                              ; bf82001f
BB112:
	s_cmp_lt_i32 s12, 5                                         ; bf04850c
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 7                                         ; bf04870c
	v_cndmask_b32_e32 v0, v15, v13, vcc                         ; 02001b0f
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 6                                         ; bf04860c
	v_cndmask_b32_e32 v1, v19, v17, vcc                         ; 02022313
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v1, v1, v0, vcc                           ; 02020101
	s_branch BB118                                              ; bf820015
BB114:
	s_cmp_lt_i32 s12, 12                                        ; bf048c0c
	s_cbranch_scc0 BB116                                        ; bf84000a
BB115:
	s_cmp_lt_i32 s12, 9                                         ; bf04890c
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 11                                        ; bf048b0c
	v_cndmask_b32_e32 v0, v23, v21, vcc                         ; 02002b17
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 10                                        ; bf048a0c
	v_cndmask_b32_e32 v1, v27, v25, vcc                         ; 0202331b
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v1, v1, v0, vcc                           ; 02020101
	s_branch BB118                                              ; bf820009
BB116:
	s_cmp_lt_i32 s12, 13                                        ; bf048d0c
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 15                                        ; bf048f0c
	v_cndmask_b32_e32 v0, v31, v29, vcc                         ; 02003b1f
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 14                                        ; bf048e0c
	v_cndmask_b32_e32 v1, v35, v33, vcc                         ; 02024323
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v1, v1, v0, vcc                           ; 02020101
BB118:
	v_cmp_lt_u32_e32 vcc, v1, v39                               ; 7d824f01
	s_branch BB120                                              ; bf820001
BB119:
	s_mov_b64 vcc, 0                                            ; beea0480
BB120:
	s_not_b64 s[12:13], vcc                                     ; be8c086a
	s_and_saveexec_b64 s[12:13], s[12:13]                       ; be8c240c
BB121:
	v_mov_b32_e32 v0, s8                                        ; 7e000208
	s_andn2_b64 s[12:13], s[12:13], exec                        ; 8a8c7e0c
	s_cbranch_scc0 BB159                                        ; bf840082
BB128:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
	s_add_u32 s12, s8, 1                                        ; 800c8108
	s_cmp_lt_i32 s12, 8                                         ; bf04880c
	s_cbranch_scc0 BB133                                        ; bf84001c
BB129:
	s_cmp_lt_i32 s12, 4                                         ; bf04840c
	s_cbranch_scc0 BB131                                        ; bf84000d
BB130:
	s_cmp_lt_i32 s12, 1                                         ; bf04810c
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 3                                         ; bf04830c
	v_cndmask_b32_e32 v0, v8, v6, vcc                           ; 02000d08
	v_cndmask_b32_e32 v1, v7, v5, vcc                           ; 02020b07
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 2                                         ; bf04820c
	v_cndmask_b32_e32 v40, v12, v10, vcc                        ; 0250150c
	v_cndmask_b32_e32 v42, v11, v9, vcc                         ; 0254130b
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v40, v40, v0, vcc                         ; 02500128
	v_cndmask_b32_e32 v42, v42, v1, vcc                         ; 0254032a
	s_branch BB137                                              ; bf820028
BB131:
	s_cmp_lt_i32 s12, 5                                         ; bf04850c
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 7                                         ; bf04870c
	v_cndmask_b32_e32 v0, v16, v14, vcc                         ; 02001d10
	v_cndmask_b32_e32 v1, v15, v13, vcc                         ; 02021b0f
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 6                                         ; bf04860c
	v_cndmask_b32_e32 v40, v20, v18, vcc                        ; 02502514
	v_cndmask_b32_e32 v42, v19, v17, vcc                        ; 02542313
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v40, v40, v0, vcc                         ; 02500128
	v_cndmask_b32_e32 v42, v42, v1, vcc                         ; 0254032a
	s_branch BB137                                              ; bf82001b
BB133:
	s_cmp_lt_i32 s12, 12                                        ; bf048c0c
	s_cbranch_scc0 BB135                                        ; bf84000d
BB134:
	s_cmp_lt_i32 s12, 9                                         ; bf04890c
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 11                                        ; bf048b0c
	v_cndmask_b32_e32 v0, v24, v22, vcc                         ; 02002d18
	v_cndmask_b32_e32 v1, v23, v21, vcc                         ; 02022b17
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 10                                        ; bf048a0c
	v_cndmask_b32_e32 v40, v28, v26, vcc                        ; 0250351c
	v_cndmask_b32_e32 v42, v27, v25, vcc                        ; 0254331b
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v40, v40, v0, vcc                         ; 02500128
	v_cndmask_b32_e32 v42, v42, v1, vcc                         ; 0254032a
	s_branch BB137                                              ; bf82000c
BB135:
	s_cmp_lt_i32 s12, 13                                        ; bf048d0c
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 15                                        ; bf048f0c
	v_cndmask_b32_e32 v0, v32, v30, vcc                         ; 02003d20
	v_cndmask_b32_e32 v1, v31, v29, vcc                         ; 02023b1f
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_cmp_lt_i32 s12, 14                                        ; bf048e0c
	v_cndmask_b32_e32 v40, v36, v34, vcc                        ; 02504524
	v_cndmask_b32_e32 v42, v35, v33, vcc                        ; 02544323
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v40, v40, v0, vcc                         ; 02500128
	v_cndmask_b32_e32 v42, v42, v1, vcc                         ; 0254032a
BB137:
	s_cmp_lt_i32 s8, 8                                          ; bf048808
	s_cbranch_scc0 BB148                                        ; bf840022
BB138:
	s_cmp_lt_i32 s8, 4                                          ; bf048408
	s_cbranch_scc0 BB143                                        ; bf840010
BB139:
	s_cmp_lt_i32 s8, 2                                          ; bf048208
	s_cbranch_scc0 BB141                                        ; bf840007
BB140:
	s_cmp_lt_i32 s8, 1                                          ; bf048108
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v8, v40, v8, vcc                          ; 02101128
	v_cndmask_b32_e32 v7, v42, v7, vcc                          ; 020e0f2a
	v_cndmask_b32_e32 v6, v6, v40, vcc                          ; 020c5106
	v_cndmask_b32_e32 v5, v5, v42, vcc                          ; 020a5505
	s_branch BB158                                              ; bf820038
BB141:
	s_cmp_lt_i32 s8, 3                                          ; bf048308
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v12, v40, v12, vcc                        ; 02181928
	v_cndmask_b32_e32 v11, v42, v11, vcc                        ; 0216172a
	v_cndmask_b32_e32 v10, v10, v40, vcc                        ; 0214510a
	v_cndmask_b32_e32 v9, v9, v42, vcc                          ; 02125509
	s_branch BB158                                              ; bf820031
BB143:
	s_cmp_lt_i32 s8, 6                                          ; bf048608
	s_cbranch_scc0 BB145                                        ; bf840007
BB144:
	s_cmp_lt_i32 s8, 5                                          ; bf048508
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v16, v40, v16, vcc                        ; 02202128
	v_cndmask_b32_e32 v15, v42, v15, vcc                        ; 021e1f2a
	v_cndmask_b32_e32 v14, v14, v40, vcc                        ; 021c510e
	v_cndmask_b32_e32 v13, v13, v42, vcc                        ; 021a550d
	s_branch BB158                                              ; bf820028
BB145:
	s_cmp_lt_i32 s8, 7                                          ; bf048708
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v20, v40, v20, vcc                        ; 02282928
	v_cndmask_b32_e32 v19, v42, v19, vcc                        ; 0226272a
	v_cndmask_b32_e32 v18, v18, v40, vcc                        ; 02245112
	v_cndmask_b32_e32 v17, v17, v42, vcc                        ; 02225511
	s_branch BB158                                              ; bf820021
BB148:
	s_cmp_lt_i32 s8, 12                                         ; bf048c08
	s_cbranch_scc0 BB153                                        ; bf840010
BB149:
	s_cmp_lt_i32 s8, 10                                         ; bf048a08
	s_cbranch_scc0 BB151                                        ; bf840007
BB150:
	s_cmp_lt_i32 s8, 9                                          ; bf048908
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v24, v40, v24, vcc                        ; 02303128
	v_cndmask_b32_e32 v23, v42, v23, vcc                        ; 022e2f2a
	v_cndmask_b32_e32 v22, v22, v40, vcc                        ; 022c5116
	v_cndmask_b32_e32 v21, v21, v42, vcc                        ; 022a5515
	s_branch BB158                                              ; bf820016
BB151:
	s_cmp_lt_i32 s8, 11                                         ; bf048b08
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v28, v40, v28, vcc                        ; 02383928
	v_cndmask_b32_e32 v27, v42, v27, vcc                        ; 0236372a
	v_cndmask_b32_e32 v26, v26, v40, vcc                        ; 0234511a
	v_cndmask_b32_e32 v25, v25, v42, vcc                        ; 02325519
	s_branch BB158                                              ; bf82000f
BB153:
	s_cmp_lt_i32 s8, 14                                         ; bf048e08
	s_cbranch_scc0 BB155                                        ; bf840007
BB154:
	s_cmp_lt_i32 s8, 13                                         ; bf048d08
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v32, v40, v32, vcc                        ; 02404128
	v_cndmask_b32_e32 v31, v42, v31, vcc                        ; 023e3f2a
	v_cndmask_b32_e32 v30, v30, v40, vcc                        ; 023c511e
	v_cndmask_b32_e32 v29, v29, v42, vcc                        ; 023a551d
	s_branch BB158                                              ; bf820006
BB155:
	s_cmp_lt_i32 s8, 15                                         ; bf048f08
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	v_cndmask_b32_e32 v36, v40, v36, vcc                        ; 02484928
	v_cndmask_b32_e32 v35, v42, v35, vcc                        ; 0246472a
	v_cndmask_b32_e32 v34, v34, v40, vcc                        ; 02445122
	v_cndmask_b32_e32 v33, v33, v42, vcc                        ; 02425521
BB158:
	s_mov_b32 s8, s12                                           ; be88030c
	s_branch BB108                                              ; bf82ff46
BB159:
	s_mov_b64 exec, s[10:11]                                    ; befe040a
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 8, v0                                     ; 7d280088
	s_cbranch_execz BB180                                       ; bf880024
BB160:
	s_mov_b64 s[8:9], exec                                      ; be88047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 4, v0                                     ; 7d280084
	s_cbranch_execz BB169                                       ; bf88000f
BB161:
	s_mov_b64 s[12:13], exec                                    ; be8c047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 2, v0                                     ; 7d280082
BB162:
	v_cmp_gt_i32_e32 vcc, 1, v0                                 ; 7d080081
	v_cndmask_b32_e32 v8, v38, v8, vcc                          ; 02101126
	v_cndmask_b32_e32 v7, v39, v7, vcc                          ; 020e0f27
	v_cndmask_b32_e32 v6, v6, v38, vcc                          ; 020c4d06
	v_cndmask_b32_e32 v5, v5, v39, vcc                          ; 020a4f05
	s_andn2_b64 exec, s[12:13], exec                            ; 8afe7e0c
BB165:
	v_cmp_gt_i32_e32 vcc, 3, v0                                 ; 7d080083
	v_cndmask_b32_e32 v12, v38, v12, vcc                        ; 02181926
	v_cndmask_b32_e32 v11, v39, v11, vcc                        ; 02161727
	v_cndmask_b32_e32 v10, v10, v38, vcc                        ; 02144d0a
	v_cndmask_b32_e32 v9, v9, v39, vcc                          ; 02124f09
BB167:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
BB169:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	s_cbranch_execz BB178                                       ; bf88000e
BB170:
	s_mov_b64 s[12:13], exec                                    ; be8c047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 6, v0                                     ; 7d280086
BB171:
	v_cmp_gt_i32_e32 vcc, 5, v0                                 ; 7d080085
	v_cndmask_b32_e32 v16, v38, v16, vcc                        ; 02202126
	v_cndmask_b32_e32 v15, v39, v15, vcc                        ; 021e1f27
	v_cndmask_b32_e32 v14, v14, v38, vcc                        ; 021c4d0e
	v_cndmask_b32_e32 v13, v13, v39, vcc                        ; 021a4f0d
	s_andn2_b64 exec, s[12:13], exec                            ; 8afe7e0c
BB174:
	v_cmp_gt_i32_e32 vcc, 7, v0                                 ; 7d080087
	v_cndmask_b32_e32 v20, v38, v20, vcc                        ; 02282926
	v_cndmask_b32_e32 v19, v39, v19, vcc                        ; 02262727
	v_cndmask_b32_e32 v18, v18, v38, vcc                        ; 02244d12
	v_cndmask_b32_e32 v17, v17, v39, vcc                        ; 02224f11
BB178:
	s_mov_b64 exec, s[8:9]                                      ; befe0408
BB180:
	s_andn2_b64 exec, s[10:11], exec                            ; 8afe7e0a
	s_cbranch_execz BB201                                       ; bf880023
BB181:
	s_mov_b64 s[8:9], exec                                      ; be88047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 12, v0                                    ; 7d28008c
	s_cbranch_execz BB190                                       ; bf88000f
BB182:
	s_mov_b64 s[12:13], exec                                    ; be8c047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 10, v0                                    ; 7d28008a
BB183:
	v_cmp_gt_i32_e32 vcc, 9, v0                                 ; 7d080089
	v_cndmask_b32_e32 v24, v38, v24, vcc                        ; 02303126
	v_cndmask_b32_e32 v23, v39, v23, vcc                        ; 022e2f27
	v_cndmask_b32_e32 v22, v22, v38, vcc                        ; 022c4d16
	v_cndmask_b32_e32 v21, v21, v39, vcc                        ; 022a4f15
	s_andn2_b64 exec, s[12:13], exec                            ; 8afe7e0c
BB186:
	v_cmp_gt_i32_e32 vcc, 11, v0                                ; 7d08008b
	v_cndmask_b32_e32 v28, v38, v28, vcc                        ; 02383926
	v_cndmask_b32_e32 v27, v39, v27, vcc                        ; 02363727
	v_cndmask_b32_e32 v26, v26, v38, vcc                        ; 02344d1a
	v_cndmask_b32_e32 v25, v25, v39, vcc                        ; 02324f19
BB188:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
BB190:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	s_cbranch_execz BB201                                       ; bf88000e
BB191:
	s_mov_b64 s[12:13], exec                                    ; be8c047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_gt_i32_e32 14, v0                                    ; 7d28008e
BB192:
	v_cmp_gt_i32_e32 vcc, 13, v0                                ; 7d08008d
	v_cndmask_b32_e32 v32, v38, v32, vcc                        ; 02404126
	v_cndmask_b32_e32 v31, v39, v31, vcc                        ; 023e3f27
	v_cndmask_b32_e32 v30, v30, v38, vcc                        ; 023c4d1e
	v_cndmask_b32_e32 v29, v29, v39, vcc                        ; 023a4f1d
	s_andn2_b64 exec, s[12:13], exec                            ; 8afe7e0c
BB195:
	v_cmp_gt_i32_e32 vcc, 15, v0                                ; 7d08008f
	v_cndmask_b32_e32 v36, v38, v36, vcc                        ; 02484926
	v_cndmask_b32_e32 v35, v39, v35, vcc                        ; 02464727
	v_cndmask_b32_e32 v34, v34, v38, vcc                        ; 02444d22
	v_cndmask_b32_e32 v33, v33, v39, vcc                        ; 02424f21
BB201:
	s_mov_b64 exec, s[10:11]                                    ; befe040a
	v_mov_b32_e32 v0, v41                                       ; 7e000329
BB203:
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
	s_cbranch_execz BB206                                       ; bf88001b
BB204:
	v_cvt_f32_ubyte3_e32 v1, v38                                ; 7e022926
	s_mov_b32 s8, 0x3b808081                                    ; be8803ff 3b808081
	v_cvt_f32_ubyte0_e32 v41, v38                               ; 7e522326
	v_cvt_f32_ubyte1_e32 v42, v38                               ; 7e542526
	v_cvt_f32_ubyte2_e32 v38, v38                               ; 7e4c2726
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v3, v3, v0                                    ; 10060103
	v_mul_f32_e32 v2, v2, v0                                    ; 10040102
	v_mul_f32_e32 v1, s8, v1                                    ; 10020208
	v_mul_f32_e32 v41, s8, v41                                  ; 10525208
	v_mul_f32_e32 v42, s8, v42                                  ; 10545408
	v_mul_f32_e32 v38, s8, v38                                  ; 104c4c08
	v_sub_f32_e32 v39, 1.0, v1                                  ; 084e02f2
	v_mul_f32_e32 v41, v41, v1                                  ; 10520329
	v_mul_f32_e32 v42, v42, v1                                  ; 1054032a
	v_mul_f32_e32 v38, v38, v1                                  ; 104c0326
	v_mad_f32 v40, v0, v39, v1                                  ; d5410028 04064f00
	v_mac_f32_e32 v41, v4, v39                                  ; 3e524f04
	v_mac_f32_e32 v42, v3, v39                                  ; 3e544f03
	v_mac_f32_e32 v38, v2, v39                                  ; 3e4c4f02
	v_mov_b32_e32 v0, v40                                       ; 7e000328
	v_rcp_f32_e32 v43, v40                                      ; 7e565528
	v_mul_f32_e32 v2, v38, v43                                  ; 10045726
	v_mul_f32_e32 v4, v41, v43                                  ; 10085729
	v_mul_f32_e32 v3, v42, v43                                  ; 1006572a
BB206:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
BB207:
	v_mov_b32_e32 v1, v37                                       ; 7e020325
	s_branch BB2                                                ; bf82fd95
BB208:
	s_mov_b64 exec, s[4:5]                                      ; befe0404
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_ne_i32_e32 0, v1                                     ; 7d2a0280
	s_cbranch_execz BB312                                       ; bf880207
BB209:
	v_cvt_f32_ubyte3_e32 v5, v6                                 ; 7e0a2906
	s_mov_b32 s0, 0x3b808081                                    ; be8003ff 3b808081
	v_cvt_f32_ubyte0_e32 v11, v6                                ; 7e162306
	v_cvt_f32_ubyte1_e32 v13, v6                                ; 7e1a2506
	v_cvt_f32_ubyte2_e32 v6, v6                                 ; 7e0c2706
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v3, v3, v0                                    ; 10060103
	v_mul_f32_e32 v2, v2, v0                                    ; 10040102
	v_mul_f32_e32 v5, s0, v5                                    ; 100a0a00
	v_mul_f32_e32 v11, s0, v11                                  ; 10161600
	v_mul_f32_e32 v13, s0, v13                                  ; 101a1a00
	v_mul_f32_e32 v6, s0, v6                                    ; 100c0c00
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_sub_f32_e32 v7, 1.0, v5                                   ; 080e0af2
	v_mul_f32_e32 v11, v11, v5                                  ; 10160b0b
	v_mul_f32_e32 v13, v13, v5                                  ; 101a0b0d
	v_mul_f32_e32 v6, v6, v5                                    ; 100c0b06
	v_mad_f32 v9, v0, v7, v5                                    ; d5410009 04160f00
	v_mac_f32_e32 v11, v4, v7                                   ; 3e160f04
	v_mac_f32_e32 v13, v3, v7                                   ; 3e1a0f03
	v_mac_f32_e32 v6, v2, v7                                    ; 3e0c0f02
	v_rcp_f32_e32 v15, v9                                       ; 7e1e5509
	v_mul_f32_e32 v6, v6, v15                                   ; 100c1f06
	v_mul_f32_e32 v11, v11, v15                                 ; 10161f0b
	v_mul_f32_e32 v13, v13, v15                                 ; 101a1f0d
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 1, v1                                     ; 7da20281
	s_cbranch_execz BB309                                       ; bf8801e8
BB210:
	v_cvt_f32_ubyte3_e32 v0, v8                                 ; 7e002908
	s_mov_b32 s2, 0x3b808081                                    ; be8203ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v8                                 ; 7e082308
	v_cvt_f32_ubyte1_e32 v5, v8                                 ; 7e0a2508
	v_cvt_f32_ubyte2_e32 v8, v8                                 ; 7e102708
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v0, s2, v0                                    ; 10000002
	v_mul_f32_e32 v4, s2, v4                                    ; 10080802
	v_mul_f32_e32 v5, s2, v5                                    ; 100a0a02
	v_mul_f32_e32 v8, s2, v8                                    ; 10101002
	s_mov_b64 s[2:3], exec                                      ; be82047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v8, v8, v0                                    ; 10100108
	v_mad_f32 v3, v9, v2, v0                                    ; d5410003 04020509
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v8, v6, v2                                    ; 3e100506
	v_rcp_f32_e32 v6, v3                                        ; 7e0c5503
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v8, v6                                    ; 100c0d08
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 2, v1                                     ; 7da20282
	s_cbranch_execz BB302                                       ; bf8801c8
BB211:
	v_cvt_f32_ubyte3_e32 v0, v10                                ; 7e00290a
	s_mov_b32 s6, 0x3b808081                                    ; be8603ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v10                                ; 7e08230a
	v_cvt_f32_ubyte1_e32 v5, v10                                ; 7e0a250a
	v_cvt_f32_ubyte2_e32 v10, v10                               ; 7e14270a
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v13, v13, v3                                  ; 101a070d
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_mul_f32_e32 v0, s6, v0                                    ; 10000006
	v_mul_f32_e32 v4, s6, v4                                    ; 10080806
	v_mul_f32_e32 v5, s6, v5                                    ; 100a0a06
	v_mul_f32_e32 v10, s6, v10                                  ; 10141406
	s_mov_b64 s[6:7], exec                                      ; be86047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v10, v10, v0                                  ; 1014010a
	v_mad_f32 v9, v3, v2, v0                                    ; d5410009 04020503
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v10, v6, v2                                   ; 3e140506
	v_rcp_f32_e32 v6, v9                                        ; 7e0c5509
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v10, v6                                   ; 100c0d0a
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 3, v1                                     ; 7da20283
	s_cbranch_execz BB299                                       ; bf8801a9
BB212:
	v_cvt_f32_ubyte3_e32 v0, v12                                ; 7e00290c
	s_mov_b32 s8, 0x3b808081                                    ; be8803ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v12                                ; 7e08230c
	v_cvt_f32_ubyte1_e32 v5, v12                                ; 7e0a250c
	v_cvt_f32_ubyte2_e32 v12, v12                               ; 7e18270c
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v0, s8, v0                                    ; 10000008
	v_mul_f32_e32 v4, s8, v4                                    ; 10080808
	v_mul_f32_e32 v5, s8, v5                                    ; 100a0a08
	v_mul_f32_e32 v12, s8, v12                                  ; 10181808
	s_mov_b64 s[8:9], exec                                      ; be88047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v12, v12, v0                                  ; 1018010c
	v_mad_f32 v3, v9, v2, v0                                    ; d5410003 04020509
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v12, v6, v2                                   ; 3e180506
	v_rcp_f32_e32 v6, v3                                        ; 7e0c5503
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v12, v6                                   ; 100c0d0c
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 4, v1                                     ; 7da20284
	s_cbranch_execz BB292                                       ; bf880189
BB213:
	v_cvt_f32_ubyte3_e32 v0, v14                                ; 7e00290e
	s_mov_b32 s10, 0x3b808081                                   ; be8a03ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v14                                ; 7e08230e
	v_cvt_f32_ubyte1_e32 v5, v14                                ; 7e0a250e
	v_cvt_f32_ubyte2_e32 v14, v14                               ; 7e1c270e
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v13, v13, v3                                  ; 101a070d
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_mul_f32_e32 v0, s10, v0                                   ; 1000000a
	v_mul_f32_e32 v4, s10, v4                                   ; 1008080a
	v_mul_f32_e32 v5, s10, v5                                   ; 100a0a0a
	v_mul_f32_e32 v14, s10, v14                                 ; 101c1c0a
	s_mov_b64 s[10:11], exec                                    ; be8a047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v14, v14, v0                                  ; 101c010e
	v_mad_f32 v9, v3, v2, v0                                    ; d5410009 04020503
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v14, v6, v2                                   ; 3e1c0506
	v_rcp_f32_e32 v6, v9                                        ; 7e0c5509
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v14, v6                                   ; 100c0d0e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 5, v1                                     ; 7da20285
	s_cbranch_execz BB289                                       ; bf88016a
BB214:
	v_cvt_f32_ubyte3_e32 v0, v16                                ; 7e002910
	s_mov_b32 s12, 0x3b808081                                   ; be8c03ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v16                                ; 7e082310
	v_cvt_f32_ubyte1_e32 v5, v16                                ; 7e0a2510
	v_cvt_f32_ubyte2_e32 v16, v16                               ; 7e202710
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v0, s12, v0                                   ; 1000000c
	v_mul_f32_e32 v4, s12, v4                                   ; 1008080c
	v_mul_f32_e32 v5, s12, v5                                   ; 100a0a0c
	v_mul_f32_e32 v16, s12, v16                                 ; 1020200c
	s_mov_b64 s[12:13], exec                                    ; be8c047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v16, v16, v0                                  ; 10200110
	v_mad_f32 v3, v9, v2, v0                                    ; d5410003 04020509
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v16, v6, v2                                   ; 3e200506
	v_rcp_f32_e32 v6, v3                                        ; 7e0c5503
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v16, v6                                   ; 100c0d10
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 6, v1                                     ; 7da20286
	s_cbranch_execz BB282                                       ; bf88014a
BB215:
	v_cvt_f32_ubyte3_e32 v0, v18                                ; 7e002912
	s_mov_b32 s14, 0x3b808081                                   ; be8e03ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v18                                ; 7e082312
	v_cvt_f32_ubyte1_e32 v5, v18                                ; 7e0a2512
	v_cvt_f32_ubyte2_e32 v18, v18                               ; 7e242712
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v13, v13, v3                                  ; 101a070d
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_mul_f32_e32 v0, s14, v0                                   ; 1000000e
	v_mul_f32_e32 v4, s14, v4                                   ; 1008080e
	v_mul_f32_e32 v5, s14, v5                                   ; 100a0a0e
	v_mul_f32_e32 v18, s14, v18                                 ; 1024240e
	s_mov_b64 s[14:15], exec                                    ; be8e047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v18, v18, v0                                  ; 10240112
	v_mad_f32 v9, v3, v2, v0                                    ; d5410009 04020503
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v18, v6, v2                                   ; 3e240506
	v_rcp_f32_e32 v6, v9                                        ; 7e0c5509
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v18, v6                                   ; 100c0d12
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 7, v1                                     ; 7da20287
	s_cbranch_execz BB279                                       ; bf88012b
BB216:
	v_cvt_f32_ubyte3_e32 v0, v20                                ; 7e002914
	s_mov_b32 s16, 0x3b808081                                   ; be9003ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v20                                ; 7e082314
	v_cvt_f32_ubyte1_e32 v5, v20                                ; 7e0a2514
	v_cvt_f32_ubyte2_e32 v20, v20                               ; 7e282714
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v0, s16, v0                                   ; 10000010
	v_mul_f32_e32 v4, s16, v4                                   ; 10080810
	v_mul_f32_e32 v5, s16, v5                                   ; 100a0a10
	v_mul_f32_e32 v20, s16, v20                                 ; 10282810
	s_mov_b64 s[16:17], exec                                    ; be90047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v20, v20, v0                                  ; 10280114
	v_mad_f32 v3, v9, v2, v0                                    ; d5410003 04020509
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v20, v6, v2                                   ; 3e280506
	v_rcp_f32_e32 v6, v3                                        ; 7e0c5503
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v20, v6                                   ; 100c0d14
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 8, v1                                     ; 7da20288
	s_cbranch_execz BB272                                       ; bf88010b
BB217:
	v_cvt_f32_ubyte3_e32 v0, v22                                ; 7e002916
	s_mov_b32 s18, 0x3b808081                                   ; be9203ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v22                                ; 7e082316
	v_cvt_f32_ubyte1_e32 v5, v22                                ; 7e0a2516
	v_cvt_f32_ubyte2_e32 v22, v22                               ; 7e2c2716
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v13, v13, v3                                  ; 101a070d
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_mul_f32_e32 v0, s18, v0                                   ; 10000012
	v_mul_f32_e32 v4, s18, v4                                   ; 10080812
	v_mul_f32_e32 v5, s18, v5                                   ; 100a0a12
	v_mul_f32_e32 v22, s18, v22                                 ; 102c2c12
	s_mov_b64 s[18:19], exec                                    ; be92047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v22, v22, v0                                  ; 102c0116
	v_mad_f32 v9, v3, v2, v0                                    ; d5410009 04020503
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v22, v6, v2                                   ; 3e2c0506
	v_rcp_f32_e32 v6, v9                                        ; 7e0c5509
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v22, v6                                   ; 100c0d16
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 9, v1                                     ; 7da20289
	s_cbranch_execz BB269                                       ; bf8800ec
BB218:
	v_cvt_f32_ubyte3_e32 v0, v24                                ; 7e002918
	s_mov_b32 s20, 0x3b808081                                   ; be9403ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v24                                ; 7e082318
	v_cvt_f32_ubyte1_e32 v5, v24                                ; 7e0a2518
	v_cvt_f32_ubyte2_e32 v24, v24                               ; 7e302718
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v0, s20, v0                                   ; 10000014
	v_mul_f32_e32 v4, s20, v4                                   ; 10080814
	v_mul_f32_e32 v5, s20, v5                                   ; 100a0a14
	v_mul_f32_e32 v24, s20, v24                                 ; 10303014
	s_mov_b64 s[20:21], exec                                    ; be94047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v24, v24, v0                                  ; 10300118
	v_mad_f32 v3, v9, v2, v0                                    ; d5410003 04020509
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v24, v6, v2                                   ; 3e300506
	v_rcp_f32_e32 v6, v3                                        ; 7e0c5503
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v24, v6                                   ; 100c0d18
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 10, v1                                    ; 7da2028a
	s_cbranch_execz BB262                                       ; bf8800cc
BB219:
	v_cvt_f32_ubyte3_e32 v0, v26                                ; 7e00291a
	s_mov_b32 s22, 0x3b808081                                   ; be9603ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v26                                ; 7e08231a
	v_cvt_f32_ubyte1_e32 v5, v26                                ; 7e0a251a
	v_cvt_f32_ubyte2_e32 v26, v26                               ; 7e34271a
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v13, v13, v3                                  ; 101a070d
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_mul_f32_e32 v0, s22, v0                                   ; 10000016
	v_mul_f32_e32 v4, s22, v4                                   ; 10080816
	v_mul_f32_e32 v5, s22, v5                                   ; 100a0a16
	v_mul_f32_e32 v26, s22, v26                                 ; 10343416
	s_mov_b64 s[22:23], exec                                    ; be96047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v26, v26, v0                                  ; 1034011a
	v_mad_f32 v9, v3, v2, v0                                    ; d5410009 04020503
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v26, v6, v2                                   ; 3e340506
	v_rcp_f32_e32 v6, v9                                        ; 7e0c5509
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v26, v6                                   ; 100c0d1a
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 11, v1                                    ; 7da2028b
	s_cbranch_execz BB259                                       ; bf8800ad
BB220:
	v_cvt_f32_ubyte3_e32 v0, v28                                ; 7e00291c
	s_mov_b32 s24, 0x3b808081                                   ; be9803ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v28                                ; 7e08231c
	v_cvt_f32_ubyte1_e32 v5, v28                                ; 7e0a251c
	v_cvt_f32_ubyte2_e32 v28, v28                               ; 7e38271c
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v0, s24, v0                                   ; 10000018
	v_mul_f32_e32 v4, s24, v4                                   ; 10080818
	v_mul_f32_e32 v5, s24, v5                                   ; 100a0a18
	v_mul_f32_e32 v28, s24, v28                                 ; 10383818
	s_mov_b64 s[24:25], exec                                    ; be98047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v28, v28, v0                                  ; 1038011c
	v_mad_f32 v3, v9, v2, v0                                    ; d5410003 04020509
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v28, v6, v2                                   ; 3e380506
	v_rcp_f32_e32 v6, v3                                        ; 7e0c5503
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v28, v6                                   ; 100c0d1c
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 12, v1                                    ; 7da2028c
	s_cbranch_execz BB252                                       ; bf88008d
BB221:
	v_cvt_f32_ubyte3_e32 v0, v30                                ; 7e00291e
	s_mov_b32 s26, 0x3b808081                                   ; be9a03ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v30                                ; 7e08231e
	v_cvt_f32_ubyte1_e32 v5, v30                                ; 7e0a251e
	v_cvt_f32_ubyte2_e32 v30, v30                               ; 7e3c271e
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v13, v13, v3                                  ; 101a070d
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_mul_f32_e32 v0, s26, v0                                   ; 1000001a
	v_mul_f32_e32 v4, s26, v4                                   ; 1008081a
	v_mul_f32_e32 v5, s26, v5                                   ; 100a0a1a
	v_mul_f32_e32 v30, s26, v30                                 ; 103c3c1a
	s_mov_b64 s[26:27], exec                                    ; be9a047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v30, v30, v0                                  ; 103c011e
	v_mad_f32 v9, v3, v2, v0                                    ; d5410009 04020503
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v30, v6, v2                                   ; 3e3c0506
	v_rcp_f32_e32 v6, v9                                        ; 7e0c5509
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v30, v6                                   ; 100c0d1e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 13, v1                                    ; 7da2028d
	s_cbranch_execz BB249                                       ; bf88006e
BB222:
	v_cvt_f32_ubyte3_e32 v0, v32                                ; 7e002920
	s_mov_b32 s28, 0x3b808081                                   ; be9c03ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v32                                ; 7e082320
	v_cvt_f32_ubyte1_e32 v5, v32                                ; 7e0a2520
	v_cvt_f32_ubyte2_e32 v32, v32                               ; 7e402720
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v0, s28, v0                                   ; 1000001c
	v_mul_f32_e32 v4, s28, v4                                   ; 1008081c
	v_mul_f32_e32 v5, s28, v5                                   ; 100a0a1c
	v_mul_f32_e32 v32, s28, v32                                 ; 1040401c
	s_mov_b64 s[28:29], exec                                    ; be9c047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v32, v32, v0                                  ; 10400120
	v_mad_f32 v3, v9, v2, v0                                    ; d5410003 04020509
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v32, v6, v2                                   ; 3e400506
	v_rcp_f32_e32 v6, v3                                        ; 7e0c5503
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v32, v6                                   ; 100c0d20
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 14, v1                                    ; 7da2028e
	s_cbranch_execz BB242                                       ; bf88004e
BB223:
	v_cvt_f32_ubyte3_e32 v0, v34                                ; 7e002922
	s_mov_b32 s30, 0x3b808081                                   ; be9e03ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v34                                ; 7e082322
	v_cvt_f32_ubyte1_e32 v5, v34                                ; 7e0a2522
	v_cvt_f32_ubyte2_e32 v34, v34                               ; 7e442722
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v13, v13, v3                                  ; 101a070d
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_mul_f32_e32 v0, s30, v0                                   ; 1000001e
	v_mul_f32_e32 v4, s30, v4                                   ; 1008081e
	v_mul_f32_e32 v5, s30, v5                                   ; 100a0a1e
	v_mul_f32_e32 v34, s30, v34                                 ; 1044441e
	s_mov_b64 s[30:31], exec                                    ; be9e047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v34, v34, v0                                  ; 10440122
	v_mad_f32 v9, v3, v2, v0                                    ; d5410009 04020503
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v34, v6, v2                                   ; 3e440506
	v_rcp_f32_e32 v6, v9                                        ; 7e0c5509
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	v_mul_f32_e32 v6, v34, v6                                   ; 100c0d22
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_u32_e32 15, v1                                    ; 7da2028f
	s_cbranch_execz BB239                                       ; bf88002f
BB224:
	v_cvt_f32_ubyte3_e32 v0, v36                                ; 7e002924
	s_mov_b32 s32, 0x3b808081                                   ; bea003ff 3b808081
	v_cvt_f32_ubyte0_e32 v4, v36                                ; 7e082324
	v_cvt_f32_ubyte1_e32 v5, v36                                ; 7e0a2524
	v_cvt_f32_ubyte2_e32 v36, v36                               ; 7e482724
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v0, s32, v0                                   ; 10000020
	v_mul_f32_e32 v4, s32, v4                                   ; 10080820
	v_mul_f32_e32 v5, s32, v5                                   ; 100a0a20
	s_mov_b32 s34, 16                                           ; bea20390
	v_mul_f32_e32 v36, s32, v36                                 ; 10484820
	s_mov_b64 s[32:33], exec                                    ; bea0047e
	s_mov_b64 s[36:37], exec                                    ; bea4047e
	v_sub_f32_e32 v2, 1.0, v0                                   ; 080400f2
	v_mul_f32_e32 v4, v4, v0                                    ; 10080104
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v36, v36, v0                                  ; 10480124
	v_mad_f32 v3, v9, v2, v0                                    ; d5410003 04020509
	v_mac_f32_e32 v4, v11, v2                                   ; 3e08050b
	v_mac_f32_e32 v5, v13, v2                                   ; 3e0a050d
	v_mac_f32_e32 v36, v6, v2                                   ; 3e480506
	v_rcp_f32_e32 v6, v3                                        ; 7e0c5503
	v_mul_f32_e32 v36, v36, v6                                  ; 10480d24
	v_mul_f32_e32 v11, v4, v6                                   ; 10160d04
	v_mul_f32_e32 v13, v5, v6                                   ; 101a0d05
	s_nop 0                                                     ; bf800000
	(then repeated 1 times)
BB225:
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_ge_u32_e32 s34, v1                                   ; 7dac0222
BB226:
	s_andn2_b64 s[36:37], s[36:37], exec                        ; 8aa47e24
	s_cbranch_scc0 BB234                                        ; bf840009
BB233:
	s_mov_b64 exec, s[36:37]                                    ; befe0424
	s_add_u32 s34, s34, 1                                       ; 80228122
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v13, v13, v3                                  ; 101a070d
	v_mul_f32_e32 v36, v36, v3                                  ; 10480724
	v_mul_f32_e32 v11, v11, v6                                  ; 10160d0b
	v_mul_f32_e32 v13, v13, v6                                  ; 101a0d0d
	v_mul_f32_e32 v36, v36, v6                                  ; 10480d24
	s_branch BB225                                              ; bf82fff3
BB234:
	s_mov_b64 exec, s[32:33]                                    ; befe0420
	v_mov_b32_e32 v6, v36                                       ; 7e0c0324
	v_mov_b32_e32 v9, v3                                        ; 7e120303
BB239:
	s_mov_b64 exec, s[30:31]                                    ; befe041e
BB242:
	s_andn2_b64 exec, s[28:29], exec                            ; 8afe7e1c
	v_mov_b32_e32 v9, v3                                        ; 7e120303
BB249:
	s_mov_b64 exec, s[26:27]                                    ; befe041a
BB252:
	s_andn2_b64 exec, s[24:25], exec                            ; 8afe7e18
	v_mov_b32_e32 v9, v3                                        ; 7e120303
BB259:
	s_mov_b64 exec, s[22:23]                                    ; befe0416
BB262:
	s_andn2_b64 exec, s[20:21], exec                            ; 8afe7e14
	v_mov_b32_e32 v9, v3                                        ; 7e120303
BB269:
	s_mov_b64 exec, s[18:19]                                    ; befe0412
BB272:
	s_andn2_b64 exec, s[16:17], exec                            ; 8afe7e10
	v_mov_b32_e32 v9, v3                                        ; 7e120303
BB279:
	s_mov_b64 exec, s[14:15]                                    ; befe040e
BB282:
	s_andn2_b64 exec, s[12:13], exec                            ; 8afe7e0c
	v_mov_b32_e32 v9, v3                                        ; 7e120303
BB289:
	s_mov_b64 exec, s[10:11]                                    ; befe040a
BB292:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	v_mov_b32_e32 v9, v3                                        ; 7e120303
BB299:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
BB302:
	s_andn2_b64 exec, s[2:3], exec                              ; 8afe7e02
	v_mov_b32_e32 v9, v3                                        ; 7e120303
BB309:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
BB312:
	s_andn2_b64 exec, s[4:5], exec                              ; 8afe7e04
	v_mov_b32_e32 v6, 0                                         ; 7e0c0280
	v_mov_b32_e32 v9, 0                                         ; 7e120280
	v_mov_b32_e32 v11, 0                                        ; 7e160280
	v_mov_b32_e32 v13, 0                                        ; 7e1a0280
BB314:
	s_mov_b64 exec, s[4:5]                                      ; befe0404
	s_branch BB326                                              ; bf820031
BB315:
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_mov_b32_e32 v6, 0                                         ; 7e0c0280
	v_mov_b32_e32 v9, 0                                         ; 7e120280
	v_mov_b32_e32 v11, 0                                        ; 7e160280
	v_mov_b32_e32 v13, 0                                        ; 7e1a0280
BB316:
	s_mov_b64 s[4:5], exec                                      ; be84047e
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_eq_i32_e32 -1, v1                                    ; 7d2402c1
BB317:
	s_andn2_b64 s[4:5], s[4:5], exec                            ; 8a847e04
	s_cbranch_scc0 BB325                                        ; bf840025
BB324:
	s_mov_b64 exec, s[4:5]                                      ; befe0404
	s_load_dwordx4 s[4:7], s[2:3], 0x30                         ; f4080101 fa000030
	v_lshlrev_b32_e32 v1, 4, v1                                 ; 34020284
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	buffer_load_dwordx2 v[1:2], v1, s[4:7], 0 offen             ; e0341000 80010101
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b32 s4, 0x3b808081                                    ; be8403ff 3b808081
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v13, v13, v9                                  ; 101a130d
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_f32_ubyte3_e32 v0, v2                                 ; 7e002902
	v_cvt_f32_ubyte0_e32 v5, v2                                 ; 7e0a2302
	v_cvt_f32_ubyte1_e32 v7, v2                                 ; 7e0e2502
	v_cvt_f32_ubyte2_e32 v2, v2                                 ; 7e042702
	v_mul_f32_e32 v0, s4, v0                                    ; 10000004
	v_mul_f32_e32 v5, s4, v5                                    ; 100a0a04
	v_mul_f32_e32 v7, s4, v7                                    ; 100e0e04
	v_mul_f32_e32 v2, s4, v2                                    ; 10040404
	v_sub_f32_e32 v3, 1.0, v0                                   ; 080600f2
	v_mul_f32_e32 v5, v5, v0                                    ; 100a0105
	v_mul_f32_e32 v7, v7, v0                                    ; 100e0107
	v_mul_f32_e32 v2, v2, v0                                    ; 10040102
	v_mad_f32 v4, v9, v3, v0                                    ; d5410004 04020709
	v_mac_f32_e32 v5, v11, v3                                   ; 3e0a070b
	v_mac_f32_e32 v7, v13, v3                                   ; 3e0e070d
	v_mac_f32_e32 v2, v6, v3                                    ; 3e040706
	v_rcp_f32_e32 v8, v4                                        ; 7e105504
	v_mov_b32_e32 v9, v4                                        ; 7e120304
	v_mul_f32_e32 v6, v2, v8                                    ; 100c1102
	v_mul_f32_e32 v11, v5, v8                                   ; 10161105
	v_mul_f32_e32 v13, v7, v8                                   ; 101a1107
	s_branch BB316                                              ; bf82ffd5
BB325:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
BB326:
	v_cvt_pkrtz_f16_f32_e32 v11, v11, v13                       ; 5e161b0b
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v9                          ; 5e0c1306
	exp mrt0 v11, v11, v6, v6 done compr vm                     ; f8001c0f 8080060b
	s_endpgm                                                    ; bf810000
