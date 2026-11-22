# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[0:1], null                        ; f40c0200 fa000000
	s_load_dwordx4 s[16:19], s[0:1], 0x50                       ; f4080400 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v3, v0, attr1.w                         ; c80c0700
	v_interp_p1_f32_e32 v4, v0, attr1.z                         ; c8100600
	v_interp_p2_f32_e32 v3, v1, attr1.w                         ; c80d0701
	v_interp_p2_f32_e32 v4, v1, attr1.z                         ; c8110601
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[8:11], [v4, v3], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00820804 00000003
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[0:1], 0x60                        ; f40c0200 fa000060
	s_load_dwordx4 s[4:7], s[0:1], 0xb0                         ; f4080100 fa0000b0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[5:7], [v4, v3], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220504 00000003
	v_interp_p1_f32_e32 v15, v0, attr0.y                        ; c83c0100
	v_interp_p1_f32_e32 v13, v0, attr1.x                        ; c8340400
	v_interp_p1_f32_e32 v14, v0, attr1.y                        ; c8380500
	v_interp_p1_f32_e32 v12, v0, attr0.w                        ; c8300300
	v_interp_p1_f32_e32 v17, v0, attr0.z                        ; c8440200
	v_interp_p1_f32_e32 v18, v0, attr0.x                        ; c8480000
	v_interp_p1_f32_e32 v21, v0, attr3.w                        ; c8540f00
	v_interp_p2_f32_e32 v15, v1, attr0.y                        ; c83d0101
	v_interp_p2_f32_e32 v13, v1, attr1.x                        ; c8350401
	v_interp_p1_f32_e32 v23, v0, attr4.x                        ; c85c1000
	v_interp_p2_f32_e32 v14, v1, attr1.y                        ; c8390501
	v_interp_p2_f32_e32 v12, v1, attr0.w                        ; c8310301
	v_interp_p2_f32_e32 v17, v1, attr0.z                        ; c8450201
	v_interp_p1_f32_e32 v24, v0, attr3.z                        ; c8600e00
	v_interp_p2_f32_e32 v18, v1, attr0.x                        ; c8490001
	v_interp_p2_f32_e32 v21, v1, attr3.w                        ; c8550f01
	v_interp_p2_f32_e32 v23, v1, attr4.x                        ; c85d1001
	v_interp_p2_f32_e32 v24, v1, attr3.z                        ; c8610e01
	v_mul_f32_e32 v16, v15, v15                                 ; 10201f0f
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[0:3], s[2:3], null                         ; f4080001 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s0, s[0:3], 0xe0                        ; f4200000 fa0000e0
	v_mul_f32_e32 v27, v17, v21                                 ; 10362b11
	v_mul_f32_e32 v22, v21, v21                                 ; 102c2b15
	v_mul_f32_e32 v3, v18, v23                                  ; 10062f12
	v_mac_f32_e32 v16, v17, v17                                 ; 3e202311
	v_mul_f32_e32 v4, v15, v24                                  ; 1008310f
	v_mac_f32_e32 v22, v23, v23                                 ; 3e2c2f17
	v_mac_f32_e32 v16, v18, v18                                 ; 3e202512
	v_mac_f32_e32 v22, v24, v24                                 ; 3e2c3118
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_rsq_f32_e32 v22, v22                                      ; 7e2c5d16
	v_mul_f32_e32 v19, v18, v16                                 ; 10262112
	v_mul_f32_e32 v20, v15, v16                                 ; 1028210f
	v_mad_f32 v15, v15, v23, -v27                               ; d541000f 846e2f0f
	v_mul_f32_e32 v16, v17, v16                                 ; 10202111
	v_mad_f32 v17, v17, v24, -v3                                ; d5410011 840e3111
	v_interp_p1_f32_e32 v27, v0, attr3.y                        ; c86c0d00
	v_interp_p1_f32_e32 v3, v0, attr2.w                         ; c80c0b00
	v_interp_p2_f32_e32 v27, v1, attr3.y                        ; c86d0d01
	v_interp_p2_f32_e32 v3, v1, attr2.w                         ; c80d0b01
	v_mul_f32_e32 v26, v21, v22                                 ; 10342d15
	v_mul_f32_e32 v25, v24, v22                                 ; 10322d18
	v_mul_f32_e32 v22, v23, v22                                 ; 102c2d17
	v_interp_p1_f32_e32 v23, v0, attr3.x                        ; c85c0c00
	v_interp_p2_f32_e32 v23, v1, attr3.x                        ; c85d0c01
	v_mad_f32 v18, v18, v21, -v4                                ; d5410012 84122b12
	v_interp_p1_f32_e32 v21, v0, attr4.y                        ; c8541100
	v_interp_p1_f32_e32 v4, v0, attr2.y                         ; c8100900
	v_interp_p2_f32_e32 v21, v1, attr4.y                        ; c8551101
	v_interp_p2_f32_e32 v4, v1, attr2.y                         ; c8110901
	v_mul_f32_e32 v24, v23, v23                                 ; 10302f17
	v_mul_f32_e32 v15, v15, v21                                 ; 101e2b0f
	v_mul_f32_e32 v17, v17, v21                                 ; 10222b11
	v_mul_f32_e32 v18, v18, v21                                 ; 10242b12
	v_mul_f32_e32 v21, v4, v4                                   ; 102a0904
	v_mac_f32_e32 v24, v27, v27                                 ; 3e30371b
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	v_mac_f32_e32 v24, v3, v3                                   ; 3e300703
	v_rsq_f32_e32 v24, v24                                      ; 7e305d18
	v_mul_f32_e32 v3, v3, v24                                   ; 10063103
	v_mul_f32_e32 v23, v23, v24                                 ; 102e3117
	v_mul_f32_e32 v27, v27, v24                                 ; 1036311b
	v_interp_p1_f32_e32 v24, v0, attr2.z                        ; c8600a00
	v_interp_p1_f32_e32 v0, v0, attr2.x                         ; c8000800
	v_interp_p2_f32_e32 v24, v1, attr2.z                        ; c8610a01
	v_interp_p2_f32_e32 v0, v1, attr2.x                         ; c8010801
	v_mac_f32_e32 v21, v24, v24                                 ; 3e2a3118
	v_mac_f32_e32 v21, v0, v0                                   ; 3e2a0100
	v_rsq_f32_e32 v21, v21                                      ; 7e2a5d15
	v_mul_f32_e32 v24, v24, v21                                 ; 10302b18
	v_mul_f32_e32 v0, v0, v21                                   ; 10002b00
	v_mul_f32_e32 v4, v4, v21                                   ; 10082b04
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v8, v8, v12                                   ; 10101908
	v_mul_f32_e32 v10, v10, v14                                 ; 10141d0a
	v_mul_f32_e32 v9, v9, v13                                   ; 10121b09
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v6, 2.0, v6, -1.0                                 ; d5410006 03ce0cf4
	v_mad_f32 v5, 2.0, v5, -1.0                                 ; d5410005 03ce0af4
	v_mad_f32 v7, 2.0, v7, -1.0                                 ; d5410007 03ce0ef4
	v_mul_f32_e32 v1, v6, v6                                    ; 10020d06
	v_mac_f32_e32 v1, v7, v7                                    ; 3e020f07
	v_mac_f32_e32 v1, v5, v5                                    ; 3e020b05
	v_rsq_f32_e32 v1, v1                                        ; 7e025d01
	v_mul_f32_e32 v6, v6, v1                                    ; 100c0306
	v_mul_f32_e32 v7, v7, v1                                    ; 100e0307
	v_mul_f32_e32 v5, v5, v1                                    ; 100a0305
	v_mul_f32_e32 v19, v19, v7                                  ; 10260f13
	v_mul_f32_e32 v20, v20, v7                                  ; 10280f14
	v_mul_f32_e32 v16, v16, v7                                  ; 10200f10
	v_mac_f32_e32 v19, v15, v6                                  ; 3e260d0f
	v_mac_f32_e32 v20, v17, v6                                  ; 3e280d11
	v_mac_f32_e32 v16, v18, v6                                  ; 3e200d12
	v_mac_f32_e32 v19, v25, v5                                  ; 3e260b19
	v_mac_f32_e32 v20, v26, v5                                  ; 3e280b1a
	v_mac_f32_e32 v16, v22, v5                                  ; 3e200b16
	v_mul_f32_e32 v5, v27, v16                                  ; 100a211b
	v_mad_f32 v6, v23, -v20, -v5                                ; d5410006 c4162917
	v_mac_f32_e32 v5, v23, v20                                  ; 3e0a2917
	v_mad_f32 v6, v3, -v19, v6 mul:2                            ; d5410006 4c1a2703
	v_mac_f32_e32 v5, v3, v19                                   ; 3e0a2703
	v_mad_f32 v12, v20, -v6, -v23                               ; d541000c c45e0d14
	v_mad_f32 v16, v16, -v6, -v27                               ; d5410010 c46e0d10
	v_mad_f32 v7, v19, -v6, -v3                                 ; d5410007 c40e0d13
	v_max_f32_e32 v5, 0x3e800000, v5                            ; 200a0aff 3e800000
	v_mul_f32_e32 v16, v16, v24                                 ; 10203110
	v_mac_f32_e32 v16, v12, v4                                  ; 3e20090c
	v_mac_f32_e32 v16, v7, v0                                   ; 3e200107
	v_max_f32_e32 v16, 0, v16                                   ; 20202080
	v_log_f32_e32 v16, v16                                      ; 7e204f10
	v_mul_f32_e32 v16, 0x42000000, v16                          ; 102020ff 42000000
	v_exp_f32_e32 v16, v16                                      ; 7e204b10
	v_mad_f32 v9, v5, v9, v16                                   ; d5410009 04421305
	v_mad_f32 v8, v5, v8, v16                                   ; d5410008 04421105
	v_mac_f32_e32 v16, v5, v10                                  ; 3e201505
	s_cbranch_scc0 BB33                                         ; bf840057
BB1:
	v_bfe_u32 v0, v2, 4, 2                                      ; d5480000 02090902
	v_bfe_u32 v2, v2, 2, 2                                      ; d5480002 02090502
	v_cmp_eq_i32_e32 vcc, 1, v0                                 ; 7d040081
	v_cndmask_b32_e64 v1, 0, 1, vcc                             ; d5010001 01a90280
	v_cmp_eq_i32_e32 vcc, 1, v2                                 ; 7d040481
	v_cndmask_b32_e64 v2, 0, 4, vcc                             ; d5010002 01a90880
	v_or_b32_e32 v2, v2, v1                                     ; 38040302
	v_cmp_class_f16_e32 vcc, 0x7c01, v2                         ; 7d1e04ff 00007c01
	v_cndmask_b32_e64 v3, 1, 2, vcc                             ; d5010003 01a90481
	v_cmp_class_f32_e32 vcc, -1, v2                             ; 7d1004c1
	v_cndmask_b32_e64 v3, v3, 4, vcc                            ; d5010003 01a90903
	v_cmp_class_f32_e32 vcc, 0xff800000, v2                     ; 7d1004ff ff800000
	v_cndmask_b32_e64 v4, 1, 2, vcc                             ; d5010004 01a90481
	v_cmp_class_f32_e32 vcc, -1.0, v2                           ; 7d1004f3
	v_cndmask_b32_e64 v4, v4, 4, vcc                            ; d5010004 01a90904
	v_cmp_eq_i32_e32 vcc, 1, v3                                 ; 7d040681
	v_cmp_eq_i32_e64 s[0:1], 1, v4                              ; d4820000 00020881
	s_and_b64 s[2:3], vcc, s[0:1]                               ; 8782006a
	s_and_saveexec_b64 s[2:3], s[2:3]                           ; be822402
BB2:
	v_mul_f32_e32 v16, 0x3ecccccd, v16                          ; 102020ff 3ecccccd
	v_mul_f32_e32 v9, 0x3f4ccccd, v9                            ; 101212ff 3f4ccccd
	v_mov_b32_e32 v8, 0                                         ; 7e100280
	s_andn2_b64 exec, s[2:3], exec                              ; 8afe7e02
	s_cbranch_execz BB31                                        ; bf880031
BB5:
	v_cmp_eq_i32_e64 s[4:5], 2, v3                              ; d4820004 00020682
	s_and_b64 s[0:1], s[4:5], s[0:1]                            ; 87800004
	s_and_saveexec_b64 s[0:1], s[0:1]                           ; be802400
BB6:
	v_mul_f32_e32 v9, 0x3f19999a, v9                            ; 101212ff 3f19999a
	v_mul_f32_e32 v8, 0x3e4ccccd, v8                            ; 101010ff 3e4ccccd
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	s_cbranch_execz BB31                                        ; bf880027
BB9:
	v_cmp_eq_i32_e64 s[6:7], 2, v4                              ; d4820006 00020882
	s_and_b64 s[8:9], vcc, s[6:7]                               ; 8788066a
	s_and_saveexec_b64 s[8:9], s[8:9]                           ; be882408
BB10:
	v_mul_f32_e32 v16, 0x3f4ccccd, v16                          ; 102020ff 3f4ccccd
	v_mul_f32_e32 v9, 0x3ecccccd, v9                            ; 101212ff 3ecccccd
	v_mov_b32_e32 v8, 0                                         ; 7e100280
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	s_cbranch_execz BB31                                        ; bf88001c
BB13:
	s_and_b64 s[10:11], s[4:5], s[6:7]                          ; 878a0604
	s_and_saveexec_b64 s[10:11], s[10:11]                       ; be8a240a
BB14:
	v_mul_f32_e32 v16, 0x3e4ccccd, v16                          ; 102020ff 3e4ccccd
	s_andn2_b64 exec, s[10:11], exec                            ; 8afe7e0a
	s_cbranch_execz BB31                                        ; bf880016
BB17:
	v_cmp_eq_i32_e32 vcc, 4, v3                                 ; 7d040684
	s_and_b64 s[6:7], vcc, s[6:7]                               ; 8786066a
	s_and_saveexec_b64 s[6:7], s[6:7]                           ; be862406
BB18:
	v_mul_f32_e32 v9, 0x3f4ccccd, v9                            ; 101212ff 3f4ccccd
	v_mul_f32_e32 v8, 0x3f4ccccd, v8                            ; 101010ff 3f4ccccd
	v_mov_b32_e32 v16, 0                                        ; 7e200280
	s_andn2_b64 exec, s[6:7], exec                              ; 8afe7e06
BB21:
	v_cmp_eq_i32_e32 vcc, 4, v4                                 ; 7d040884
	v_mul_f32_e32 v0, 0x3ecccccd, v9                            ; 100012ff 3ecccccd
	v_mul_f32_e32 v9, 0x3f4ccccd, v9                            ; 101212ff 3f4ccccd
	v_mul_f32_e32 v1, 0x3e4ccccd, v16                           ; 100220ff 3e4ccccd
	v_mul_f32_e32 v16, 0x3ecccccd, v16                          ; 102020ff 3ecccccd
	s_and_b64 vcc, s[4:5], vcc                                  ; 87ea6a04
	v_cndmask_b32_e32 v8, 0, v8, vcc                            ; 02101080
	v_cndmask_b32_e32 v9, v9, v0, vcc                           ; 02120109
	v_cndmask_b32_e32 v16, v16, v1, vcc                         ; 02200310
BB31:
	s_mov_b64 exec, s[2:3]                                      ; befe0402
BB33:
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v9                          ; 5e101308
	v_cvt_pkrtz_f16_f32_e32 v16, v16, v11                       ; 5e201710
	exp mrt0 v8, v8, v16, v16 done compr vm                     ; f8001c0f 80801008
	s_endpgm                                                    ; bf810000
