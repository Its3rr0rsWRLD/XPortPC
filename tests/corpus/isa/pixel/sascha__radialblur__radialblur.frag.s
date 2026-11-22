# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x70                       ; f4080401 fa000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx4 s[4:7], s[4:7], null                  ; f4280102 fa000000
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	s_bfe_u32 s1, s9, 0x2001e                                   ; 9381ff09 0002001e
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	s_add_u32 s1, s1, 1                                         ; 80018101
	s_and_b32 s2, s10, 0x3fff                                   ; 8702ff0a 00003fff
	s_lshl2_add_u32 s2, s2, s1                                  ; 97820102
	s_bfe_u32 s27, s11, 0x4000c                                 ; 939bff0b 0004000c
	s_lshr_b32 s2, s2, s27                                      ; 90021b02
	s_bfe_u32 s26, s10, 0x10000e                                ; 939aff0a 0010000e
	s_add_u32 s26, s26, 1                                       ; 801a811a
	s_lshr_b32 s26, s26, s27                                    ; 901a1b1a
	s_max_u32 s2, s2, 1                                         ; 84828102
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v6, s4, neg(0x3d042108), 1.0                      ; d5410006 43c9fe04 3d042108
	s_cselect_b32 s2, 0, s2                                     ; 85020280
	s_max_u32 s26, s26, 1                                       ; 849a811a
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	v_mad_f32 v7, s4, neg(0x3d842108), 1.0                      ; d5410007 43c9fe04 3d842108
	v_cvt_f32_i32_e32 v3, s2                                    ; 7e060a02
	v_mad_f32 v12, s4, neg(0x3dc6318c), 1.0                     ; d541000c 43c9fe04 3dc6318c
	s_cselect_b32 s26, 0, s26                                   ; 851a1a80
	v_mad_f32 v13, s4, neg(0x3e042108), 1.0                     ; d541000d 43c9fe04 3e042108
	v_cvt_f32_i32_e32 v4, s26                                   ; 7e080a1a
	v_rcp_f32_e64 v3, v3 div:2                                  ; d5aa0003 18000103
	v_mad_f32 v16, s4, neg(0x3e25294a), 1.0                     ; d5410010 43c9fe04 3e25294a
	v_rcp_f32_e64 v4, v4 div:2                                  ; d5aa0004 18000104
	v_subrev_f32_e32 v3, s6, v3                                 ; 0a060606
	v_mad_f32 v17, s4, neg(0x3e46318c), 1.0                     ; d5410011 43c9fe04 3e46318c
	v_subrev_f32_e32 v4, s7, v4                                 ; 0a080807
	v_add_f32_e32 v2, v2, v3                                    ; 06040702
	v_mad_f32 v20, s4, neg(0x3e6739ce), 1.0                     ; d5410014 43c9fe04 3e6739ce
	v_add_f32_e32 v0, v0, v4                                    ; 06000900
	v_mad_f32 v8, v2, v6, s6                                    ; d5410008 001a0d02
	v_add_f32_e32 v4, s6, v2                                    ; 06080406
	v_mad_f32 v14, v2, v13, s6                                  ; d541000e 001a1b02
	v_mad_f32 v10, v2, v7, s6                                   ; d541000a 001a0f02
	v_mad_f32 v18, v2, v17, s6                                  ; d5410012 001a2302
	v_mad_f32 v19, v0, v17, s7                                  ; d5410013 001e2300
	v_mad_f32 v17, v0, v20, s7                                  ; d5410011 001e2900
	v_add_f32_e32 v5, s7, v0                                    ; 060a0007
	v_mad_f32 v9, v0, v6, s7                                    ; d5410009 001e0d00
	v_mad_f32 v6, v2, v12, s6                                   ; d5410006 001a1902
	v_mad_f32 v11, v0, v7, s7                                   ; d541000b 001e0f00
	v_mad_f32 v7, v0, v12, s7                                   ; d5410007 001e1900
	v_mad_f32 v12, v2, v16, s6                                  ; d541000c 001a2102
	v_mad_f32 v15, v0, v13, s7                                  ; d541000f 001e1b00
	v_mad_f32 v13, v0, v16, s7                                  ; d541000d 001e2100
	v_mad_f32 v16, v2, v20, s6                                  ; d5410010 001a2902
	s_clause 0x7                                                ; bfa10007
	image_sample v[20:23], v[4:5], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821404
	image_sample v[24:27], v[8:9], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821808
	image_sample v[8:11], v[10:11], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 0082080a
	image_sample v[4:7], v[6:7], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820406
	image_sample v[28:31], v[14:15], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821c0e
	image_sample v[12:15], v[12:13], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820c0c
	image_sample v[32:35], v[18:19], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00822012
	image_sample v[16:19], v[16:17], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821010
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v20, v20, v24                                 ; 06283114
	v_mad_f32 v24, s4, neg(0x3e842108), 1.0                     ; d5410018 43c9fe04 3e842108
	v_add_f32_e32 v23, v23, v27                                 ; 062e3717
	v_add_f32_e32 v22, v22, v26                                 ; 062c3516
	v_add_f32_e32 v21, v21, v25                                 ; 062a3315
	v_mad_f32 v25, s4, neg(0x3e94a529), 1.0                     ; d5410019 43c9fe04 3e94a529
	v_mad_f32 v1, s4, neg(0x3ea5294a), 1.0                      ; d5410001 43c9fe04 3ea5294a
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v20, v20, v8                                  ; 06281114
	v_mad_f32 v26, v2, v24, s6                                  ; d541001a 001a3102
	v_mad_f32 v27, v0, v24, s7                                  ; d541001b 001e3100
	v_add_f32_e32 v23, v23, v11                                 ; 062e1717
	v_add_f32_e32 v22, v22, v10                                 ; 062c1516
	v_add_f32_e32 v21, v21, v9                                  ; 062a1315
	v_mad_f32 v9, v0, v25, s7                                   ; d5410009 001e3300
	v_mad_f32 v8, v2, v25, s6                                   ; d5410008 001a3302
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v20, v20, v4                                  ; 06280914
	v_mad_f32 v4, v2, v1, s6                                    ; d5410004 001a0302
	v_add_f32_e32 v23, v23, v7                                  ; 062e0f17
	v_add_f32_e32 v22, v22, v6                                  ; 062c0d16
	v_add_f32_e32 v21, v21, v5                                  ; 062a0b15
	v_mad_f32 v5, v0, v1, s7                                    ; d5410005 001e0300
	s_clause 0x2                                                ; bfa10002
	image_sample v[24:27], v[26:27], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 0082181a
	image_sample v[8:11], v[8:9], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820808
	image_sample v[4:7], v[4:5], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820404
	v_mad_f32 v3, s4, neg(0x3eb5ad6b), 1.0                      ; d5410003 43c9fe04 3eb5ad6b
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v20, v20, v28                                 ; 06283914
	v_add_f32_e32 v23, v23, v31                                 ; 062e3f17
	v_add_f32_e32 v22, v22, v30                                 ; 062c3d16
	v_add_f32_e32 v21, v21, v29                                 ; 062a3b15
	v_mad_f32 v28, v2, v3, s6                                   ; d541001c 001a0702
	v_mad_f32 v29, v0, v3, s7                                   ; d541001d 001e0700
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v20, v20, v12                                 ; 06281914
	v_mad_f32 v12, s4, neg(0x3ec6318c), 1.0                     ; d541000c 43c9fe04 3ec6318c
	v_add_f32_e32 v23, v23, v15                                 ; 062e1f17
	v_add_f32_e32 v22, v22, v14                                 ; 062c1d16
	v_add_f32_e32 v21, v21, v13                                 ; 062a1b15
	v_mad_f32 v13, s4, neg(0x3ed6b5ad), 1.0                     ; d541000d 43c9fe04 3ed6b5ad
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v20, v20, v32                                 ; 06284114
	v_mad_f32 v14, v2, v12, s6                                  ; d541000e 001a1902
	v_mad_f32 v15, v0, v12, s7                                  ; d541000f 001e1900
	v_add_f32_e32 v23, v23, v35                                 ; 062e4717
	v_add_f32_e32 v22, v22, v34                                 ; 062c4516
	v_add_f32_e32 v21, v21, v33                                 ; 062a4315
	v_mad_f32 v30, v2, v13, s6                                  ; d541001e 001a1b02
	v_mad_f32 v31, v0, v13, s7                                  ; d541001f 001e1b00
	s_clause 0x2                                                ; bfa10002
	image_sample v[32:35], v[28:29], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 0082201c
	image_sample v[12:15], v[14:15], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820c0e
	image_sample v[28:31], v[30:31], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821c1e
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	v_mad_f32 v16, s4, neg(0x3ee739ce), 1.0                     ; d5410010 43c9fe04 3ee739ce
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	v_mad_f32 v17, s4, neg(0x3ef7bdef), 1.0                     ; d5410011 43c9fe04 3ef7bdef
	v_mad_f32 v18, v2, v16, s6                                  ; d5410012 001a2102
	v_mad_f32 v19, v0, v16, s7                                  ; d5410013 001e2100
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v22, v22, v26                                 ; 062c3516
	v_mad_f32 v26, s4, neg(0x3f042108), 1.0                     ; d541001a 43c9fe04 3f042108
	v_add_f32_e32 v23, v23, v27                                 ; 062e3717
	v_add_f32_e32 v20, v20, v24                                 ; 06283114
	v_mad_f32 v24, v2, v17, s6                                  ; d5410018 001a2302
	v_add_f32_e32 v21, v21, v25                                 ; 062a3315
	v_mad_f32 v25, v0, v17, s7                                  ; d5410019 001e2300
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v22, v22, v10                                 ; 062c1516
	v_add_f32_e32 v23, v23, v11                                 ; 062e1717
	v_add_f32_e32 v20, v20, v8                                  ; 06281114
	v_mad_f32 v8, v2, v26, s6                                   ; d5410008 001a3502
	v_add_f32_e32 v21, v21, v9                                  ; 062a1315
	v_mad_f32 v9, v0, v26, s7                                   ; d5410009 001e3500
	s_clause 0x2                                                ; bfa10002
	image_sample v[16:19], v[18:19], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821012
	image_sample v[24:27], v[24:25], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821818
	image_sample v[8:11], v[8:9], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820808
	v_mad_f32 v1, s4, neg(0x3f0c6318), 1.0                      ; d5410001 43c9fe04 3f0c6318
	v_mad_f32 v3, s4, neg(0x3f14a529), 1.0                      ; d5410003 43c9fe04 3f14a529
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v22, v22, v6                                  ; 062c0d16
	v_add_f32_e32 v23, v23, v7                                  ; 062e0f17
	v_add_f32_e32 v20, v20, v4                                  ; 06280914
	v_add_f32_e32 v21, v21, v5                                  ; 062a0b15
	v_mad_f32 v5, v0, v1, s7                                    ; d5410005 001e0300
	v_mad_f32 v4, v2, v1, s6                                    ; d5410004 001a0302
	v_mad_f32 v6, v2, v3, s6                                    ; d5410006 001a0702
	v_mad_f32 v7, v0, v3, s7                                    ; d5410007 001e0700
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v23, v23, v35                                 ; 062e4717
	v_add_f32_e32 v22, v22, v34                                 ; 062c4516
	v_add_f32_e32 v20, v20, v32                                 ; 06284114
	v_add_f32_e32 v21, v21, v33                                 ; 062a4315
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v23, v23, v15                                 ; 062e1f17
	v_add_f32_e32 v22, v22, v14                                 ; 062c1d16
	v_add_f32_e32 v20, v20, v12                                 ; 06281914
	v_mad_f32 v12, s4, neg(0x3f1ce73a), 1.0                     ; d541000c 43c9fe04 3f1ce73a
	v_add_f32_e32 v21, v21, v13                                 ; 062a1b15
	v_mad_f32 v15, v0, v12, s7                                  ; d541000f 001e1900
	v_mad_f32 v14, v2, v12, s6                                  ; d541000e 001a1902
	s_clause 0x2                                                ; bfa10002
	image_sample v[32:35], v[4:5], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00822004
	image_sample v[4:7], v[6:7], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820406
	image_sample v[12:15], v[14:15], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820c0e
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v23, v23, v31                                 ; 062e3f17
	v_add_f32_e32 v22, v22, v30                                 ; 062c3d16
	v_add_f32_e32 v20, v20, v28                                 ; 06283914
	v_mad_f32 v28, s4, neg(0x3f25294a), 1.0                     ; d541001c 43c9fe04 3f25294a
	v_add_f32_e32 v21, v21, v29                                 ; 062a3b15
	v_mad_f32 v29, s4, neg(0x3f2d6b5a), 1.0                     ; d541001d 43c9fe04 3f2d6b5a
	v_mad_f32 v1, s4, neg(0x3f35ad6b), 1.0                      ; d5410001 43c9fe04 3f35ad6b
	v_mad_f32 v31, v0, v28, s7                                  ; d541001f 001e3900
	v_mad_f32 v30, v2, v28, s6                                  ; d541001e 001a3902
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	v_mad_f32 v18, v2, v1, s6                                   ; d5410012 001a0302
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	v_mad_f32 v17, v0, v29, s7                                  ; d5410011 001e3b00
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	v_mad_f32 v19, v0, v1, s7                                   ; d5410013 001e0300
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	v_mad_f32 v16, v2, v29, s6                                  ; d5410010 001a3b02
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v22, v22, v26                                 ; 062c3516
	v_add_f32_e32 v21, v21, v25                                 ; 062a3315
	v_add_f32_e32 v23, v23, v27                                 ; 062e3717
	v_add_f32_e32 v20, v20, v24                                 ; 06283114
	s_clause 0x2                                                ; bfa10002
	image_sample v[24:27], v[30:31], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 0082181e
	image_sample v[28:31], v[16:17], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821c10
	image_sample v[16:19], v[18:19], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821012
	v_mad_f32 v3, s4, neg(0x3f3def7c), 1.0                      ; d5410003 43c9fe04 3f3def7c
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v22, v22, v10                                 ; 062c1516
	v_mad_f32 v10, s4, neg(0x3f46318c), 1.0                     ; d541000a 43c9fe04 3f46318c
	v_add_f32_e32 v21, v21, v9                                  ; 062a1315
	v_add_f32_e32 v23, v23, v11                                 ; 062e1717
	v_add_f32_e32 v20, v20, v8                                  ; 06281114
	v_mad_f32 v11, s4, neg(0x3f4e739c), 1.0                     ; d541000b 43c9fe04 3f4e739c
	v_mad_f32 v8, v2, v3, s6                                    ; d5410008 001a0702
	v_mad_f32 v9, v0, v3, s7                                    ; d5410009 001e0700
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v21, v21, v33                                 ; 062a4315
	v_mad_f32 v33, v0, v10, s7                                  ; d5410021 001e1500
	v_add_f32_e32 v23, v23, v35                                 ; 062e4717
	v_add_f32_e32 v20, v20, v32                                 ; 06284114
	v_mad_f32 v32, v2, v10, s6                                  ; d5410020 001a1502
	v_add_f32_e32 v22, v22, v34                                 ; 062c4516
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v21, v21, v5                                  ; 062a0b15
	v_mad_f32 v5, v0, v11, s7                                   ; d5410005 001e1700
	v_add_f32_e32 v23, v23, v7                                  ; 062e0f17
	v_add_f32_e32 v20, v20, v4                                  ; 06280914
	v_mad_f32 v4, v2, v11, s6                                   ; d5410004 001a1702
	v_add_f32_e32 v22, v22, v6                                  ; 062c0d16
	s_clause 0x2                                                ; bfa10002
	image_sample v[8:11], v[8:9], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820808
	image_sample v[32:35], v[32:33], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00822020
	image_sample v[4:7], v[4:5], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820404
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v21, v21, v13                                 ; 062a1b15
	v_mad_f32 v13, s4, neg(0x3f5ef7be), 1.0                     ; d541000d 43c9fe04 3f5ef7be
	v_add_f32_e32 v23, v23, v15                                 ; 062e1f17
	v_add_f32_e32 v20, v20, v12                                 ; 06281914
	v_mad_f32 v12, s4, neg(0x3f56b5ad), 1.0                     ; d541000c 43c9fe04 3f56b5ad
	v_add_f32_e32 v22, v22, v14                                 ; 062c1d16
	v_mad_f32 v14, v2, v12, s6                                  ; d541000e 001a1902
	v_mad_f32 v15, v0, v12, s7                                  ; d541000f 001e1900
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v20, v20, v24                                 ; 06283114
	v_mad_f32 v24, v2, v13, s6                                  ; d5410018 001a1b02
	v_add_f32_e32 v22, v22, v26                                 ; 062c3516
	v_mad_f32 v26, s4, neg(0x3f6739ce), 1.0                     ; d541001a 43c9fe04 3f6739ce
	v_add_f32_e32 v23, v23, v27                                 ; 062e3717
	v_add_f32_e32 v21, v21, v25                                 ; 062a3315
	v_mad_f32 v25, v0, v13, s7                                  ; d5410019 001e1b00
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v20, v20, v28                                 ; 06283914
	v_add_f32_e32 v22, v22, v30                                 ; 062c3d16
	v_mad_f32 v12, v2, v26, s6                                  ; d541000c 001a3502
	v_mad_f32 v13, v0, v26, s7                                  ; d541000d 001e3500
	v_add_f32_e32 v23, v23, v31                                 ; 062e3f17
	v_add_f32_e32 v21, v21, v29                                 ; 062a3b15
	s_clause 0x2                                                ; bfa10002
	image_sample v[28:31], v[14:15], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821c0e
	image_sample v[24:27], v[24:25], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821818
	image_sample v[12:15], v[12:13], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820c0c
	v_mad_f32 v1, s4, neg(0x3f6f7bde), 1.0                      ; d5410001 43c9fe04 3f6f7bde
	v_mad_f32 v3, s4, neg(0x3f77bdef), 1.0                      ; d5410003 43c9fe04 3f77bdef
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	v_mad_f32 v17, v0, v1, s7                                   ; d5410011 001e0300
	v_mad_f32 v16, v2, v1, s6                                   ; d5410010 001a0302
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v22, v22, v10                                 ; 062c1516
	v_sub_f32_e64 v10, 1.0, s4                                  ; d504000a 000008f2
	v_add_f32_e32 v20, v20, v8                                  ; 06281114
	v_mad_f32 v8, v2, v3, s6                                    ; d5410008 001a0702
	v_add_f32_e32 v21, v21, v9                                  ; 062a1315
	v_mad_f32 v9, v0, v3, s7                                    ; d5410009 001e0700
	v_add_f32_e32 v23, v23, v11                                 ; 062e1717
	v_mad_f32 v2, v2, v10, s6                                   ; d5410002 001a1502
	v_mad_f32 v3, v0, v10, s7                                   ; d5410003 001e1500
	s_clause 0x2                                                ; bfa10002
	image_sample v[16:19], v[16:17], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00821010
	image_sample v[8:11], v[8:9], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820808
	image_sample v[0:3], v[2:3], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00820002
	s_mov_b32 s4, 0x3d000000                                    ; be8403ff 3d000000
	s_waitcnt vmcnt(7)                                          ; bf8c3f77
	v_add_f32_e32 v22, v22, v34                                 ; 062c4516
	v_add_f32_e32 v20, v20, v32                                 ; 06284114
	v_add_f32_e32 v21, v21, v33                                 ; 062a4315
	v_add_f32_e32 v23, v23, v35                                 ; 062e4717
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v22, v22, v6                                  ; 062c0d16
	v_add_f32_e32 v20, v20, v4                                  ; 06280914
	v_add_f32_e32 v21, v21, v5                                  ; 062a0b15
	v_add_f32_e32 v23, v23, v7                                  ; 062e0f17
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v20, v20, v28                                 ; 06283914
	v_add_f32_e32 v22, v22, v30                                 ; 062c3d16
	v_add_f32_e32 v23, v23, v31                                 ; 062e3f17
	v_add_f32_e32 v21, v21, v29                                 ; 062a3b15
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v20, v20, v24                                 ; 06283114
	v_add_f32_e32 v22, v22, v26                                 ; 062c3516
	v_add_f32_e32 v23, v23, v27                                 ; 062e3717
	v_add_f32_e32 v21, v21, v25                                 ; 062a3315
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v20, v20, v12                                 ; 06281914
	v_add_f32_e32 v22, v22, v14                                 ; 062c1d16
	v_add_f32_e32 v23, v23, v15                                 ; 062e1f17
	v_add_f32_e32 v21, v21, v13                                 ; 062a1b15
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v21, v21, v9                                  ; 062a1315
	v_add_f32_e32 v20, v20, v8                                  ; 06281114
	v_add_f32_e32 v22, v22, v10                                 ; 062c1516
	v_add_f32_e32 v23, v23, v11                                 ; 062e1717
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v21, v21, v1                                  ; 062a0315
	v_add_f32_e32 v20, v20, v0                                  ; 06280114
	v_add_f32_e32 v22, v22, v2                                  ; 062c0516
	v_add_f32_e32 v23, v23, v3                                  ; 062e0717
	v_mul_f32_e32 v21, s4, v21                                  ; 102a2a04
	v_mul_f32_e32 v20, s4, v20                                  ; 10282804
	v_mul_f32_e32 v22, s4, v22                                  ; 102c2c04
	v_mul_f32_e32 v23, s4, v23                                  ; 102e2e04
	v_fma_mixlo_f16 v11, s5, v20, neg(0) op_sel_hi:[0,0,1]      ; cc21400b 82022805
	v_fma_mixhi_f16 v11, s5, v21, neg(0) op_sel_hi:[0,0,1]      ; cc22400b 82022a05
	v_fma_mixlo_f16 v12, s5, v22, neg(0) op_sel_hi:[0,0,1]      ; cc21400c 82022c05
	v_fma_mixhi_f16 v12, s5, v23, neg(0) op_sel_hi:[0,0,1]      ; cc22400c 82022e05
	exp mrt0 v11, v11, v12, v12 done compr vm                   ; f8001c0f 80800c0b
	s_endpgm                                                    ; bf810000
