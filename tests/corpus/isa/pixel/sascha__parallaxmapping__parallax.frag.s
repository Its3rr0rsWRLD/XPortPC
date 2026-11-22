# Pixel Shader
BB0:
	s_mov_b32 s4, s3                                            ; be840303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[8:11], s[2:3], 0xd0                        ; f4080201 fa0000d0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s5, s[8:11], 0xc                        ; f4200144 fa00000c
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v6, v0, attr0.y                         ; c8180100
	v_interp_p1_f32_e32 v7, v0, attr0.x                         ; c81c0000
	v_interp_p1_f32_e32 v2, v0, attr1.z                         ; c8080600
	v_interp_p1_f32_e32 v4, v0, attr1.w                         ; c8100700
	v_interp_p1_f32_e32 v5, v0, attr1.y                         ; c8140500
	v_interp_p2_f32_e32 v6, v1, attr0.y                         ; c8190101
	v_interp_p2_f32_e32 v7, v1, attr0.x                         ; c81d0001
	v_interp_p2_f32_e32 v2, v1, attr1.z                         ; c8090601
	v_interp_p2_f32_e32 v4, v1, attr1.w                         ; c8110701
	v_interp_p2_f32_e32 v5, v1, attr1.y                         ; c8150501
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_eq_i32 s5, 0                                          ; bf008005
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	s_cbranch_scc0 BB2                                          ; bf84000a
BB1:
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[0:3], [v7, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220007 00000006
	s_branch BB38                                               ; bf8200e8
BB2:
	s_cmp_eq_i32 s5, 2                                          ; bf008205
	s_cbranch_scc0 BB4                                          ; bf84001a
BB3:
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[16:23], s[2:3], 0x60                       ; f40c0401 fa000060
	s_load_dwordx4 s[12:15], s[2:3], 0xb0                       ; f4080301 fa0000b0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_lz  v3, [v7, v6], s[16:23], s[12:15] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f09c080a 00640307 00000006
	s_buffer_load_dwordx2 s[6:7], s[8:11], null                 ; f4240184 fa000000
	v_rcp_f32_e32 v8, v4                                        ; 7e105504
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v9, s6, 0.5                                   ; d5080009 0001e006
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_sub_f32_e32 v3, 1.0, v3                                   ; 080606f2
	v_mad_f32 v3, v3, v9, s7                                    ; d5410003 001e1303
	v_mul_f32_e32 v10, v5, v3                                   ; 10140705
	v_mul_f32_e32 v3, v2, v3                                    ; 10060702
	v_mad_f32 v10, v10, -v8, v7                                 ; d541000a 441e110a
	v_mad_f32 v11, v3, -v8, v6                                  ; d541000b 441a1103
	s_branch BB5                                                ; bf820002
BB4:
	v_mov_b32_e32 v10, v7                                       ; 7e140307
	v_mov_b32_e32 v11, v6                                       ; 7e160306
BB5:
	s_cmp_eq_i32 s5, 3                                          ; bf008305
	s_cbranch_scc0 BB21                                         ; bf840030
BB6:
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dword s4, s[8:11], null                       ; f4200104 fa000000
	s_buffer_load_dword s6, s[8:11], 0x8                        ; f4200184 fa000008
	s_mov_b64 s[12:13], exec                                    ; be8c047e
	v_mov_b32_e32 v11, v6                                       ; 7e160306
	v_mov_b32_e32 v12, 0                                        ; 7e180280
	v_mov_b32_e32 v13, v7                                       ; 7e1a0307
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v3, s4, v5                                    ; 10060a04
	v_mul_f32_e32 v8, s4, v2                                    ; 10100404
	s_mov_b32 s4, 0                                             ; be840380
	v_mul_f32_e32 v9, s6, v4                                    ; 10120806
	v_rcp_f32_e32 v10, s6                                       ; 7e145406
	v_rcp_f32_e32 v9, v9                                        ; 7e125509
BB7:
	v_cvt_f32_i32_e32 v14, s4                                   ; 7e1c0a04
	v_cmp_ngt_f32_e32 vcc, s6, v14                              ; 7c161c06
	s_cbranch_vccz BB10                                         ; bf860002
BB8:
	v_mov_b32_e32 v10, v13                                      ; 7e14030d
	s_branch BB19                                               ; bf82001a
BB10:
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[16:23], s[2:3], 0x60                       ; f40c0401 fa000060
	s_load_dwordx4 s[24:27], s[2:3], 0xb0                       ; f4080601 fa0000b0
	v_mad_f32 v14, v3, -v9, v13                                 ; d541000e 44361303
	v_mad_f32 v11, v8, -v9, v11                                 ; d541000b 442e1308
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_lz  v13, [v14, v11], s[16:23], s[24:27] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f09c080a 00c40d0e 0000000b
	v_add_f32_e32 v12, v12, v10                                 ; 0618150c
	s_mov_b64 s[14:15], exec                                    ; be8e047e
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_sub_f32_e32 v13, 1.0, v13                                 ; 081a1af2
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 v13, v12                                  ; 7c22190d
BB11:
	v_mov_b32_e32 v10, v14                                      ; 7e14030e
	s_andn2_b64 s[14:15], s[14:15], exec                        ; 8a8e7e0e
	s_cbranch_scc0 BB19                                         ; bf840004
BB18:
	s_mov_b64 exec, s[14:15]                                    ; befe040e
	s_add_u32 s4, s4, 1                                         ; 80048104
	v_mov_b32_e32 v13, v14                                      ; 7e1a030e
	s_branch BB7                                                ; bf82ffe1
BB19:
	s_mov_b64 exec, s[12:13]                                    ; befe040c
BB21:
	s_cmp_eq_i32 s5, 4                                          ; bf008405
	s_cbranch_scc0 BB37                                         ; bf840043
BB22:
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[16:23], s[2:3], 0x60                       ; f40c0401 fa000060
	s_load_dwordx4 s[4:7], s[2:3], 0xb0                         ; f4080101 fa0000b0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_lz  v3, [v7, v6], s[16:23], s[4:7] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f09c080a 00240307 00000006
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dword s12, s[8:11], null                      ; f4200304 fa000000
	s_buffer_load_dword s13, s[8:11], 0x8                       ; f4200344 fa000008
	s_mov_b64 s[8:9], exec                                      ; be88047e
	s_mov_b32 s10, 0                                            ; be8a0380
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v8, s12, v5                                   ; 10100a0c
	v_mul_f32_e32 v9, s12, v2                                   ; 1012040c
	v_mul_f32_e32 v10, s13, v4                                  ; 1014080d
	v_rcp_f32_e32 v11, s13                                      ; 7e16540d
	v_rcp_f32_e32 v10, v10                                      ; 7e14550a
	v_mul_f32_e32 v8, v8, v10                                   ; 10101508
	v_mul_f32_e32 v9, v9, v10                                   ; 10121509
	v_mov_b32_e32 v10, 0                                        ; 7e140280
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_sub_f32_e32 v3, 1.0, v3                                   ; 080606f2
BB23:
	v_cvt_f32_i32_e32 v12, s10                                  ; 7e180a0a
	v_cmp_ngt_f32_e32 vcc, s13, v12                             ; 7c16180d
	s_cbranch_vccz BB26                                         ; bf860003
BB24:
	v_mov_b32_e32 v12, v7                                       ; 7e180307
	v_mov_b32_e32 v13, v6                                       ; 7e1a0306
	s_branch BB35                                               ; bf820011
BB26:
	v_sub_f32_e32 v12, v7, v8                                   ; 08181107
	v_sub_f32_e32 v13, v6, v9                                   ; 081a1306
	image_sample_lz v3, v[12:13], s[16:23], s[4:7] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f09c0808 0024030c
	v_add_f32_e32 v10, v10, v11                                 ; 0614170a
	s_mov_b64 s[14:15], exec                                    ; be8e047e
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_sub_f32_e32 v3, 1.0, v3                                   ; 080606f2
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 v3, v10                                   ; 7c221503
BB27:
	s_andn2_b64 s[14:15], s[14:15], exec                        ; 8a8e7e0e
	s_cbranch_scc0 BB35                                         ; bf840005
BB34:
	s_mov_b64 exec, s[14:15]                                    ; befe040e
	s_add_u32 s10, s10, 1                                       ; 800a810a
	v_mov_b32_e32 v6, v13                                       ; 7e0c030d
	v_mov_b32_e32 v7, v12                                       ; 7e0e030c
	s_branch BB23                                               ; bf82ffe9
BB35:
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	v_add_f32_e32 v6, v12, v8                                   ; 060c110c
	v_add_f32_e32 v7, v13, v9                                   ; 060e130d
	image_sample_lz v6, v[6:7], s[16:23], s[4:7] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f09c0808 00240606
	v_sub_f32_e32 v3, v3, v10                                   ; 08061503
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_sub_f32_e32 v6, 1.0, v6                                   ; 080c0cf2
	v_sub_f32_e32 v6, v6, v10                                   ; 080c1506
	v_add_f32_e32 v6, v6, v11                                   ; 060c1706
	v_sub_f32_e32 v6, v3, v6                                    ; 080c0d03
	v_rcp_f32_e32 v6, v6                                        ; 7e0c5506
	v_mul_f32_e32 v3, v3, v6                                    ; 10060d03
	v_mad_f32 v10, v8, v3, v12                                  ; d541000a 04320708
	v_mad_f32 v11, v9, v3, v13                                  ; d541000b 04360709
BB37:
	s_clause 0x3                                                ; bfa10003
	s_load_dwordx8 s[8:15], s[2:3], 0x60                        ; f40c0201 fa000060
	s_load_dwordx4 s[4:7], s[2:3], 0xb0                         ; f4080101 fa0000b0
	s_load_dwordx8 s[16:23], s[2:3], null                       ; f40c0401 fa000000
	s_load_dwordx4 s[24:27], s[2:3], 0x50                       ; f4080601 fa000050
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_lz v[6:8], v[10:11], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f09c0708 0022060a
	image_sample v[12:14], v[10:11], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00c40c0a
	v_min_f32_e32 v15, v10, v11                                 ; 1e1e170a
	v_max_f32_e32 v10, v10, v11                                 ; 2014170a
	v_cmp_gt_f32_e32 vcc, 0, v15                                ; 7c081e80
	v_cmp_lt_f32_e64 s[2:3], 1.0, v10                           ; d4010002 000214f2
	s_or_b64 s[2:3], s[2:3], vcc                                ; 88826a02
	s_andn2_b64 exec, exec, s[2:3]                              ; 8afe027e
	s_andn2_b64 s[0:1], s[0:1], s[2:3]                          ; 8a800200
	s_cbranch_scc0 BB39                                         ; bf840044
	v_interp_p1_f32_e32 v19, v0, attr1.x                        ; c84c0400
	v_interp_p1_f32_e32 v17, v0, attr0.w                        ; c8440300
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v19, v1, attr1.x                        ; c84d0401
	v_interp_p2_f32_e32 v17, v1, attr0.w                        ; c8450301
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mul_f32_e32 v18, v17, v17                                 ; 10242311
	v_mac_f32_e32 v18, v19, v19                                 ; 3e242713
	v_mac_f32_e32 v18, v0, v0                                   ; 3e240100
	v_rsq_f32_e32 v18, v18                                      ; 7e245d12
	v_mul_f32_e32 v17, v17, v18                                 ; 10222511
	v_mul_f32_e32 v0, v0, v18                                   ; 10002500
	v_mul_f32_e32 v19, v19, v18                                 ; 10262513
	v_add_f32_e32 v2, v17, v2                                   ; 06040511
	v_add_f32_e32 v5, v0, v5                                    ; 060a0b00
	v_add_f32_e32 v4, v19, v4                                   ; 06080913
	v_mul_f32_e32 v20, v2, v2                                   ; 10280502
	v_mac_f32_e32 v20, v4, v4                                   ; 3e280904
	v_mac_f32_e32 v20, v5, v5                                   ; 3e280b05
	v_rsq_f32_e32 v20, v20                                      ; 7e285d14
	v_mul_f32_e32 v4, v4, v20                                   ; 10082904
	v_mul_f32_e32 v2, v2, v20                                   ; 10042902
	v_mul_f32_e32 v5, v5, v20                                   ; 100a2905
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mad_f32 v8, 2.0, v8, -1.0                                 ; d5410008 03ce10f4
	v_mad_f32 v6, 2.0, v6, -1.0                                 ; d5410006 03ce0cf4
	v_mad_f32 v7, 2.0, v7, -1.0                                 ; d5410007 03ce0ef4
	v_mul_f32_e32 v16, v7, v7                                   ; 10200f07
	v_mac_f32_e32 v16, v8, v8                                   ; 3e201108
	v_mac_f32_e32 v16, v6, v6                                   ; 3e200d06
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_mul_f32_e32 v6, v6, v16                                   ; 100c2106
	v_mul_f32_e32 v7, v7, v16                                   ; 100e2107
	v_mul_f32_e32 v8, v8, v16                                   ; 10102108
	v_mul_f32_e32 v19, v19, v8                                  ; 10261113
	v_mul_f32_e32 v8, v8, v4                                    ; 10100908
	v_mov_b32_e32 v3, 1.0                                       ; 7e0602f2
	v_mac_f32_e32 v19, v17, v7                                  ; 3e260f11
	v_mac_f32_e32 v8, v7, v2                                    ; 3e100507
	v_mac_f32_e32 v19, v0, v6                                   ; 3e260d00
	v_mac_f32_e32 v8, v6, v5                                    ; 3e100b06
	v_max_f32_e32 v19, 0, v19                                   ; 20262680
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_add_f32_e32 v19, 0x3e4ccccd, v19                          ; 062626ff 3e4ccccd
	v_log_f32_e32 v8, v8                                        ; 7e104f08
	v_mul_f32_e32 v8, 0x42000000, v8                            ; 101010ff 42000000
	v_exp_f32_e32 v8, v8                                        ; 7e104b08
	v_mul_f32_e32 v2, 0x3e19999a, v8                            ; 100410ff 3e19999a
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v0, v12, v19, v2                                  ; d5410000 040a270c
	v_mad_f32 v1, v13, v19, v2                                  ; d5410001 040a270d
	v_mac_f32_e32 v2, v14, v19                                  ; 3e04270e
BB38:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v1                          ; 5e000300
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v3                          ; 5e040702
	exp mrt0 v0, v0, v2, v2 done compr vm                       ; f8001c0f 80800200
	s_endpgm                                                    ; bf810000
BB39:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
