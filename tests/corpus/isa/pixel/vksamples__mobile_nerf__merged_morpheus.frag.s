# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x4                                                ; bfa10004
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_load_dwordx8 s[16:23], s[2:3], 0x60                       ; f40c0401 fa000060
	s_load_dwordx4 s[24:27], s[2:3], 0xb0                       ; f4080601 fa0000b0
	s_load_dwordx4 s[28:31], s[2:3], 0xd0                       ; f4080701 fa0000d0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v3, v2], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220403 00000002
	image_sample  v[8:11], [v3, v2], s[16:23], s[24:27] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00c40803 00000002
	s_mov_b64 s[96:97], s[28:29]                                ; bee0041c
	s_mov_b64 s[98:99], s[30:31]                                ; bee2041e
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x5                                                ; bfa10005
	s_buffer_load_dwordx16 s[0:15], s[28:31], null              ; f430000e fa000000
	s_buffer_load_dwordx16 s[32:47], s[28:31], 0x7c0            ; f430080e fa0007c0
	s_buffer_load_dwordx16 s[48:63], s[28:31], 0x40             ; f4300c0e fa000040
	s_buffer_load_dwordx16 s[64:79], s[28:31], 0x80             ; f430100e fa000080
	s_buffer_load_dwordx16 s[80:95], s[28:31], 0xc0             ; f430140e fa0000c0
	s_buffer_load_dwordx16 s[16:31], s[28:31], 0x100            ; f430040e fa000100
	v_interp_p1_f32_e32 v12, v0, attr0.w                        ; c8300300
	v_interp_p1_f32_e32 v14, v0, attr1.x                        ; c8380400
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v12, v1, attr0.w                        ; c8310301
	v_interp_p2_f32_e32 v14, v1, attr1.x                        ; c8390401
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mul_f32_e32 v13, v12, v12                                 ; 101a190c
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_mov_b64 s[104:105], s[12:13]                              ; bee8040c
	s_mov_b64 vcc, s[14:15]                                     ; beea040e
	s_mov_b64 s[100:101], s[8:9]                                ; bee40408
	s_mov_b64 s[102:103], s[10:11]                              ; bee6040a
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mad_f32 v15, s0, v4, s32                                  ; d541000f 00820800
	v_mad_f32 v16, s1, v4, s33                                  ; d5410010 00860801
	s_mov_b64 s[32:33], s[4:5]                                  ; bea00404
	v_mad_f32 v17, s2, v4, s34                                  ; d5410011 008a0802
	v_mad_f32 v18, s3, v4, s35                                  ; d5410012 008e0803
	s_mov_b64 s[34:35], s[6:7]                                  ; bea20406
	v_mac_f32_e32 v13, v14, v14                                 ; 3e1a1d0e
	v_mad_f32 v23, s100, v4, s40                                ; d5410017 00a20864
	v_mad_f32 v24, s101, v4, s41                                ; d5410018 00a60865
	v_mad_f32 v25, s102, v4, s42                                ; d5410019 00aa0866
	v_mad_f32 v26, s103, v4, s43                                ; d541001a 00ae0867
	s_mov_b64 s[100:101], s[44:45]                              ; bee4042c
	s_mov_b64 s[102:103], s[46:47]                              ; bee6042e
	v_mad_f32 v20, s33, v4, s37                                 ; d5410014 00960821
	v_mad_f32 v19, s32, v4, s36                                 ; d5410013 00920820
	v_mad_f32 v21, s34, v4, s38                                 ; d5410015 009a0822
	v_mad_f32 v22, s35, v4, s39                                 ; d5410016 009e0823
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x140             ; f4300030 fa000140
	s_buffer_load_dwordx16 s[32:47], s[96:99], 0x180            ; f4300830 fa000180
	v_mad_f32 v7, 2.0, v7, -1.0                                 ; d5410007 03ce0ef4
	v_mac_f32_e32 v15, s48, v5                                  ; 3e1e0a30
	v_mac_f32_e32 v16, s49, v5                                  ; 3e200a31
	v_mac_f32_e32 v13, v0, v0                                   ; 3e1a0100
	v_mac_f32_e32 v17, s50, v5                                  ; 3e220a32
	v_mac_f32_e32 v18, s51, v5                                  ; 3e240a33
	v_mad_f32 v27, s104, v4, s100                               ; d541001b 01920868
	v_mad_f32 v28, s105, v4, s101                               ; d541001c 01960869
	v_mad_f32 v29, vcc_lo, v4, s102                             ; d541001d 019a086a
	v_mad_f32 v4, vcc_hi, v4, s103                              ; d5410004 019e086b
	s_mov_b64 s[100:101], s[60:61]                              ; bee4043c
	v_mac_f32_e32 v20, s53, v5                                  ; 3e280a35
	v_mac_f32_e32 v19, s52, v5                                  ; 3e260a34
	s_mov_b64 s[102:103], s[62:63]                              ; bee6043e
	s_mov_b64 s[104:105], s[56:57]                              ; bee80438
	v_mac_f32_e32 v21, s54, v5                                  ; 3e2a0a36
	s_mov_b64 vcc, s[58:59]                                     ; beea043a
	v_mac_f32_e32 v22, s55, v5                                  ; 3e2c0a37
	s_buffer_load_dwordx16 s[48:63], s[96:99], 0x1c0            ; f4300c30 fa0001c0
	v_rsq_f32_e32 v13, v13                                      ; 7e1a5d0d
	v_mac_f32_e32 v27, s100, v5                                 ; 3e360a64
	v_mac_f32_e32 v28, s101, v5                                 ; 3e380a65
	v_mac_f32_e32 v15, s64, v6                                  ; 3e1e0c40
	v_mac_f32_e32 v16, s65, v6                                  ; 3e200c41
	v_mac_f32_e32 v17, s66, v6                                  ; 3e220c42
	v_mac_f32_e32 v29, s102, v5                                 ; 3e3a0a66
	v_mac_f32_e32 v4, s103, v5                                  ; 3e080a67
	v_mac_f32_e32 v18, s67, v6                                  ; 3e240c43
	v_mac_f32_e32 v23, s104, v5                                 ; 3e2e0a68
	v_mac_f32_e32 v24, s105, v5                                 ; 3e300a69
	v_mac_f32_e32 v19, s68, v6                                  ; 3e260c44
	v_mac_f32_e32 v20, s69, v6                                  ; 3e280c45
	v_mac_f32_e32 v25, vcc_lo, v5                               ; 3e320a6a
	v_mac_f32_e32 v26, vcc_hi, v5                               ; 3e340a6b
	v_mac_f32_e32 v21, s70, v6                                  ; 3e2a0c46
	v_mac_f32_e32 v22, s71, v6                                  ; 3e2c0c47
	s_mov_b64 s[100:101], s[76:77]                              ; bee4044c
	s_mov_b64 s[102:103], s[78:79]                              ; bee6044e
	s_mov_b64 s[104:105], s[72:73]                              ; bee80448
	s_mov_b64 vcc, s[74:75]                                     ; beea044a
	s_buffer_load_dwordx16 s[64:79], s[96:99], 0x200            ; f4301030 fa000200
	v_mac_f32_e32 v15, s80, v7                                  ; 3e1e0e50
	v_mac_f32_e32 v16, s81, v7                                  ; 3e200e51
	v_mac_f32_e32 v17, s82, v7                                  ; 3e220e52
	v_mac_f32_e32 v18, s83, v7                                  ; 3e240e53
	v_mac_f32_e32 v19, s84, v7                                  ; 3e260e54
	v_mac_f32_e32 v28, s101, v6                                 ; 3e380c65
	v_mac_f32_e32 v27, s100, v6                                 ; 3e360c64
	v_mac_f32_e32 v20, s85, v7                                  ; 3e280e55
	v_mac_f32_e32 v4, s103, v6                                  ; 3e080c67
	v_mac_f32_e32 v29, s102, v6                                 ; 3e3a0c66
	v_mac_f32_e32 v21, s86, v7                                  ; 3e2a0e56
	v_mac_f32_e32 v23, s104, v6                                 ; 3e2e0c68
	v_mac_f32_e32 v22, s87, v7                                  ; 3e2c0e57
	v_mac_f32_e32 v24, s105, v6                                 ; 3e300c69
	v_mac_f32_e32 v26, vcc_hi, v6                               ; 3e340c6b
	v_mac_f32_e32 v25, vcc_lo, v6                               ; 3e320c6a
	s_mov_b64 s[100:101], s[92:93]                              ; bee4045c
	s_mov_b64 s[102:103], s[94:95]                              ; bee6045e
	s_mov_b64 s[104:105], s[88:89]                              ; bee80458
	s_mov_b64 vcc, s[90:91]                                     ; beea045a
	s_buffer_load_dwordx16 s[80:95], s[96:99], 0x240            ; f4301430 fa000240
	v_mad_f32 v0, v0, v13, 1.0 div:2                            ; d5410000 1bca1b00
	v_mad_f32 v14, v14, -v13, 1.0 div:2                         ; d541000e 5bca1b0e
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v15, s16, v8                                  ; 3e1e1010
	v_mac_f32_e32 v16, s17, v8                                  ; 3e201011
	v_mac_f32_e32 v17, s18, v8                                  ; 3e221012
	v_mac_f32_e32 v18, s19, v8                                  ; 3e241013
	v_mac_f32_e32 v27, s100, v7                                 ; 3e360e64
	v_mac_f32_e32 v28, s101, v7                                 ; 3e380e65
	v_mac_f32_e32 v29, s102, v7                                 ; 3e3a0e66
	v_mac_f32_e32 v19, s20, v8                                  ; 3e261014
	v_mac_f32_e32 v4, s103, v7                                  ; 3e080e67
	v_mac_f32_e32 v20, s21, v8                                  ; 3e281015
	v_mac_f32_e32 v23, s104, v7                                 ; 3e2e0e68
	v_mac_f32_e32 v24, s105, v7                                 ; 3e300e69
	v_mac_f32_e32 v25, vcc_lo, v7                               ; 3e320e6a
	v_mac_f32_e32 v21, s22, v8                                  ; 3e2a1016
	v_mac_f32_e32 v26, vcc_hi, v7                               ; 3e340e6b
	v_mac_f32_e32 v22, s23, v8                                  ; 3e2c1017
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s0, v9                                   ; 3e1e1200
	v_mac_f32_e32 v16, s1, v9                                   ; 3e201201
	v_mac_f32_e32 v27, s28, v8                                  ; 3e36101c
	v_mac_f32_e32 v17, s2, v9                                   ; 3e221202
	v_mac_f32_e32 v28, s29, v8                                  ; 3e38101d
	v_mac_f32_e32 v29, s30, v8                                  ; 3e3a101e
	v_mac_f32_e32 v18, s3, v9                                   ; 3e241203
	v_mac_f32_e32 v19, s4, v9                                   ; 3e261204
	v_mac_f32_e32 v4, s31, v8                                   ; 3e08101f
	v_mac_f32_e32 v20, s5, v9                                   ; 3e281205
	v_mac_f32_e32 v23, s24, v8                                  ; 3e2e1018
	v_mac_f32_e32 v24, s25, v8                                  ; 3e301019
	v_mac_f32_e32 v25, s26, v8                                  ; 3e32101a
	v_mac_f32_e32 v21, s6, v9                                   ; 3e2a1206
	v_mac_f32_e32 v26, s27, v8                                  ; 3e34101b
	v_mac_f32_e32 v22, s7, v9                                   ; 3e2c1207
	v_mac_f32_e32 v27, s12, v9                                  ; 3e36120c
	v_mac_f32_e32 v15, s32, v10                                 ; 3e1e1420
	v_mac_f32_e32 v28, s13, v9                                  ; 3e38120d
	v_mac_f32_e32 v16, s33, v10                                 ; 3e201421
	v_mac_f32_e32 v29, s14, v9                                  ; 3e3a120e
	v_mac_f32_e32 v17, s34, v10                                 ; 3e221422
	v_mac_f32_e32 v18, s35, v10                                 ; 3e241423
	v_mac_f32_e32 v19, s36, v10                                 ; 3e261424
	v_mac_f32_e32 v4, s15, v9                                   ; 3e08120f
	v_mac_f32_e32 v20, s37, v10                                 ; 3e281425
	v_mac_f32_e32 v23, s8, v9                                   ; 3e2e1208
	v_mac_f32_e32 v24, s9, v9                                   ; 3e301209
	v_mac_f32_e32 v25, s10, v9                                  ; 3e32120a
	v_mac_f32_e32 v21, s38, v10                                 ; 3e2a1426
	v_mac_f32_e32 v26, s11, v9                                  ; 3e34120b
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x280             ; f4300030 fa000280
	v_mac_f32_e32 v22, s39, v10                                 ; 3e2c1427
	v_mac_f32_e32 v27, s44, v10                                 ; 3e36142c
	v_mac_f32_e32 v28, s45, v10                                 ; 3e38142d
	v_mad_f32 v11, 2.0, v11, -1.0                               ; d541000b 03ce16f4
	v_mac_f32_e32 v29, s46, v10                                 ; 3e3a142e
	v_mac_f32_e32 v4, s47, v10                                  ; 3e08142f
	v_mac_f32_e32 v23, s40, v10                                 ; 3e2e1428
	v_mac_f32_e32 v24, s41, v10                                 ; 3e301429
	v_mac_f32_e32 v25, s42, v10                                 ; 3e32142a
	v_mac_f32_e32 v26, s43, v10                                 ; 3e34142b
	v_mac_f32_e32 v28, s61, v11                                 ; 3e38163d
	v_mac_f32_e32 v17, s50, v11                                 ; 3e221632
	v_mac_f32_e32 v19, s52, v11                                 ; 3e261634
	v_mac_f32_e32 v21, s54, v11                                 ; 3e2a1636
	v_mac_f32_e32 v20, s53, v11                                 ; 3e281635
	v_mac_f32_e32 v16, s49, v11                                 ; 3e201631
	v_mac_f32_e32 v22, s55, v11                                 ; 3e2c1637
	v_mac_f32_e32 v15, s48, v11                                 ; 3e1e1630
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x800            ; f4300430 fa000800
	v_mac_f32_e32 v18, s51, v11                                 ; 3e241633
	v_mac_f32_e32 v27, s60, v11                                 ; 3e36163c
	v_mac_f32_e32 v29, s62, v11                                 ; 3e3a163e
	v_mac_f32_e32 v4, s63, v11                                  ; 3e08163f
	v_mac_f32_e32 v23, s56, v11                                 ; 3e2e1638
	v_mac_f32_e32 v24, s57, v11                                 ; 3e301639
	v_mac_f32_e32 v25, s58, v11                                 ; 3e32163a
	v_mac_f32_e32 v26, s59, v11                                 ; 3e34163b
	v_mac_f32_e32 v17, s66, v0                                  ; 3e220042
	v_mac_f32_e32 v19, s68, v0                                  ; 3e260044
	v_mac_f32_e32 v21, s70, v0                                  ; 3e2a0046
	v_mac_f32_e32 v20, s69, v0                                  ; 3e280045
	v_mac_f32_e32 v16, s65, v0                                  ; 3e200041
	v_mac_f32_e32 v22, s71, v0                                  ; 3e2c0047
	v_mac_f32_e32 v15, s64, v0                                  ; 3e1e0040
	v_mac_f32_e32 v18, s67, v0                                  ; 3e240043
	v_mac_f32_e32 v28, s77, v0                                  ; 3e38004d
	v_mac_f32_e32 v27, s76, v0                                  ; 3e36004c
	v_mac_f32_e32 v29, s78, v0                                  ; 3e3a004e
	v_mac_f32_e32 v4, s79, v0                                   ; 3e08004f
	v_mac_f32_e32 v23, s72, v0                                  ; 3e2e0048
	v_mac_f32_e32 v24, s73, v0                                  ; 3e300049
	v_mac_f32_e32 v25, s74, v0                                  ; 3e32004a
	v_mac_f32_e32 v26, s75, v0                                  ; 3e34004b
	v_mac_f32_e32 v17, s82, v14                                 ; 3e221c52
	v_mac_f32_e32 v19, s84, v14                                 ; 3e261c54
	v_mac_f32_e32 v21, s86, v14                                 ; 3e2a1c56
	v_mac_f32_e32 v20, s85, v14                                 ; 3e281c55
	v_mac_f32_e32 v16, s81, v14                                 ; 3e201c51
	v_mac_f32_e32 v22, s87, v14                                 ; 3e2c1c57
	v_mac_f32_e32 v15, s80, v14                                 ; 3e1e1c50
	v_mac_f32_e32 v18, s83, v14                                 ; 3e241c53
	v_mac_f32_e32 v28, s93, v14                                 ; 3e381c5d
	v_mac_f32_e32 v27, s92, v14                                 ; 3e361c5c
	v_mac_f32_e32 v29, s94, v14                                 ; 3e3a1c5e
	v_mac_f32_e32 v4, s95, v14                                  ; 3e081c5f
	v_mad_f32 v12, v12, v13, 1.0 div:2                          ; d541000c 1bca1b0c
	v_mac_f32_e32 v23, s88, v14                                 ; 3e2e1c58
	v_mac_f32_e32 v24, s89, v14                                 ; 3e301c59
	v_mac_f32_e32 v25, s90, v14                                 ; 3e321c5a
	v_mac_f32_e32 v26, s91, v14                                 ; 3e341c5b
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v16, s1, v12                                  ; 3e201801
	v_mac_f32_e32 v15, s0, v12                                  ; 3e1e1800
	v_mac_f32_e32 v20, s5, v12                                  ; 3e281805
	v_mac_f32_e32 v19, s4, v12                                  ; 3e261804
	v_mac_f32_e32 v4, s15, v12                                  ; 3e08180f
	v_mac_f32_e32 v18, s3, v12                                  ; 3e241803
	v_mac_f32_e32 v21, s6, v12                                  ; 3e2a1806
	v_mac_f32_e32 v17, s2, v12                                  ; 3e221802
	v_mac_f32_e32 v27, s12, v12                                 ; 3e36180c
	v_mac_f32_e32 v28, s13, v12                                 ; 3e38180d
	v_mac_f32_e32 v29, s14, v12                                 ; 3e3a180e
	v_mac_f32_e32 v22, s7, v12                                  ; 3e2c1807
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_mac_f32_e32 v23, s8, v12                                  ; 3e2e1808
	v_mac_f32_e32 v24, s9, v12                                  ; 3e301809
	v_mac_f32_e32 v25, s10, v12                                 ; 3e32180a
	v_mac_f32_e32 v26, s11, v12                                 ; 3e34180b
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v15                                    ; 7c221e80
	s_cbranch_execz BB4                                         ; bf880023
BB1:
	s_buffer_load_dwordx16 s[32:47], s[96:99], 0x2c0            ; f4300830 fa0002c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v0, s32, v15, s16                                 ; d5410000 00421e20
	v_mad_f32 v1, s33, v15, s17                                 ; d5410001 00461e21
	v_mad_f32 v2, s34, v15, s18                                 ; d5410002 004a1e22
	v_mad_f32 v3, s35, v15, s19                                 ; d5410003 004e1e23
	v_mad_f32 v5, s36, v15, s20                                 ; d5410005 00521e24
	v_mad_f32 v6, s37, v15, s21                                 ; d5410006 00561e25
	v_mad_f32 v7, s38, v15, s22                                 ; d5410007 005a1e26
	v_mad_f32 v8, s39, v15, s23                                 ; d5410008 005e1e27
	v_mad_f32 v9, s40, v15, s24                                 ; d5410009 00621e28
	v_mad_f32 v10, s41, v15, s25                                ; d541000a 00661e29
	v_mad_f32 v11, s42, v15, s26                                ; d541000b 006a1e2a
	v_mad_f32 v12, s43, v15, s27                                ; d541000c 006e1e2b
	v_mad_f32 v13, s44, v15, s28                                ; d541000d 00721e2c
	v_mad_f32 v14, s45, v15, s29                                ; d541000e 00761e2d
	v_mad_f32 v30, s46, v15, s30                                ; d541001e 007a1e2e
	v_mad_f32 v15, s47, v15, s31                                ; d541000f 007e1e2f
BB4:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_lshrrev_b64 v[0:1], 0, s[16:17]                           ; d7000000 00002080
	v_lshrrev_b64 v[2:3], 0, s[18:19]                           ; d7000002 00002480
	v_lshrrev_b64 v[5:6], 0, s[20:21]                           ; d7000005 00002880
	v_lshrrev_b64 v[7:8], 0, s[22:23]                           ; d7000007 00002c80
	v_lshrrev_b64 v[9:10], 0, s[24:25]                          ; d7000009 00003080
	v_lshrrev_b64 v[11:12], 0, s[26:27]                         ; d700000b 00003480
	v_lshrrev_b64 v[13:14], 0, s[28:29]                         ; d700000d 00003880
	v_mov_b32_e32 v15, s31                                      ; 7e1e021f
	v_mov_b32_e32 v30, s30                                      ; 7e3c021e
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v16                                    ; 7c222080
	s_cbranch_execz BB12                                        ; bf880013
BB7:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x300            ; f4300430 fa000300
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v16                                 ; 3e1e201f
	v_mac_f32_e32 v0, s16, v16                                  ; 3e002010
	v_mac_f32_e32 v1, s17, v16                                  ; 3e022011
	v_mac_f32_e32 v2, s18, v16                                  ; 3e042012
	v_mac_f32_e32 v3, s19, v16                                  ; 3e062013
	v_mac_f32_e32 v5, s20, v16                                  ; 3e0a2014
	v_mac_f32_e32 v6, s21, v16                                  ; 3e0c2015
	v_mac_f32_e32 v7, s22, v16                                  ; 3e0e2016
	v_mac_f32_e32 v8, s23, v16                                  ; 3e102017
	v_mac_f32_e32 v9, s24, v16                                  ; 3e122018
	v_mac_f32_e32 v10, s25, v16                                 ; 3e142019
	v_mac_f32_e32 v11, s26, v16                                 ; 3e16201a
	v_mac_f32_e32 v12, s27, v16                                 ; 3e18201b
	v_mac_f32_e32 v13, s28, v16                                 ; 3e1a201c
	v_mac_f32_e32 v14, s29, v16                                 ; 3e1c201d
	v_mac_f32_e32 v30, s30, v16                                 ; 3e3c201e
BB12:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v17                                    ; 7c222280
	s_cbranch_execz BB18                                        ; bf880013
BB13:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x340            ; f4300430 fa000340
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v17                                 ; 3e1e221f
	v_mac_f32_e32 v0, s16, v17                                  ; 3e002210
	v_mac_f32_e32 v1, s17, v17                                  ; 3e022211
	v_mac_f32_e32 v2, s18, v17                                  ; 3e042212
	v_mac_f32_e32 v3, s19, v17                                  ; 3e062213
	v_mac_f32_e32 v5, s20, v17                                  ; 3e0a2214
	v_mac_f32_e32 v6, s21, v17                                  ; 3e0c2215
	v_mac_f32_e32 v7, s22, v17                                  ; 3e0e2216
	v_mac_f32_e32 v8, s23, v17                                  ; 3e102217
	v_mac_f32_e32 v9, s24, v17                                  ; 3e122218
	v_mac_f32_e32 v10, s25, v17                                 ; 3e142219
	v_mac_f32_e32 v11, s26, v17                                 ; 3e16221a
	v_mac_f32_e32 v12, s27, v17                                 ; 3e18221b
	v_mac_f32_e32 v13, s28, v17                                 ; 3e1a221c
	v_mac_f32_e32 v14, s29, v17                                 ; 3e1c221d
	v_mac_f32_e32 v30, s30, v17                                 ; 3e3c221e
BB18:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v18                                    ; 7c222480
	s_cbranch_execz BB24                                        ; bf880013
BB19:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x380            ; f4300430 fa000380
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v18                                 ; 3e1e241f
	v_mac_f32_e32 v0, s16, v18                                  ; 3e002410
	v_mac_f32_e32 v1, s17, v18                                  ; 3e022411
	v_mac_f32_e32 v2, s18, v18                                  ; 3e042412
	v_mac_f32_e32 v3, s19, v18                                  ; 3e062413
	v_mac_f32_e32 v5, s20, v18                                  ; 3e0a2414
	v_mac_f32_e32 v6, s21, v18                                  ; 3e0c2415
	v_mac_f32_e32 v7, s22, v18                                  ; 3e0e2416
	v_mac_f32_e32 v8, s23, v18                                  ; 3e102417
	v_mac_f32_e32 v9, s24, v18                                  ; 3e122418
	v_mac_f32_e32 v10, s25, v18                                 ; 3e142419
	v_mac_f32_e32 v11, s26, v18                                 ; 3e16241a
	v_mac_f32_e32 v12, s27, v18                                 ; 3e18241b
	v_mac_f32_e32 v13, s28, v18                                 ; 3e1a241c
	v_mac_f32_e32 v14, s29, v18                                 ; 3e1c241d
	v_mac_f32_e32 v30, s30, v18                                 ; 3e3c241e
BB24:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v19                                    ; 7c222680
	s_cbranch_execz BB30                                        ; bf880013
BB25:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x3c0            ; f4300430 fa0003c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v19                                 ; 3e1e261f
	v_mac_f32_e32 v0, s16, v19                                  ; 3e002610
	v_mac_f32_e32 v1, s17, v19                                  ; 3e022611
	v_mac_f32_e32 v2, s18, v19                                  ; 3e042612
	v_mac_f32_e32 v3, s19, v19                                  ; 3e062613
	v_mac_f32_e32 v5, s20, v19                                  ; 3e0a2614
	v_mac_f32_e32 v6, s21, v19                                  ; 3e0c2615
	v_mac_f32_e32 v7, s22, v19                                  ; 3e0e2616
	v_mac_f32_e32 v8, s23, v19                                  ; 3e102617
	v_mac_f32_e32 v9, s24, v19                                  ; 3e122618
	v_mac_f32_e32 v10, s25, v19                                 ; 3e142619
	v_mac_f32_e32 v11, s26, v19                                 ; 3e16261a
	v_mac_f32_e32 v12, s27, v19                                 ; 3e18261b
	v_mac_f32_e32 v13, s28, v19                                 ; 3e1a261c
	v_mac_f32_e32 v14, s29, v19                                 ; 3e1c261d
	v_mac_f32_e32 v30, s30, v19                                 ; 3e3c261e
BB30:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v20                                    ; 7c222880
	s_cbranch_execz BB36                                        ; bf880013
BB31:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x400            ; f4300430 fa000400
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v20                                 ; 3e1e281f
	v_mac_f32_e32 v0, s16, v20                                  ; 3e002810
	v_mac_f32_e32 v1, s17, v20                                  ; 3e022811
	v_mac_f32_e32 v2, s18, v20                                  ; 3e042812
	v_mac_f32_e32 v3, s19, v20                                  ; 3e062813
	v_mac_f32_e32 v5, s20, v20                                  ; 3e0a2814
	v_mac_f32_e32 v6, s21, v20                                  ; 3e0c2815
	v_mac_f32_e32 v7, s22, v20                                  ; 3e0e2816
	v_mac_f32_e32 v8, s23, v20                                  ; 3e102817
	v_mac_f32_e32 v9, s24, v20                                  ; 3e122818
	v_mac_f32_e32 v10, s25, v20                                 ; 3e142819
	v_mac_f32_e32 v11, s26, v20                                 ; 3e16281a
	v_mac_f32_e32 v12, s27, v20                                 ; 3e18281b
	v_mac_f32_e32 v13, s28, v20                                 ; 3e1a281c
	v_mac_f32_e32 v14, s29, v20                                 ; 3e1c281d
	v_mac_f32_e32 v30, s30, v20                                 ; 3e3c281e
BB36:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v21                                    ; 7c222a80
	s_cbranch_execz BB42                                        ; bf880013
BB37:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x440            ; f4300430 fa000440
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v21                                 ; 3e1e2a1f
	v_mac_f32_e32 v0, s16, v21                                  ; 3e002a10
	v_mac_f32_e32 v1, s17, v21                                  ; 3e022a11
	v_mac_f32_e32 v2, s18, v21                                  ; 3e042a12
	v_mac_f32_e32 v3, s19, v21                                  ; 3e062a13
	v_mac_f32_e32 v5, s20, v21                                  ; 3e0a2a14
	v_mac_f32_e32 v6, s21, v21                                  ; 3e0c2a15
	v_mac_f32_e32 v7, s22, v21                                  ; 3e0e2a16
	v_mac_f32_e32 v8, s23, v21                                  ; 3e102a17
	v_mac_f32_e32 v9, s24, v21                                  ; 3e122a18
	v_mac_f32_e32 v10, s25, v21                                 ; 3e142a19
	v_mac_f32_e32 v11, s26, v21                                 ; 3e162a1a
	v_mac_f32_e32 v12, s27, v21                                 ; 3e182a1b
	v_mac_f32_e32 v13, s28, v21                                 ; 3e1a2a1c
	v_mac_f32_e32 v14, s29, v21                                 ; 3e1c2a1d
	v_mac_f32_e32 v30, s30, v21                                 ; 3e3c2a1e
BB42:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v22                                    ; 7c222c80
	s_cbranch_execz BB48                                        ; bf880013
BB43:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x480            ; f4300430 fa000480
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v22                                 ; 3e1e2c1f
	v_mac_f32_e32 v0, s16, v22                                  ; 3e002c10
	v_mac_f32_e32 v1, s17, v22                                  ; 3e022c11
	v_mac_f32_e32 v2, s18, v22                                  ; 3e042c12
	v_mac_f32_e32 v3, s19, v22                                  ; 3e062c13
	v_mac_f32_e32 v5, s20, v22                                  ; 3e0a2c14
	v_mac_f32_e32 v6, s21, v22                                  ; 3e0c2c15
	v_mac_f32_e32 v7, s22, v22                                  ; 3e0e2c16
	v_mac_f32_e32 v8, s23, v22                                  ; 3e102c17
	v_mac_f32_e32 v9, s24, v22                                  ; 3e122c18
	v_mac_f32_e32 v10, s25, v22                                 ; 3e142c19
	v_mac_f32_e32 v11, s26, v22                                 ; 3e162c1a
	v_mac_f32_e32 v12, s27, v22                                 ; 3e182c1b
	v_mac_f32_e32 v13, s28, v22                                 ; 3e1a2c1c
	v_mac_f32_e32 v14, s29, v22                                 ; 3e1c2c1d
	v_mac_f32_e32 v30, s30, v22                                 ; 3e3c2c1e
BB48:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v23                                    ; 7c222e80
	s_cbranch_execz BB54                                        ; bf880013
BB49:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x4c0            ; f4300430 fa0004c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v23                                 ; 3e1e2e1f
	v_mac_f32_e32 v0, s16, v23                                  ; 3e002e10
	v_mac_f32_e32 v1, s17, v23                                  ; 3e022e11
	v_mac_f32_e32 v2, s18, v23                                  ; 3e042e12
	v_mac_f32_e32 v3, s19, v23                                  ; 3e062e13
	v_mac_f32_e32 v5, s20, v23                                  ; 3e0a2e14
	v_mac_f32_e32 v6, s21, v23                                  ; 3e0c2e15
	v_mac_f32_e32 v7, s22, v23                                  ; 3e0e2e16
	v_mac_f32_e32 v8, s23, v23                                  ; 3e102e17
	v_mac_f32_e32 v9, s24, v23                                  ; 3e122e18
	v_mac_f32_e32 v10, s25, v23                                 ; 3e142e19
	v_mac_f32_e32 v11, s26, v23                                 ; 3e162e1a
	v_mac_f32_e32 v12, s27, v23                                 ; 3e182e1b
	v_mac_f32_e32 v13, s28, v23                                 ; 3e1a2e1c
	v_mac_f32_e32 v14, s29, v23                                 ; 3e1c2e1d
	v_mac_f32_e32 v30, s30, v23                                 ; 3e3c2e1e
BB54:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v24                                    ; 7c223080
	s_cbranch_execz BB60                                        ; bf880013
BB55:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x500            ; f4300430 fa000500
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v24                                 ; 3e1e301f
	v_mac_f32_e32 v0, s16, v24                                  ; 3e003010
	v_mac_f32_e32 v1, s17, v24                                  ; 3e023011
	v_mac_f32_e32 v2, s18, v24                                  ; 3e043012
	v_mac_f32_e32 v3, s19, v24                                  ; 3e063013
	v_mac_f32_e32 v5, s20, v24                                  ; 3e0a3014
	v_mac_f32_e32 v6, s21, v24                                  ; 3e0c3015
	v_mac_f32_e32 v7, s22, v24                                  ; 3e0e3016
	v_mac_f32_e32 v8, s23, v24                                  ; 3e103017
	v_mac_f32_e32 v9, s24, v24                                  ; 3e123018
	v_mac_f32_e32 v10, s25, v24                                 ; 3e143019
	v_mac_f32_e32 v11, s26, v24                                 ; 3e16301a
	v_mac_f32_e32 v12, s27, v24                                 ; 3e18301b
	v_mac_f32_e32 v13, s28, v24                                 ; 3e1a301c
	v_mac_f32_e32 v14, s29, v24                                 ; 3e1c301d
	v_mac_f32_e32 v30, s30, v24                                 ; 3e3c301e
BB60:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v25                                    ; 7c223280
	s_cbranch_execz BB66                                        ; bf880013
BB61:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x540            ; f4300430 fa000540
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v25                                 ; 3e1e321f
	v_mac_f32_e32 v0, s16, v25                                  ; 3e003210
	v_mac_f32_e32 v1, s17, v25                                  ; 3e023211
	v_mac_f32_e32 v2, s18, v25                                  ; 3e043212
	v_mac_f32_e32 v3, s19, v25                                  ; 3e063213
	v_mac_f32_e32 v5, s20, v25                                  ; 3e0a3214
	v_mac_f32_e32 v6, s21, v25                                  ; 3e0c3215
	v_mac_f32_e32 v7, s22, v25                                  ; 3e0e3216
	v_mac_f32_e32 v8, s23, v25                                  ; 3e103217
	v_mac_f32_e32 v9, s24, v25                                  ; 3e123218
	v_mac_f32_e32 v10, s25, v25                                 ; 3e143219
	v_mac_f32_e32 v11, s26, v25                                 ; 3e16321a
	v_mac_f32_e32 v12, s27, v25                                 ; 3e18321b
	v_mac_f32_e32 v13, s28, v25                                 ; 3e1a321c
	v_mac_f32_e32 v14, s29, v25                                 ; 3e1c321d
	v_mac_f32_e32 v30, s30, v25                                 ; 3e3c321e
BB66:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v26                                    ; 7c223480
	s_cbranch_execz BB72                                        ; bf880013
BB67:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x580            ; f4300430 fa000580
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v26                                 ; 3e1e341f
	v_mac_f32_e32 v0, s16, v26                                  ; 3e003410
	v_mac_f32_e32 v1, s17, v26                                  ; 3e023411
	v_mac_f32_e32 v2, s18, v26                                  ; 3e043412
	v_mac_f32_e32 v3, s19, v26                                  ; 3e063413
	v_mac_f32_e32 v5, s20, v26                                  ; 3e0a3414
	v_mac_f32_e32 v6, s21, v26                                  ; 3e0c3415
	v_mac_f32_e32 v7, s22, v26                                  ; 3e0e3416
	v_mac_f32_e32 v8, s23, v26                                  ; 3e103417
	v_mac_f32_e32 v9, s24, v26                                  ; 3e123418
	v_mac_f32_e32 v10, s25, v26                                 ; 3e143419
	v_mac_f32_e32 v11, s26, v26                                 ; 3e16341a
	v_mac_f32_e32 v12, s27, v26                                 ; 3e18341b
	v_mac_f32_e32 v13, s28, v26                                 ; 3e1a341c
	v_mac_f32_e32 v14, s29, v26                                 ; 3e1c341d
	v_mac_f32_e32 v30, s30, v26                                 ; 3e3c341e
BB72:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v27                                    ; 7c223680
	s_cbranch_execz BB78                                        ; bf880013
BB73:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x5c0            ; f4300430 fa0005c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v27                                 ; 3e1e361f
	v_mac_f32_e32 v0, s16, v27                                  ; 3e003610
	v_mac_f32_e32 v1, s17, v27                                  ; 3e023611
	v_mac_f32_e32 v2, s18, v27                                  ; 3e043612
	v_mac_f32_e32 v3, s19, v27                                  ; 3e063613
	v_mac_f32_e32 v5, s20, v27                                  ; 3e0a3614
	v_mac_f32_e32 v6, s21, v27                                  ; 3e0c3615
	v_mac_f32_e32 v7, s22, v27                                  ; 3e0e3616
	v_mac_f32_e32 v8, s23, v27                                  ; 3e103617
	v_mac_f32_e32 v9, s24, v27                                  ; 3e123618
	v_mac_f32_e32 v10, s25, v27                                 ; 3e143619
	v_mac_f32_e32 v11, s26, v27                                 ; 3e16361a
	v_mac_f32_e32 v12, s27, v27                                 ; 3e18361b
	v_mac_f32_e32 v13, s28, v27                                 ; 3e1a361c
	v_mac_f32_e32 v14, s29, v27                                 ; 3e1c361d
	v_mac_f32_e32 v30, s30, v27                                 ; 3e3c361e
BB78:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v28                                    ; 7c223880
	s_cbranch_execz BB84                                        ; bf880013
BB79:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x600            ; f4300430 fa000600
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v28                                 ; 3e1e381f
	v_mac_f32_e32 v0, s16, v28                                  ; 3e003810
	v_mac_f32_e32 v1, s17, v28                                  ; 3e023811
	v_mac_f32_e32 v2, s18, v28                                  ; 3e043812
	v_mac_f32_e32 v3, s19, v28                                  ; 3e063813
	v_mac_f32_e32 v5, s20, v28                                  ; 3e0a3814
	v_mac_f32_e32 v6, s21, v28                                  ; 3e0c3815
	v_mac_f32_e32 v7, s22, v28                                  ; 3e0e3816
	v_mac_f32_e32 v8, s23, v28                                  ; 3e103817
	v_mac_f32_e32 v9, s24, v28                                  ; 3e123818
	v_mac_f32_e32 v10, s25, v28                                 ; 3e143819
	v_mac_f32_e32 v11, s26, v28                                 ; 3e16381a
	v_mac_f32_e32 v12, s27, v28                                 ; 3e18381b
	v_mac_f32_e32 v13, s28, v28                                 ; 3e1a381c
	v_mac_f32_e32 v14, s29, v28                                 ; 3e1c381d
	v_mac_f32_e32 v30, s30, v28                                 ; 3e3c381e
BB84:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v29                                    ; 7c223a80
	s_cbranch_execz BB90                                        ; bf880013
BB85:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x640            ; f4300430 fa000640
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v29                                 ; 3e1e3a1f
	v_mac_f32_e32 v0, s16, v29                                  ; 3e003a10
	v_mac_f32_e32 v1, s17, v29                                  ; 3e023a11
	v_mac_f32_e32 v2, s18, v29                                  ; 3e043a12
	v_mac_f32_e32 v3, s19, v29                                  ; 3e063a13
	v_mac_f32_e32 v5, s20, v29                                  ; 3e0a3a14
	v_mac_f32_e32 v6, s21, v29                                  ; 3e0c3a15
	v_mac_f32_e32 v7, s22, v29                                  ; 3e0e3a16
	v_mac_f32_e32 v8, s23, v29                                  ; 3e103a17
	v_mac_f32_e32 v9, s24, v29                                  ; 3e123a18
	v_mac_f32_e32 v10, s25, v29                                 ; 3e143a19
	v_mac_f32_e32 v11, s26, v29                                 ; 3e163a1a
	v_mac_f32_e32 v12, s27, v29                                 ; 3e183a1b
	v_mac_f32_e32 v13, s28, v29                                 ; 3e1a3a1c
	v_mac_f32_e32 v14, s29, v29                                 ; 3e1c3a1d
	v_mac_f32_e32 v30, s30, v29                                 ; 3e3c3a1e
BB90:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v4                                     ; 7c220880
	s_cbranch_execz BB96                                        ; bf880013
BB91:
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x680            ; f4300430 fa000680
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s31, v4                                  ; 3e1e081f
	v_mac_f32_e32 v0, s16, v4                                   ; 3e000810
	v_mac_f32_e32 v1, s17, v4                                   ; 3e020811
	v_mac_f32_e32 v2, s18, v4                                   ; 3e040812
	v_mac_f32_e32 v3, s19, v4                                   ; 3e060813
	v_mac_f32_e32 v5, s20, v4                                   ; 3e0a0814
	v_mac_f32_e32 v6, s21, v4                                   ; 3e0c0815
	v_mac_f32_e32 v7, s22, v4                                   ; 3e0e0816
	v_mac_f32_e32 v8, s23, v4                                   ; 3e100817
	v_mac_f32_e32 v9, s24, v4                                   ; 3e120818
	v_mac_f32_e32 v10, s25, v4                                  ; 3e140819
	v_mac_f32_e32 v11, s26, v4                                  ; 3e16081a
	v_mac_f32_e32 v12, s27, v4                                  ; 3e18081b
	v_mac_f32_e32 v13, s28, v4                                  ; 3e1a081c
	v_mac_f32_e32 v14, s29, v4                                  ; 3e1c081d
	v_mac_f32_e32 v30, s30, v4                                  ; 3e3c081e
BB96:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x840               ; f4280130 fa000840
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v0                                     ; 7c220080
	s_cbranch_execz BB100                                       ; bf880009
BB97:
	s_buffer_load_dwordx4 s[8:11], s[96:99], 0x6c0              ; f4280230 fa0006c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v4, s8, v0, s4                                    ; d5410004 00120008
	v_mad_f32 v16, s9, v0, s5                                   ; d5410010 00160009
	v_mad_f32 v0, s10, v0, s6                                   ; d5410000 001a000a
BB100:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mov_b32_e32 v0, s6                                        ; 7e000206
	v_mov_b32_e32 v4, s4                                        ; 7e080204
	v_mov_b32_e32 v16, s5                                       ; 7e200205
BB102:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v1                                     ; 7c220280
	s_cbranch_execz BB108                                       ; bf880006
BB103:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x6d0               ; f4280130 fa0006d0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v1                                    ; 3e080204
	v_mac_f32_e32 v16, s5, v1                                   ; 3e200205
	v_mac_f32_e32 v0, s6, v1                                    ; 3e000206
BB108:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v2                                     ; 7c220480
	s_cbranch_execz BB114                                       ; bf880006
BB109:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x6e0               ; f4280130 fa0006e0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v2                                    ; 3e080404
	v_mac_f32_e32 v16, s5, v2                                   ; 3e200405
	v_mac_f32_e32 v0, s6, v2                                    ; 3e000406
BB114:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v3                                     ; 7c220680
	s_cbranch_execz BB120                                       ; bf880006
BB115:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x6f0               ; f4280130 fa0006f0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v3                                    ; 3e080604
	v_mac_f32_e32 v16, s5, v3                                   ; 3e200605
	v_mac_f32_e32 v0, s6, v3                                    ; 3e000606
BB120:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v5                                     ; 7c220a80
	s_cbranch_execz BB126                                       ; bf880006
BB121:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x700               ; f4280130 fa000700
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v5                                    ; 3e080a04
	v_mac_f32_e32 v16, s5, v5                                   ; 3e200a05
	v_mac_f32_e32 v0, s6, v5                                    ; 3e000a06
BB126:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v6                                     ; 7c220c80
	s_cbranch_execz BB132                                       ; bf880006
BB127:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x710               ; f4280130 fa000710
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v6                                    ; 3e080c04
	v_mac_f32_e32 v16, s5, v6                                   ; 3e200c05
	v_mac_f32_e32 v0, s6, v6                                    ; 3e000c06
BB132:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v7                                     ; 7c220e80
	s_cbranch_execz BB138                                       ; bf880006
BB133:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x720               ; f4280130 fa000720
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v7                                    ; 3e080e04
	v_mac_f32_e32 v16, s5, v7                                   ; 3e200e05
	v_mac_f32_e32 v0, s6, v7                                    ; 3e000e06
BB138:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v8                                     ; 7c221080
	s_cbranch_execz BB144                                       ; bf880006
BB139:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x730               ; f4280130 fa000730
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v8                                    ; 3e081004
	v_mac_f32_e32 v16, s5, v8                                   ; 3e201005
	v_mac_f32_e32 v0, s6, v8                                    ; 3e001006
BB144:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v9                                     ; 7c221280
	s_cbranch_execz BB150                                       ; bf880006
BB145:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x740               ; f4280130 fa000740
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v9                                    ; 3e081204
	v_mac_f32_e32 v16, s5, v9                                   ; 3e201205
	v_mac_f32_e32 v0, s6, v9                                    ; 3e001206
BB150:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v10                                    ; 7c221480
	s_cbranch_execz BB156                                       ; bf880006
BB151:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x750               ; f4280130 fa000750
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v10                                   ; 3e081404
	v_mac_f32_e32 v16, s5, v10                                  ; 3e201405
	v_mac_f32_e32 v0, s6, v10                                   ; 3e001406
BB156:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v11                                    ; 7c221680
	s_cbranch_execz BB162                                       ; bf880006
BB157:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x760               ; f4280130 fa000760
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v11                                   ; 3e081604
	v_mac_f32_e32 v16, s5, v11                                  ; 3e201605
	v_mac_f32_e32 v0, s6, v11                                   ; 3e001606
BB162:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v12                                    ; 7c221880
	s_cbranch_execz BB168                                       ; bf880006
BB163:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x770               ; f4280130 fa000770
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v12                                   ; 3e081804
	v_mac_f32_e32 v16, s5, v12                                  ; 3e201805
	v_mac_f32_e32 v0, s6, v12                                   ; 3e001806
BB168:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v13                                    ; 7c221a80
	s_cbranch_execz BB174                                       ; bf880006
BB169:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x780               ; f4280130 fa000780
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v13                                   ; 3e081a04
	v_mac_f32_e32 v16, s5, v13                                  ; 3e201a05
	v_mac_f32_e32 v0, s6, v13                                   ; 3e001a06
BB174:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v14                                    ; 7c221c80
	s_cbranch_execz BB180                                       ; bf880006
BB175:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x790               ; f4280130 fa000790
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v14                                   ; 3e081c04
	v_mac_f32_e32 v16, s5, v14                                  ; 3e201c05
	v_mac_f32_e32 v0, s6, v14                                   ; 3e001c06
BB180:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v30                                    ; 7c223c80
	s_cbranch_execz BB186                                       ; bf880006
BB181:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x7a0               ; f4280130 fa0007a0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v30                                   ; 3e083c04
	v_mac_f32_e32 v16, s5, v30                                  ; 3e203c05
	v_mac_f32_e32 v0, s6, v30                                   ; 3e003c06
BB186:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cmpx_lt_f32_e32 0, v15                                    ; 7c221e80
	s_cbranch_execz BB192                                       ; bf880006
BB187:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x7b0               ; f4280130 fa0007b0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v4, s4, v15                                   ; 3e081e04
	v_mac_f32_e32 v16, s5, v15                                  ; 3e201e05
	v_mac_f32_e32 v0, s6, v15                                   ; 3e001e06
BB192:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_mul_f32_e32 v4, 0x3fb8aa3b, v4                            ; 100808ff 3fb8aa3b
	v_mul_f32_e32 v16, 0x3fb8aa3b, v16                          ; 102020ff 3fb8aa3b
	v_exp_f32_e64 v4, -v4                                       ; d5a50004 20000104
	v_exp_f32_e64 v16, -v16                                     ; d5a50010 20000110
	v_add_f32_e32 v4, 1.0, v4                                   ; 060808f2
	v_add_f32_e32 v16, 1.0, v16                                 ; 062020f2
	v_rcp_f32_e32 v4, v4                                        ; 7e085504
	v_rcp_f32_e32 v16, v16                                      ; 7e205510
	v_add_f32_e32 v1, 0x3d6147ae, v4                            ; 060208ff 3d6147ae
	v_mul_f32_e32 v2, 0x3d9e8391, v4                            ; 100408ff 3d9e8391
	v_cmp_ge_f32_e32 vcc, 0x3d25aee6, v4                        ; 7c0c08ff 3d25aee6
	v_mul_f32_e32 v0, 0x3fb8aa3b, v0                            ; 100000ff 3fb8aa3b
	v_add_f32_e32 v3, 0x3d6147ae, v16                           ; 060620ff 3d6147ae
	v_mul_f32_e32 v4, 0x3d9e8391, v16                           ; 100820ff 3d9e8391
	v_mul_f32_e32 v1, 0x3f72a76f, v1                            ; 100202ff 3f72a76f
	v_exp_f32_e64 v0, -v0                                       ; d5a50000 20000100
	v_mul_f32_e32 v3, 0x3f72a76f, v3                            ; 100606ff 3f72a76f
	v_log_f32_e32 v1, v1                                        ; 7e024f01
	v_log_f32_e32 v3, v3                                        ; 7e064f03
	v_add_f32_e32 v0, 1.0, v0                                   ; 060000f2
	v_mul_f32_e32 v1, 0x4019999a, v1                            ; 100202ff 4019999a
	v_rcp_f32_e32 v0, v0                                        ; 7e005500
	v_mul_f32_e32 v3, 0x4019999a, v3                            ; 100606ff 4019999a
	v_exp_f32_e32 v1, v1                                        ; 7e024b01
	v_exp_f32_e32 v3, v3                                        ; 7e064b03
	v_add_f32_e32 v5, 0x3d6147ae, v0                            ; 060a00ff 3d6147ae
	v_mul_f32_e32 v6, 0x3d9e8391, v0                            ; 100c00ff 3d9e8391
	v_cndmask_b32_e32 v1, v1, v2, vcc                           ; 02020501
	v_cmp_ge_f32_e32 vcc, 0x3d25aee6, v16                       ; 7c0c20ff 3d25aee6
	v_mul_f32_e32 v5, 0x3f72a76f, v5                            ; 100a0aff 3f72a76f
	v_cndmask_b32_e32 v3, v3, v4, vcc                           ; 02060903
	v_cmp_ge_f32_e32 vcc, 0x3d25aee6, v0                        ; 7c0c00ff 3d25aee6
	v_log_f32_e32 v5, v5                                        ; 7e0a4f05
	v_cvt_pkrtz_f16_f32_e32 v1, v1, v3                          ; 5e020701
	v_mul_f32_e32 v5, 0x4019999a, v5                            ; 100a0aff 4019999a
	v_exp_f32_e32 v5, v5                                        ; 7e0a4b05
	v_cndmask_b32_e32 v5, v5, v6, vcc                           ; 020a0d05
	v_cvt_pkrtz_f16_f32_e64 v5, v5, 1.0                         ; d52f0005 0001e505
	exp mrt0 v1, v1, v5, v5 done compr vm                       ; f8001c0f 80800501
	s_endpgm                                                    ; bf810000
