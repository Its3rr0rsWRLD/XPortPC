# Pixel Shader
BB0:
	s_mov_b32 s4, s3                                            ; be840303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x50                       ; f4080401 fa000050
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v3, v2], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00820403 00000002
	v_mov_b32_e32 v31, v2                                       ; 7e3e0302
	v_mov_b32_e32 v30, v3                                       ; 7e3c0303
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_eq_f32_e32 vcc, 0, v4                                 ; 7c040880
	s_andn2_b64 exec, exec, vcc                                 ; 8afe6a7e
	s_andn2_b64 s[0:1], s[0:1], vcc                             ; 8a806a00
	s_cbranch_scc0 BB193                                        ; bf84038b
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[8:15], s[2:3], 0x60                        ; f40c0201 fa000060
	s_load_dwordx4 s[4:7], s[2:3], 0xb0                         ; f4080101 fa0000b0
	s_load_dwordx4 s[16:19], s[2:3], 0xd0                       ; f4080401 fa0000d0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[8:11], v[30:31], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 0022081e
	s_mov_b64 s[20:21], s[0:1]                                  ; be940400
	s_mov_b64 s[96:97], s[16:17]                                ; bee00410
	s_mov_b64 s[98:99], s[18:19]                                ; bee20412
	s_mov_b64 s[100:101], s[20:21]                              ; bee40414
	s_clause 0x3                                                ; bfa10003
	s_buffer_load_dwordx16 s[32:47], s[16:19], null             ; f4300808 fa000000
	s_buffer_load_dwordx16 s[48:63], s[16:19], 0x7c0            ; f4300c08 fa0007c0
	s_buffer_load_dwordx16 s[64:79], s[16:19], 0x40             ; f4301008 fa000040
	s_buffer_load_dwordx16 s[80:95], s[16:19], 0x80             ; f4301408 fa000080
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[0:15], s[16:19], 0xc0              ; f4300008 fa0000c0
	s_buffer_load_dwordx16 s[16:31], s[16:19], 0x100            ; f4300408 fa000100
	v_interp_p1_f32_e32 v12, v0, attr0.w                        ; c8300300
	v_interp_p1_f32_e32 v14, v0, attr1.x                        ; c8380400
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v12, v1, attr0.w                        ; c8310301
	v_interp_p2_f32_e32 v14, v1, attr1.x                        ; c8390401
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mad_f32 v7, 2.0, v7, -1.0                                 ; d5410007 03ce0ef4
	v_mul_f32_e32 v13, v12, v12                                 ; 101a190c
	v_mac_f32_e32 v13, v14, v14                                 ; 3e1a1d0e
	v_mac_f32_e32 v13, v0, v0                                   ; 3e1a0100
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_mov_b64 s[102:103], s[42:43]                              ; bee6042a
	s_mov_b64 s[104:105], s[44:45]                              ; bee8042c
	s_mov_b64 vcc, s[46:47]                                     ; beea042e
	v_mad_f32 v16, s33, v4, s49                                 ; d5410010 00c60821
	s_mov_b32 s49, s38                                          ; beb10326
	v_mad_f32 v17, s34, v4, s50                                 ; d5410011 00ca0822
	s_mov_b32 s50, s39                                          ; beb20327
	v_mad_f32 v18, s35, v4, s51                                 ; d5410012 00ce0823
	s_mov_b32 s51, s40                                          ; beb30328
	v_mad_f32 v19, s36, v4, s52                                 ; d5410013 00d20824
	s_mov_b32 s52, s41                                          ; beb40329
	v_mad_f32 v15, s32, v4, s48                                 ; d541000f 00c20820
	s_mov_b32 s48, s37                                          ; beb00325
	s_buffer_load_dwordx16 s[32:47], s[96:99], 0x140            ; f4300830 fa000140
	v_rsq_f32_e32 v13, v13                                      ; 7e1a5d0d
	v_mad_f32 v21, s49, v4, s54                                 ; d5410015 00da0831
	v_mad_f32 v25, s102, v4, s58                                ; d5410019 00ea0866
	v_mad_f32 v22, s50, v4, s55                                 ; d5410016 00de0832
	v_mad_f32 v26, s103, v4, s59                                ; d541001a 00ee0867
	v_mad_f32 v27, s104, v4, s60                                ; d541001b 00f20868
	v_mad_f32 v23, s51, v4, s56                                 ; d5410017 00e20833
	s_mov_b32 s102, s61                                         ; bee6033d
	s_mov_b32 s103, s62                                         ; bee7033e
	v_mad_f32 v24, s52, v4, s57                                 ; d5410018 00e60834
	s_mov_b32 s104, s63                                         ; bee8033f
	v_mad_f32 v20, s48, v4, s53                                 ; d5410014 00d60830
	s_buffer_load_dwordx16 s[48:63], s[96:99], 0x180            ; f4300c30 fa000180
	v_mac_f32_e32 v15, s64, v5                                  ; 3e1e0a40
	v_mac_f32_e32 v16, s65, v5                                  ; 3e200a41
	v_mac_f32_e32 v17, s66, v5                                  ; 3e220a42
	v_mac_f32_e32 v18, s67, v5                                  ; 3e240a43
	v_mac_f32_e32 v19, s68, v5                                  ; 3e260a44
	v_mac_f32_e32 v21, s70, v5                                  ; 3e2a0a46
	v_mad_f32 v28, s105, v4, s102                               ; d541001c 019a0869
	v_mad_f32 v29, vcc_lo, v4, s103                             ; d541001d 019e086a
	v_mac_f32_e32 v22, s71, v5                                  ; 3e2c0a47
	v_mac_f32_e32 v23, s72, v5                                  ; 3e2e0a48
	v_mad_f32 v4, vcc_hi, v4, s104                              ; d5410004 01a2086b
	s_mov_b32 s102, s77                                         ; bee6034d
	v_mac_f32_e32 v24, s73, v5                                  ; 3e300a49
	s_mov_b32 s103, s78                                         ; bee7034e
	s_mov_b32 s104, s79                                         ; bee8034f
	s_mov_b32 s105, s74                                         ; bee9034a
	v_mac_f32_e32 v20, s69, v5                                  ; 3e280a45
	s_mov_b32 vcc_lo, s75                                       ; beea034b
	s_mov_b32 vcc_hi, s76                                       ; beeb034c
	s_buffer_load_dwordx16 s[64:79], s[96:99], 0x1c0            ; f4301030 fa0001c0
	v_mul_f32_e32 v0, v0, v13                                   ; 10001b00
	v_mul_f32_e32 v12, v12, v13                                 ; 10181b0c
	v_mul_f32_e32 v14, v14, v13                                 ; 101c1b0e
	v_mac_f32_e32 v28, s102, v5                                 ; 3e380a66
	v_mac_f32_e32 v15, s80, v6                                  ; 3e1e0c50
	v_mac_f32_e32 v16, s81, v6                                  ; 3e200c51
	v_mac_f32_e32 v29, s103, v5                                 ; 3e3a0a67
	v_mac_f32_e32 v17, s82, v6                                  ; 3e220c52
	v_mac_f32_e32 v4, s104, v5                                  ; 3e080a68
	v_mac_f32_e32 v18, s83, v6                                  ; 3e240c53
	v_mac_f32_e32 v25, s105, v5                                 ; 3e320a69
	v_mac_f32_e32 v19, s84, v6                                  ; 3e260c54
	v_mac_f32_e32 v21, s86, v6                                  ; 3e2a0c56
	v_mac_f32_e32 v26, vcc_lo, v5                               ; 3e340a6a
	v_mac_f32_e32 v27, vcc_hi, v5                               ; 3e360a6b
	v_mac_f32_e32 v22, s87, v6                                  ; 3e2c0c57
	v_mac_f32_e32 v20, s85, v6                                  ; 3e280c55
	v_mac_f32_e32 v23, s88, v6                                  ; 3e2e0c58
	v_mac_f32_e32 v24, s89, v6                                  ; 3e300c59
	s_mov_b32 s102, s93                                         ; bee6035d
	s_mov_b32 s103, s94                                         ; bee7035e
	s_mov_b32 s104, s95                                         ; bee8035f
	s_mov_b32 s105, s90                                         ; bee9035a
	s_mov_b32 vcc_lo, s91                                       ; beea035b
	s_mov_b32 vcc_hi, s92                                       ; beeb035c
	s_buffer_load_dwordx16 s[80:95], s[96:99], 0x200            ; f4301430 fa000200
	v_mac_f32_e32 v15, s0, v7                                   ; 3e1e0e00
	v_mac_f32_e32 v16, s1, v7                                   ; 3e200e01
	v_mac_f32_e32 v17, s2, v7                                   ; 3e220e02
	v_mac_f32_e32 v18, s3, v7                                   ; 3e240e03
	v_mac_f32_e32 v19, s4, v7                                   ; 3e260e04
	v_mac_f32_e32 v28, s102, v6                                 ; 3e380c66
	v_mac_f32_e32 v20, s5, v7                                   ; 3e280e05
	v_mac_f32_e32 v21, s6, v7                                   ; 3e2a0e06
	v_mac_f32_e32 v29, s103, v6                                 ; 3e3a0c67
	v_mac_f32_e32 v22, s7, v7                                   ; 3e2c0e07
	v_mac_f32_e32 v4, s104, v6                                  ; 3e080c68
	v_mac_f32_e32 v23, s8, v7                                   ; 3e2e0e08
	v_mac_f32_e32 v25, s105, v6                                 ; 3e320c69
	v_mac_f32_e32 v26, vcc_lo, v6                               ; 3e340c6a
	v_mac_f32_e32 v24, s9, v7                                   ; 3e300e09
	s_mov_b32 s102, s13                                         ; bee6030d
	v_mac_f32_e32 v27, vcc_hi, v6                               ; 3e360c6b
	s_mov_b32 s103, s14                                         ; bee7030e
	s_mov_b32 s104, s15                                         ; bee8030f
	s_mov_b32 s105, s10                                         ; bee9030a
	s_mov_b32 vcc_lo, s11                                       ; beea030b
	s_mov_b32 vcc_hi, s12                                       ; beeb030c
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x240             ; f4300030 fa000240
	v_mac_f32_e32 v28, s102, v7                                 ; 3e380e66
	v_mac_f32_e32 v29, s103, v7                                 ; 3e3a0e67
	v_mac_f32_e32 v4, s104, v7                                  ; 3e080e68
	v_mac_f32_e32 v25, s105, v7                                 ; 3e320e69
	v_mac_f32_e32 v26, vcc_lo, v7                               ; 3e340e6a
	v_mac_f32_e32 v27, vcc_hi, v7                               ; 3e360e6b
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v28, s29, v8                                  ; 3e38101d
	v_mac_f32_e32 v29, s30, v8                                  ; 3e3a101e
	v_mac_f32_e32 v17, s18, v8                                  ; 3e221012
	v_mac_f32_e32 v26, s27, v8                                  ; 3e34101b
	v_mac_f32_e32 v18, s19, v8                                  ; 3e241013
	v_mac_f32_e32 v27, s28, v8                                  ; 3e36101c
	v_mac_f32_e32 v4, s31, v8                                   ; 3e08101f
	v_mac_f32_e32 v23, s24, v8                                  ; 3e2e1018
	v_mac_f32_e32 v21, s22, v8                                  ; 3e2a1016
	v_mac_f32_e32 v15, s16, v8                                  ; 3e1e1010
	v_mac_f32_e32 v25, s26, v8                                  ; 3e32101a
	v_mac_f32_e32 v19, s20, v8                                  ; 3e261014
	v_mac_f32_e32 v22, s23, v8                                  ; 3e2c1017
	v_mac_f32_e32 v20, s21, v8                                  ; 3e281015
	v_mac_f32_e32 v24, s25, v8                                  ; 3e301019
	v_mac_f32_e32 v16, s17, v8                                  ; 3e201011
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v17, s34, v9                                  ; 3e221222
	v_mac_f32_e32 v18, s35, v9                                  ; 3e241223
	v_mac_f32_e32 v26, s43, v9                                  ; 3e34122b
	v_mac_f32_e32 v23, s40, v9                                  ; 3e2e1228
	v_mac_f32_e32 v27, s44, v9                                  ; 3e36122c
	v_mac_f32_e32 v21, s38, v9                                  ; 3e2a1226
	v_mac_f32_e32 v28, s45, v9                                  ; 3e38122d
	v_mac_f32_e32 v15, s32, v9                                  ; 3e1e1220
	v_mac_f32_e32 v29, s46, v9                                  ; 3e3a122e
	v_mac_f32_e32 v25, s42, v9                                  ; 3e32122a
	v_mac_f32_e32 v4, s47, v9                                   ; 3e08122f
	v_mac_f32_e32 v19, s36, v9                                  ; 3e261224
	v_mac_f32_e32 v22, s39, v9                                  ; 3e2c1227
	v_mac_f32_e32 v20, s37, v9                                  ; 3e281225
	v_mac_f32_e32 v24, s41, v9                                  ; 3e301229
	v_mac_f32_e32 v16, s33, v9                                  ; 3e201221
	v_mac_f32_e32 v17, s50, v10                                 ; 3e221432
	v_mac_f32_e32 v18, s51, v10                                 ; 3e241433
	v_mac_f32_e32 v23, s56, v10                                 ; 3e2e1438
	v_mac_f32_e32 v21, s54, v10                                 ; 3e2a1436
	v_mac_f32_e32 v26, s59, v10                                 ; 3e34143b
	v_mac_f32_e32 v15, s48, v10                                 ; 3e1e1430
	v_mac_f32_e32 v27, s60, v10                                 ; 3e36143c
	s_buffer_load_dwordx16 s[16:31], s[96:99], 0x280            ; f4300430 fa000280
	v_mac_f32_e32 v28, s61, v10                                 ; 3e38143d
	v_mac_f32_e32 v29, s62, v10                                 ; 3e3a143e
	v_mac_f32_e32 v25, s58, v10                                 ; 3e32143a
	v_mac_f32_e32 v4, s63, v10                                  ; 3e08143f
	v_mad_f32 v11, 2.0, v11, -1.0                               ; d541000b 03ce16f4
	v_mac_f32_e32 v19, s52, v10                                 ; 3e261434
	v_mac_f32_e32 v22, s55, v10                                 ; 3e2c1437
	v_mac_f32_e32 v20, s53, v10                                 ; 3e281435
	v_mac_f32_e32 v24, s57, v10                                 ; 3e301439
	v_mac_f32_e32 v16, s49, v10                                 ; 3e201431
	v_mac_f32_e32 v27, s76, v11                                 ; 3e36164c
	v_mac_f32_e32 v4, s79, v11                                  ; 3e08164f
	v_mac_f32_e32 v18, s67, v11                                 ; 3e241643
	v_mac_f32_e32 v21, s70, v11                                 ; 3e2a1646
	v_mac_f32_e32 v28, s77, v11                                 ; 3e38164d
	v_mac_f32_e32 v15, s64, v11                                 ; 3e1e1640
	v_mac_f32_e32 v29, s78, v11                                 ; 3e3a164e
	s_buffer_load_dwordx16 s[32:47], s[96:99], 0x800            ; f4300830 fa000800
	v_mac_f32_e32 v25, s74, v11                                 ; 3e32164a
	v_mac_f32_e32 v26, s75, v11                                 ; 3e34164b
	v_mac_f32_e32 v17, s66, v11                                 ; 3e221642
	v_mac_f32_e32 v23, s72, v11                                 ; 3e2e1648
	v_mac_f32_e32 v19, s68, v11                                 ; 3e261644
	v_mac_f32_e32 v22, s71, v11                                 ; 3e2c1647
	v_mac_f32_e32 v20, s69, v11                                 ; 3e281645
	v_mac_f32_e32 v24, s73, v11                                 ; 3e301649
	v_mac_f32_e32 v16, s65, v11                                 ; 3e201641
	v_mac_f32_e32 v18, s83, v0                                  ; 3e240053
	v_mac_f32_e32 v21, s86, v0                                  ; 3e2a0056
	v_mac_f32_e32 v15, s80, v0                                  ; 3e1e0050
	v_mac_f32_e32 v27, s92, v0                                  ; 3e36005c
	v_mac_f32_e32 v25, s90, v0                                  ; 3e32005a
	v_mac_f32_e32 v28, s93, v0                                  ; 3e38005d
	v_mac_f32_e32 v26, s91, v0                                  ; 3e34005b
	v_mac_f32_e32 v29, s94, v0                                  ; 3e3a005e
	v_mac_f32_e32 v17, s82, v0                                  ; 3e220052
	v_mac_f32_e32 v23, s88, v0                                  ; 3e2e0058
	v_mac_f32_e32 v4, s95, v0                                   ; 3e08005f
	v_mac_f32_e32 v19, s84, v0                                  ; 3e260054
	v_mac_f32_e32 v22, s87, v0                                  ; 3e2c0057
	v_mac_f32_e32 v20, s85, v0                                  ; 3e280055
	v_mac_f32_e32 v24, s89, v0                                  ; 3e300059
	v_mac_f32_e32 v16, s81, v0                                  ; 3e200051
	v_mad_f32 v18, s3, -v14, v18                                ; d5410012 444a1c03
	v_mad_f32 v21, s6, -v14, v21                                ; d5410015 44561c06
	v_mad_f32 v15, s0, -v14, v15                                ; d541000f 443e1c00
	v_mad_f32 v25, s10, -v14, v25                               ; d5410019 44661c0a
	v_mad_f32 v26, s11, -v14, v26                               ; d541001a 446a1c0b
	v_mad_f32 v27, s12, -v14, v27                               ; d541001b 446e1c0c
	v_mad_f32 v17, s2, -v14, v17                                ; d5410011 44461c02
	v_mad_f32 v28, s13, -v14, v28                               ; d541001c 44721c0d
	v_mad_f32 v23, s8, -v14, v23                                ; d5410017 445e1c08
	v_mad_f32 v29, s14, -v14, v29                               ; d541001d 44761c0e
	v_mad_f32 v19, s4, -v14, v19                                ; d5410013 444e1c04
	v_mad_f32 v22, s7, -v14, v22                                ; d5410016 445a1c07
	v_mad_f32 v20, s5, -v14, v20                                ; d5410014 44521c05
	v_mad_f32 v24, s9, -v14, v24                                ; d5410018 44621c09
	v_mad_f32 v16, s1, -v14, v16                                ; d5410010 44421c01
	v_mad_f32 v14, s15, -v14, v4                                ; d541000e 44121c0f
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v18, s19, v12                                 ; 3e241813
	v_mac_f32_e32 v21, s22, v12                                 ; 3e2a1816
	v_mac_f32_e32 v15, s16, v12                                 ; 3e1e1810
	v_mac_f32_e32 v25, s26, v12                                 ; 3e32181a
	v_mac_f32_e32 v26, s27, v12                                 ; 3e34181b
	v_mac_f32_e32 v17, s18, v12                                 ; 3e221812
	v_mac_f32_e32 v27, s28, v12                                 ; 3e36181c
	v_mac_f32_e32 v23, s24, v12                                 ; 3e2e1818
	v_mac_f32_e32 v28, s29, v12                                 ; 3e38181d
	v_mac_f32_e32 v29, s30, v12                                 ; 3e3a181e
	v_mac_f32_e32 v19, s20, v12                                 ; 3e261814
	v_mac_f32_e32 v22, s23, v12                                 ; 3e2c1817
	v_mac_f32_e32 v20, s21, v12                                 ; 3e281815
	v_mac_f32_e32 v24, s25, v12                                 ; 3e301819
	v_mac_f32_e32 v16, s17, v12                                 ; 3e201811
	v_mac_f32_e32 v14, s31, v12                                 ; 3e1c181f
	v_cmp_lt_f32_e32 vcc, 0, v15                                ; 7c021e80
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	s_and_b64 exec, vcc, exec                                   ; 87fe7e6a
	s_cbranch_execz BB4                                         ; bf880023
BB1:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x2c0             ; f4300030 fa0002c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v0, s0, v15, s32                                  ; d5410000 00821e00
	v_mad_f32 v1, s1, v15, s33                                  ; d5410001 00861e01
	v_mad_f32 v2, s2, v15, s34                                  ; d5410002 008a1e02
	v_mad_f32 v3, s3, v15, s35                                  ; d5410003 008e1e03
	v_mad_f32 v4, s4, v15, s36                                  ; d5410004 00921e04
	v_mad_f32 v5, s5, v15, s37                                  ; d5410005 00961e05
	v_mad_f32 v6, s6, v15, s38                                  ; d5410006 009a1e06
	v_mad_f32 v7, s7, v15, s39                                  ; d5410007 009e1e07
	v_mad_f32 v8, s8, v15, s40                                  ; d5410008 00a21e08
	v_mad_f32 v9, s9, v15, s41                                  ; d5410009 00a61e09
	v_mad_f32 v10, s10, v15, s42                                ; d541000a 00aa1e0a
	v_mad_f32 v11, s11, v15, s43                                ; d541000b 00ae1e0b
	v_mad_f32 v12, s12, v15, s44                                ; d541000c 00b21e0c
	v_mad_f32 v13, s13, v15, s45                                ; d541000d 00b61e0d
	v_mad_f32 v30, s14, v15, s46                                ; d541001e 00ba1e0e
	v_mad_f32 v15, s15, v15, s47                                ; d541000f 00be1e0f
BB4:
	s_andn2_b64 exec, s[100:101], exec                          ; 8afe7e64
	v_lshrrev_b64 v[0:1], 0, s[32:33]                           ; d7000000 00004080
	v_lshrrev_b64 v[2:3], 0, s[34:35]                           ; d7000002 00004480
	v_lshrrev_b64 v[4:5], 0, s[36:37]                           ; d7000004 00004880
	v_lshrrev_b64 v[6:7], 0, s[38:39]                           ; d7000006 00004c80
	v_lshrrev_b64 v[8:9], 0, s[40:41]                           ; d7000008 00005080
	v_lshrrev_b64 v[10:11], 0, s[42:43]                         ; d700000a 00005480
	v_lshrrev_b64 v[12:13], 0, s[44:45]                         ; d700000c 00005880
	v_mov_b32_e32 v15, s47                                      ; 7e1e022f
	v_mov_b32_e32 v30, s46                                      ; 7e3c022e
BB6:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v16                                    ; 7c222080
	s_cbranch_execz BB12                                        ; bf880013
BB7:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x300             ; f4300030 fa000300
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v16                                 ; 3e1e200f
	v_mac_f32_e32 v0, s0, v16                                   ; 3e002000
	v_mac_f32_e32 v1, s1, v16                                   ; 3e022001
	v_mac_f32_e32 v2, s2, v16                                   ; 3e042002
	v_mac_f32_e32 v3, s3, v16                                   ; 3e062003
	v_mac_f32_e32 v4, s4, v16                                   ; 3e082004
	v_mac_f32_e32 v5, s5, v16                                   ; 3e0a2005
	v_mac_f32_e32 v6, s6, v16                                   ; 3e0c2006
	v_mac_f32_e32 v7, s7, v16                                   ; 3e0e2007
	v_mac_f32_e32 v8, s8, v16                                   ; 3e102008
	v_mac_f32_e32 v9, s9, v16                                   ; 3e122009
	v_mac_f32_e32 v10, s10, v16                                 ; 3e14200a
	v_mac_f32_e32 v11, s11, v16                                 ; 3e16200b
	v_mac_f32_e32 v12, s12, v16                                 ; 3e18200c
	v_mac_f32_e32 v13, s13, v16                                 ; 3e1a200d
	v_mac_f32_e32 v30, s14, v16                                 ; 3e3c200e
BB12:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v17                                    ; 7c222280
	s_cbranch_execz BB18                                        ; bf880013
BB13:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x340             ; f4300030 fa000340
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v17                                 ; 3e1e220f
	v_mac_f32_e32 v0, s0, v17                                   ; 3e002200
	v_mac_f32_e32 v1, s1, v17                                   ; 3e022201
	v_mac_f32_e32 v2, s2, v17                                   ; 3e042202
	v_mac_f32_e32 v3, s3, v17                                   ; 3e062203
	v_mac_f32_e32 v4, s4, v17                                   ; 3e082204
	v_mac_f32_e32 v5, s5, v17                                   ; 3e0a2205
	v_mac_f32_e32 v6, s6, v17                                   ; 3e0c2206
	v_mac_f32_e32 v7, s7, v17                                   ; 3e0e2207
	v_mac_f32_e32 v8, s8, v17                                   ; 3e102208
	v_mac_f32_e32 v9, s9, v17                                   ; 3e122209
	v_mac_f32_e32 v10, s10, v17                                 ; 3e14220a
	v_mac_f32_e32 v11, s11, v17                                 ; 3e16220b
	v_mac_f32_e32 v12, s12, v17                                 ; 3e18220c
	v_mac_f32_e32 v13, s13, v17                                 ; 3e1a220d
	v_mac_f32_e32 v30, s14, v17                                 ; 3e3c220e
BB18:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v18                                    ; 7c222480
	s_cbranch_execz BB24                                        ; bf880013
BB19:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x380             ; f4300030 fa000380
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v18                                 ; 3e1e240f
	v_mac_f32_e32 v0, s0, v18                                   ; 3e002400
	v_mac_f32_e32 v1, s1, v18                                   ; 3e022401
	v_mac_f32_e32 v2, s2, v18                                   ; 3e042402
	v_mac_f32_e32 v3, s3, v18                                   ; 3e062403
	v_mac_f32_e32 v4, s4, v18                                   ; 3e082404
	v_mac_f32_e32 v5, s5, v18                                   ; 3e0a2405
	v_mac_f32_e32 v6, s6, v18                                   ; 3e0c2406
	v_mac_f32_e32 v7, s7, v18                                   ; 3e0e2407
	v_mac_f32_e32 v8, s8, v18                                   ; 3e102408
	v_mac_f32_e32 v9, s9, v18                                   ; 3e122409
	v_mac_f32_e32 v10, s10, v18                                 ; 3e14240a
	v_mac_f32_e32 v11, s11, v18                                 ; 3e16240b
	v_mac_f32_e32 v12, s12, v18                                 ; 3e18240c
	v_mac_f32_e32 v13, s13, v18                                 ; 3e1a240d
	v_mac_f32_e32 v30, s14, v18                                 ; 3e3c240e
BB24:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v19                                    ; 7c222680
	s_cbranch_execz BB30                                        ; bf880013
BB25:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x3c0             ; f4300030 fa0003c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v19                                 ; 3e1e260f
	v_mac_f32_e32 v0, s0, v19                                   ; 3e002600
	v_mac_f32_e32 v1, s1, v19                                   ; 3e022601
	v_mac_f32_e32 v2, s2, v19                                   ; 3e042602
	v_mac_f32_e32 v3, s3, v19                                   ; 3e062603
	v_mac_f32_e32 v4, s4, v19                                   ; 3e082604
	v_mac_f32_e32 v5, s5, v19                                   ; 3e0a2605
	v_mac_f32_e32 v6, s6, v19                                   ; 3e0c2606
	v_mac_f32_e32 v7, s7, v19                                   ; 3e0e2607
	v_mac_f32_e32 v8, s8, v19                                   ; 3e102608
	v_mac_f32_e32 v9, s9, v19                                   ; 3e122609
	v_mac_f32_e32 v10, s10, v19                                 ; 3e14260a
	v_mac_f32_e32 v11, s11, v19                                 ; 3e16260b
	v_mac_f32_e32 v12, s12, v19                                 ; 3e18260c
	v_mac_f32_e32 v13, s13, v19                                 ; 3e1a260d
	v_mac_f32_e32 v30, s14, v19                                 ; 3e3c260e
BB30:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v20                                    ; 7c222880
	s_cbranch_execz BB36                                        ; bf880013
BB31:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x400             ; f4300030 fa000400
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v20                                 ; 3e1e280f
	v_mac_f32_e32 v0, s0, v20                                   ; 3e002800
	v_mac_f32_e32 v1, s1, v20                                   ; 3e022801
	v_mac_f32_e32 v2, s2, v20                                   ; 3e042802
	v_mac_f32_e32 v3, s3, v20                                   ; 3e062803
	v_mac_f32_e32 v4, s4, v20                                   ; 3e082804
	v_mac_f32_e32 v5, s5, v20                                   ; 3e0a2805
	v_mac_f32_e32 v6, s6, v20                                   ; 3e0c2806
	v_mac_f32_e32 v7, s7, v20                                   ; 3e0e2807
	v_mac_f32_e32 v8, s8, v20                                   ; 3e102808
	v_mac_f32_e32 v9, s9, v20                                   ; 3e122809
	v_mac_f32_e32 v10, s10, v20                                 ; 3e14280a
	v_mac_f32_e32 v11, s11, v20                                 ; 3e16280b
	v_mac_f32_e32 v12, s12, v20                                 ; 3e18280c
	v_mac_f32_e32 v13, s13, v20                                 ; 3e1a280d
	v_mac_f32_e32 v30, s14, v20                                 ; 3e3c280e
BB36:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v21                                    ; 7c222a80
	s_cbranch_execz BB42                                        ; bf880013
BB37:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x440             ; f4300030 fa000440
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v21                                 ; 3e1e2a0f
	v_mac_f32_e32 v0, s0, v21                                   ; 3e002a00
	v_mac_f32_e32 v1, s1, v21                                   ; 3e022a01
	v_mac_f32_e32 v2, s2, v21                                   ; 3e042a02
	v_mac_f32_e32 v3, s3, v21                                   ; 3e062a03
	v_mac_f32_e32 v4, s4, v21                                   ; 3e082a04
	v_mac_f32_e32 v5, s5, v21                                   ; 3e0a2a05
	v_mac_f32_e32 v6, s6, v21                                   ; 3e0c2a06
	v_mac_f32_e32 v7, s7, v21                                   ; 3e0e2a07
	v_mac_f32_e32 v8, s8, v21                                   ; 3e102a08
	v_mac_f32_e32 v9, s9, v21                                   ; 3e122a09
	v_mac_f32_e32 v10, s10, v21                                 ; 3e142a0a
	v_mac_f32_e32 v11, s11, v21                                 ; 3e162a0b
	v_mac_f32_e32 v12, s12, v21                                 ; 3e182a0c
	v_mac_f32_e32 v13, s13, v21                                 ; 3e1a2a0d
	v_mac_f32_e32 v30, s14, v21                                 ; 3e3c2a0e
BB42:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v22                                    ; 7c222c80
	s_cbranch_execz BB48                                        ; bf880013
BB43:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x480             ; f4300030 fa000480
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v22                                 ; 3e1e2c0f
	v_mac_f32_e32 v0, s0, v22                                   ; 3e002c00
	v_mac_f32_e32 v1, s1, v22                                   ; 3e022c01
	v_mac_f32_e32 v2, s2, v22                                   ; 3e042c02
	v_mac_f32_e32 v3, s3, v22                                   ; 3e062c03
	v_mac_f32_e32 v4, s4, v22                                   ; 3e082c04
	v_mac_f32_e32 v5, s5, v22                                   ; 3e0a2c05
	v_mac_f32_e32 v6, s6, v22                                   ; 3e0c2c06
	v_mac_f32_e32 v7, s7, v22                                   ; 3e0e2c07
	v_mac_f32_e32 v8, s8, v22                                   ; 3e102c08
	v_mac_f32_e32 v9, s9, v22                                   ; 3e122c09
	v_mac_f32_e32 v10, s10, v22                                 ; 3e142c0a
	v_mac_f32_e32 v11, s11, v22                                 ; 3e162c0b
	v_mac_f32_e32 v12, s12, v22                                 ; 3e182c0c
	v_mac_f32_e32 v13, s13, v22                                 ; 3e1a2c0d
	v_mac_f32_e32 v30, s14, v22                                 ; 3e3c2c0e
BB48:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v23                                    ; 7c222e80
	s_cbranch_execz BB54                                        ; bf880013
BB49:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x4c0             ; f4300030 fa0004c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v23                                 ; 3e1e2e0f
	v_mac_f32_e32 v0, s0, v23                                   ; 3e002e00
	v_mac_f32_e32 v1, s1, v23                                   ; 3e022e01
	v_mac_f32_e32 v2, s2, v23                                   ; 3e042e02
	v_mac_f32_e32 v3, s3, v23                                   ; 3e062e03
	v_mac_f32_e32 v4, s4, v23                                   ; 3e082e04
	v_mac_f32_e32 v5, s5, v23                                   ; 3e0a2e05
	v_mac_f32_e32 v6, s6, v23                                   ; 3e0c2e06
	v_mac_f32_e32 v7, s7, v23                                   ; 3e0e2e07
	v_mac_f32_e32 v8, s8, v23                                   ; 3e102e08
	v_mac_f32_e32 v9, s9, v23                                   ; 3e122e09
	v_mac_f32_e32 v10, s10, v23                                 ; 3e142e0a
	v_mac_f32_e32 v11, s11, v23                                 ; 3e162e0b
	v_mac_f32_e32 v12, s12, v23                                 ; 3e182e0c
	v_mac_f32_e32 v13, s13, v23                                 ; 3e1a2e0d
	v_mac_f32_e32 v30, s14, v23                                 ; 3e3c2e0e
BB54:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v24                                    ; 7c223080
	s_cbranch_execz BB60                                        ; bf880013
BB55:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x500             ; f4300030 fa000500
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v24                                 ; 3e1e300f
	v_mac_f32_e32 v0, s0, v24                                   ; 3e003000
	v_mac_f32_e32 v1, s1, v24                                   ; 3e023001
	v_mac_f32_e32 v2, s2, v24                                   ; 3e043002
	v_mac_f32_e32 v3, s3, v24                                   ; 3e063003
	v_mac_f32_e32 v4, s4, v24                                   ; 3e083004
	v_mac_f32_e32 v5, s5, v24                                   ; 3e0a3005
	v_mac_f32_e32 v6, s6, v24                                   ; 3e0c3006
	v_mac_f32_e32 v7, s7, v24                                   ; 3e0e3007
	v_mac_f32_e32 v8, s8, v24                                   ; 3e103008
	v_mac_f32_e32 v9, s9, v24                                   ; 3e123009
	v_mac_f32_e32 v10, s10, v24                                 ; 3e14300a
	v_mac_f32_e32 v11, s11, v24                                 ; 3e16300b
	v_mac_f32_e32 v12, s12, v24                                 ; 3e18300c
	v_mac_f32_e32 v13, s13, v24                                 ; 3e1a300d
	v_mac_f32_e32 v30, s14, v24                                 ; 3e3c300e
BB60:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v25                                    ; 7c223280
	s_cbranch_execz BB66                                        ; bf880013
BB61:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x540             ; f4300030 fa000540
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v25                                 ; 3e1e320f
	v_mac_f32_e32 v0, s0, v25                                   ; 3e003200
	v_mac_f32_e32 v1, s1, v25                                   ; 3e023201
	v_mac_f32_e32 v2, s2, v25                                   ; 3e043202
	v_mac_f32_e32 v3, s3, v25                                   ; 3e063203
	v_mac_f32_e32 v4, s4, v25                                   ; 3e083204
	v_mac_f32_e32 v5, s5, v25                                   ; 3e0a3205
	v_mac_f32_e32 v6, s6, v25                                   ; 3e0c3206
	v_mac_f32_e32 v7, s7, v25                                   ; 3e0e3207
	v_mac_f32_e32 v8, s8, v25                                   ; 3e103208
	v_mac_f32_e32 v9, s9, v25                                   ; 3e123209
	v_mac_f32_e32 v10, s10, v25                                 ; 3e14320a
	v_mac_f32_e32 v11, s11, v25                                 ; 3e16320b
	v_mac_f32_e32 v12, s12, v25                                 ; 3e18320c
	v_mac_f32_e32 v13, s13, v25                                 ; 3e1a320d
	v_mac_f32_e32 v30, s14, v25                                 ; 3e3c320e
BB66:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v26                                    ; 7c223480
	s_cbranch_execz BB72                                        ; bf880013
BB67:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x580             ; f4300030 fa000580
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v26                                 ; 3e1e340f
	v_mac_f32_e32 v0, s0, v26                                   ; 3e003400
	v_mac_f32_e32 v1, s1, v26                                   ; 3e023401
	v_mac_f32_e32 v2, s2, v26                                   ; 3e043402
	v_mac_f32_e32 v3, s3, v26                                   ; 3e063403
	v_mac_f32_e32 v4, s4, v26                                   ; 3e083404
	v_mac_f32_e32 v5, s5, v26                                   ; 3e0a3405
	v_mac_f32_e32 v6, s6, v26                                   ; 3e0c3406
	v_mac_f32_e32 v7, s7, v26                                   ; 3e0e3407
	v_mac_f32_e32 v8, s8, v26                                   ; 3e103408
	v_mac_f32_e32 v9, s9, v26                                   ; 3e123409
	v_mac_f32_e32 v10, s10, v26                                 ; 3e14340a
	v_mac_f32_e32 v11, s11, v26                                 ; 3e16340b
	v_mac_f32_e32 v12, s12, v26                                 ; 3e18340c
	v_mac_f32_e32 v13, s13, v26                                 ; 3e1a340d
	v_mac_f32_e32 v30, s14, v26                                 ; 3e3c340e
BB72:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v27                                    ; 7c223680
	s_cbranch_execz BB78                                        ; bf880013
BB73:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x5c0             ; f4300030 fa0005c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v27                                 ; 3e1e360f
	v_mac_f32_e32 v0, s0, v27                                   ; 3e003600
	v_mac_f32_e32 v1, s1, v27                                   ; 3e023601
	v_mac_f32_e32 v2, s2, v27                                   ; 3e043602
	v_mac_f32_e32 v3, s3, v27                                   ; 3e063603
	v_mac_f32_e32 v4, s4, v27                                   ; 3e083604
	v_mac_f32_e32 v5, s5, v27                                   ; 3e0a3605
	v_mac_f32_e32 v6, s6, v27                                   ; 3e0c3606
	v_mac_f32_e32 v7, s7, v27                                   ; 3e0e3607
	v_mac_f32_e32 v8, s8, v27                                   ; 3e103608
	v_mac_f32_e32 v9, s9, v27                                   ; 3e123609
	v_mac_f32_e32 v10, s10, v27                                 ; 3e14360a
	v_mac_f32_e32 v11, s11, v27                                 ; 3e16360b
	v_mac_f32_e32 v12, s12, v27                                 ; 3e18360c
	v_mac_f32_e32 v13, s13, v27                                 ; 3e1a360d
	v_mac_f32_e32 v30, s14, v27                                 ; 3e3c360e
BB78:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v28                                    ; 7c223880
	s_cbranch_execz BB84                                        ; bf880013
BB79:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x600             ; f4300030 fa000600
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v28                                 ; 3e1e380f
	v_mac_f32_e32 v0, s0, v28                                   ; 3e003800
	v_mac_f32_e32 v1, s1, v28                                   ; 3e023801
	v_mac_f32_e32 v2, s2, v28                                   ; 3e043802
	v_mac_f32_e32 v3, s3, v28                                   ; 3e063803
	v_mac_f32_e32 v4, s4, v28                                   ; 3e083804
	v_mac_f32_e32 v5, s5, v28                                   ; 3e0a3805
	v_mac_f32_e32 v6, s6, v28                                   ; 3e0c3806
	v_mac_f32_e32 v7, s7, v28                                   ; 3e0e3807
	v_mac_f32_e32 v8, s8, v28                                   ; 3e103808
	v_mac_f32_e32 v9, s9, v28                                   ; 3e123809
	v_mac_f32_e32 v10, s10, v28                                 ; 3e14380a
	v_mac_f32_e32 v11, s11, v28                                 ; 3e16380b
	v_mac_f32_e32 v12, s12, v28                                 ; 3e18380c
	v_mac_f32_e32 v13, s13, v28                                 ; 3e1a380d
	v_mac_f32_e32 v30, s14, v28                                 ; 3e3c380e
BB84:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v29                                    ; 7c223a80
	s_cbranch_execz BB90                                        ; bf880013
BB85:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x640             ; f4300030 fa000640
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v29                                 ; 3e1e3a0f
	v_mac_f32_e32 v0, s0, v29                                   ; 3e003a00
	v_mac_f32_e32 v1, s1, v29                                   ; 3e023a01
	v_mac_f32_e32 v2, s2, v29                                   ; 3e043a02
	v_mac_f32_e32 v3, s3, v29                                   ; 3e063a03
	v_mac_f32_e32 v4, s4, v29                                   ; 3e083a04
	v_mac_f32_e32 v5, s5, v29                                   ; 3e0a3a05
	v_mac_f32_e32 v6, s6, v29                                   ; 3e0c3a06
	v_mac_f32_e32 v7, s7, v29                                   ; 3e0e3a07
	v_mac_f32_e32 v8, s8, v29                                   ; 3e103a08
	v_mac_f32_e32 v9, s9, v29                                   ; 3e123a09
	v_mac_f32_e32 v10, s10, v29                                 ; 3e143a0a
	v_mac_f32_e32 v11, s11, v29                                 ; 3e163a0b
	v_mac_f32_e32 v12, s12, v29                                 ; 3e183a0c
	v_mac_f32_e32 v13, s13, v29                                 ; 3e1a3a0d
	v_mac_f32_e32 v30, s14, v29                                 ; 3e3c3a0e
BB90:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v14                                    ; 7c221c80
	s_cbranch_execz BB96                                        ; bf880013
BB91:
	s_buffer_load_dwordx16 s[0:15], s[96:99], 0x680             ; f4300030 fa000680
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v15, s15, v14                                 ; 3e1e1c0f
	v_mac_f32_e32 v0, s0, v14                                   ; 3e001c00
	v_mac_f32_e32 v1, s1, v14                                   ; 3e021c01
	v_mac_f32_e32 v2, s2, v14                                   ; 3e041c02
	v_mac_f32_e32 v3, s3, v14                                   ; 3e061c03
	v_mac_f32_e32 v4, s4, v14                                   ; 3e081c04
	v_mac_f32_e32 v5, s5, v14                                   ; 3e0a1c05
	v_mac_f32_e32 v6, s6, v14                                   ; 3e0c1c06
	v_mac_f32_e32 v7, s7, v14                                   ; 3e0e1c07
	v_mac_f32_e32 v8, s8, v14                                   ; 3e101c08
	v_mac_f32_e32 v9, s9, v14                                   ; 3e121c09
	v_mac_f32_e32 v10, s10, v14                                 ; 3e141c0a
	v_mac_f32_e32 v11, s11, v14                                 ; 3e161c0b
	v_mac_f32_e32 v12, s12, v14                                 ; 3e181c0c
	v_mac_f32_e32 v13, s13, v14                                 ; 3e1a1c0d
	v_mac_f32_e32 v30, s14, v14                                 ; 3e3c1c0e
BB96:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x840               ; f4280030 fa000840
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v0                                     ; 7c220080
	s_cbranch_execz BB100                                       ; bf880009
BB97:
	s_buffer_load_dwordx4 s[4:7], s[96:99], 0x6c0               ; f4280130 fa0006c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v14, s4, v0, s0                                   ; d541000e 00020004
	v_mad_f32 v16, s5, v0, s1                                   ; d5410010 00060005
	v_mad_f32 v0, s6, v0, s2                                    ; d5410000 000a0006
BB100:
	s_andn2_b64 exec, s[100:101], exec                          ; 8afe7e64
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mov_b32_e32 v0, s2                                        ; 7e000202
	v_mov_b32_e32 v14, s0                                       ; 7e1c0200
	v_mov_b32_e32 v16, s1                                       ; 7e200201
BB102:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v1                                     ; 7c220280
	s_cbranch_execz BB108                                       ; bf880006
BB103:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x6d0               ; f4280030 fa0006d0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v1                                   ; 3e1c0200
	v_mac_f32_e32 v16, s1, v1                                   ; 3e200201
	v_mac_f32_e32 v0, s2, v1                                    ; 3e000202
BB108:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v2                                     ; 7c220480
	s_cbranch_execz BB114                                       ; bf880006
BB109:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x6e0               ; f4280030 fa0006e0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v2                                   ; 3e1c0400
	v_mac_f32_e32 v16, s1, v2                                   ; 3e200401
	v_mac_f32_e32 v0, s2, v2                                    ; 3e000402
BB114:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v3                                     ; 7c220680
	s_cbranch_execz BB120                                       ; bf880006
BB115:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x6f0               ; f4280030 fa0006f0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v3                                   ; 3e1c0600
	v_mac_f32_e32 v16, s1, v3                                   ; 3e200601
	v_mac_f32_e32 v0, s2, v3                                    ; 3e000602
BB120:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v4                                     ; 7c220880
	s_cbranch_execz BB126                                       ; bf880006
BB121:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x700               ; f4280030 fa000700
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v4                                   ; 3e1c0800
	v_mac_f32_e32 v16, s1, v4                                   ; 3e200801
	v_mac_f32_e32 v0, s2, v4                                    ; 3e000802
BB126:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v5                                     ; 7c220a80
	s_cbranch_execz BB132                                       ; bf880006
BB127:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x710               ; f4280030 fa000710
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v5                                   ; 3e1c0a00
	v_mac_f32_e32 v16, s1, v5                                   ; 3e200a01
	v_mac_f32_e32 v0, s2, v5                                    ; 3e000a02
BB132:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v6                                     ; 7c220c80
	s_cbranch_execz BB138                                       ; bf880006
BB133:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x720               ; f4280030 fa000720
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v6                                   ; 3e1c0c00
	v_mac_f32_e32 v16, s1, v6                                   ; 3e200c01
	v_mac_f32_e32 v0, s2, v6                                    ; 3e000c02
BB138:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v7                                     ; 7c220e80
	s_cbranch_execz BB144                                       ; bf880006
BB139:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x730               ; f4280030 fa000730
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v7                                   ; 3e1c0e00
	v_mac_f32_e32 v16, s1, v7                                   ; 3e200e01
	v_mac_f32_e32 v0, s2, v7                                    ; 3e000e02
BB144:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v8                                     ; 7c221080
	s_cbranch_execz BB150                                       ; bf880006
BB145:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x740               ; f4280030 fa000740
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v8                                   ; 3e1c1000
	v_mac_f32_e32 v16, s1, v8                                   ; 3e201001
	v_mac_f32_e32 v0, s2, v8                                    ; 3e001002
BB150:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v9                                     ; 7c221280
	s_cbranch_execz BB156                                       ; bf880006
BB151:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x750               ; f4280030 fa000750
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v9                                   ; 3e1c1200
	v_mac_f32_e32 v16, s1, v9                                   ; 3e201201
	v_mac_f32_e32 v0, s2, v9                                    ; 3e001202
BB156:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v10                                    ; 7c221480
	s_cbranch_execz BB162                                       ; bf880006
BB157:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x760               ; f4280030 fa000760
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v10                                  ; 3e1c1400
	v_mac_f32_e32 v16, s1, v10                                  ; 3e201401
	v_mac_f32_e32 v0, s2, v10                                   ; 3e001402
BB162:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v11                                    ; 7c221680
	s_cbranch_execz BB168                                       ; bf880006
BB163:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x770               ; f4280030 fa000770
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v11                                  ; 3e1c1600
	v_mac_f32_e32 v16, s1, v11                                  ; 3e201601
	v_mac_f32_e32 v0, s2, v11                                   ; 3e001602
BB168:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v12                                    ; 7c221880
	s_cbranch_execz BB174                                       ; bf880006
BB169:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x780               ; f4280030 fa000780
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v12                                  ; 3e1c1800
	v_mac_f32_e32 v16, s1, v12                                  ; 3e201801
	v_mac_f32_e32 v0, s2, v12                                   ; 3e001802
BB174:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v13                                    ; 7c221a80
	s_cbranch_execz BB180                                       ; bf880006
BB175:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x790               ; f4280030 fa000790
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v13                                  ; 3e1c1a00
	v_mac_f32_e32 v16, s1, v13                                  ; 3e201a01
	v_mac_f32_e32 v0, s2, v13                                   ; 3e001a02
BB180:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v30                                    ; 7c223c80
	s_cbranch_execz BB186                                       ; bf880006
BB181:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x7a0               ; f4280030 fa0007a0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v30                                  ; 3e1c3c00
	v_mac_f32_e32 v16, s1, v30                                  ; 3e203c01
	v_mac_f32_e32 v0, s2, v30                                   ; 3e003c02
BB186:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_cmpx_lt_f32_e32 0, v15                                    ; 7c221e80
	s_cbranch_execz BB192                                       ; bf880006
BB187:
	s_buffer_load_dwordx4 s[0:3], s[96:99], 0x7b0               ; f4280030 fa0007b0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mac_f32_e32 v14, s0, v15                                  ; 3e1c1e00
	v_mac_f32_e32 v16, s1, v15                                  ; 3e201e01
	v_mac_f32_e32 v0, s2, v15                                   ; 3e001e02
BB192:
	s_mov_b64 exec, s[100:101]                                  ; befe0464
	v_mul_f32_e32 v14, 0x3fb8aa3b, v14                          ; 101c1cff 3fb8aa3b
	v_mul_f32_e32 v16, 0x3fb8aa3b, v16                          ; 102020ff 3fb8aa3b
	v_exp_f32_e64 v14, -v14                                     ; d5a5000e 2000010e
	v_exp_f32_e64 v16, -v16                                     ; d5a50010 20000110
	v_add_f32_e32 v14, 1.0, v14                                 ; 061c1cf2
	v_add_f32_e32 v16, 1.0, v16                                 ; 062020f2
	v_rcp_f32_e32 v14, v14                                      ; 7e1c550e
	v_rcp_f32_e32 v16, v16                                      ; 7e205510
	v_add_f32_e32 v1, 0x3d6147ae, v14                           ; 06021cff 3d6147ae
	v_mul_f32_e32 v2, 0x3d9e8391, v14                           ; 10041cff 3d9e8391
	v_cmp_ge_f32_e32 vcc, 0x3d25aee6, v14                       ; 7c0c1cff 3d25aee6
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
BB193:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
