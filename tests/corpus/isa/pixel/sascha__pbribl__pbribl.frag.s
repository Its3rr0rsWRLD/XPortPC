# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx8 s[16:23], s[2:3], null                       ; f40c0401 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx4 s[12:15], s[16:19], 0xc0              ; f4280308 fa0000c0
	s_mov_b32 m0, s8                                            ; befc0308
	s_buffer_load_dwordx4 s[8:11], s[20:23], null               ; f428020a fa000000
	s_wqm_b64 exec, exec                                        ; befe0a7e
	v_interp_p1_f32_e32 v7, v0, attr0.y                         ; c81c0100
	v_interp_p1_f32_e32 v6, v0, attr0.x                         ; c8180000
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v4, v0, attr1.y                         ; c8100500
	v_interp_p1_f32_e32 v5, v0, attr0.w                         ; c8140300
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v7, v1, attr0.y                         ; c81d0101
	v_interp_p2_f32_e32 v6, v1, attr0.x                         ; c8190001
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v4, v1, attr1.y                         ; c8110501
	v_interp_p2_f32_e32 v5, v1, attr0.w                         ; c8150301
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_sub_f32_e64 v8, 1.0, s4                                   ; d5040008 000008f2
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v9, 0x3d23d70a, v8                            ; 101210ff 3d23d70a
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mad_f32 v11, s6, s4, v9                                   ; d541000b 04240806
	v_mad_f32 v10, s5, s4, v9                                   ; d541000a 04240805
	v_mad_f32 v9, s7, s4, v9                                    ; d5410009 04240807
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v12, s12, v6                                  ; 06180c0c
	v_add_f32_e32 v13, s13, v7                                  ; 061a0e0d
	v_add_f32_e32 v14, s14, v0                                  ; 061c000e
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mul_f32_e32 v15, v13, v13                                 ; 101e1b0d
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_add_f32_e32 v20, s8, v6                                   ; 06280c08
	v_mac_f32_e32 v15, v14, v14                                 ; 3e1e1d0e
	v_add_f32_e32 v21, s9, v7                                   ; 062a0e09
	v_add_f32_e32 v22, s10, v0                                  ; 062c000a
	v_mac_f32_e32 v15, v12, v12                                 ; 3e1e190c
	v_mul_f32_e32 v23, v21, v21                                 ; 102e2b15
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_rsq_f32_e32 v15, v15                                      ; 7e1e5d0f
	v_mac_f32_e32 v23, v22, v22                                 ; 3e2e2d16
	v_mac_f32_e32 v23, v20, v20                                 ; 3e2e2914
	v_mul_f32_e32 v13, v13, v15                                 ; 101a1f0d
	v_mul_f32_e32 v14, v14, v15                                 ; 101c1f0e
	v_mul_f32_e32 v12, v12, v15                                 ; 10181f0c
	v_rsq_f32_e32 v23, v23                                      ; 7e2e5d17
	v_mul_f32_e32 v16, v14, v4                                  ; 1020090e
	v_mad_f32 v17, v13, -v2, -v16                               ; d5410011 c442050d
	v_mul_f32_e32 v20, v20, v23                                 ; 10282f14
	v_mul_f32_e32 v21, v21, v23                                 ; 102a2f15
	v_mul_f32_e32 v22, v22, v23                                 ; 102c2f16
	v_mad_f32 v17, v12, -v5, v17 mul:2                          ; d5410011 4c460b0c
	v_add_f32_e32 v24, v12, v20                                 ; 0630290c
	v_add_f32_e32 v25, v13, v21                                 ; 06322b0d
	v_mac_f32_e32 v16, v13, v2                                  ; 3e20050d
	v_add_f32_e32 v26, v14, v22                                 ; 06342d0e
	v_mul_f32_e32 v22, v4, v22                                  ; 102c2d04
	v_mad_f32 v18, v5, -v17, -v12                               ; d5410012 c4322305
	v_mad_f32 v19, v2, -v17, -v13                               ; d5410013 c4362302
	v_mad_f32 v17, v4, -v17, -v14                               ; d5410011 c43a2304
	v_mul_f32_e32 v27, v25, v25                                 ; 10363319
	s_mov_b64 s[8:9], exec                                      ; be88047e
	v_mac_f32_e32 v16, v12, v5                                  ; 3e200b0c
	v_mac_f32_e32 v22, v2, v21                                  ; 3e2c2b02
	v_mac_f32_e32 v27, v26, v26                                 ; 3e36351a
	v_add_f32_e64 v28, v16, 0 clamp                             ; d503801c 00010110
	v_mad_f32 v20, v5, v20, v22 clamp                           ; d5418014 045a2905
	v_mac_f32_e32 v27, v24, v24                                 ; 3e363118
	v_rsq_f32_e32 v27, v27                                      ; 7e365d1b
	v_mul_f32_e32 v26, v26, v27                                 ; 1034371a
	v_mul_f32_e32 v24, v24, v27                                 ; 10303718
	v_mul_f32_e32 v25, v25, v27                                 ; 10323719
	v_mul_f32_e32 v26, v4, v26                                  ; 10343504
	v_mac_f32_e32 v26, v2, v25                                  ; 3e343302
	v_mad_f32 v24, v5, v24, v26 clamp                           ; d5418018 046a3105
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v20                                    ; 7c222880
	s_cbranch_execz BB4                                         ; bf880045
BB1:
	v_mul_f32_e32 v24, v24, v24                                 ; 10303118
	v_mul_f32_e64 v1, s0, s0                                    ; d5080001 00000000
	v_add_f32_e64 v21, s0, 1.0                                  ; d5030015 0001e400
	v_sub_f32_e32 v3, 1.0, v24                                  ; 080630f2
	v_mul_f32_e32 v1, v1, v1                                    ; 10020301
	v_mul_f32_e32 v21, v21, v21                                 ; 102a2b15
	v_mac_f32_e32 v3, v1, v24                                   ; 3e063101
	v_sub_f32_e32 v24, 1.0, v28                                 ; 083038f2
	v_mul_f32_e32 v21, 0x3e000000, v21                          ; 102a2aff 3e000000
	v_sub_f32_e32 v26, 1.0, v10                                 ; 083414f2
	v_sub_f32_e32 v27, 1.0, v11                                 ; 083616f2
	v_sub_f32_e32 v29, 1.0, v9                                  ; 083a12f2
	v_mul_f32_e32 v15, 0x40490fdb, v3                           ; 101e06ff 40490fdb
	v_mul_f32_e32 v25, v24, v24                                 ; 10323118
	v_sub_f32_e32 v22, 1.0, v21                                 ; 082c2af2
	v_mul_f32_e32 v15, v15, v3                                  ; 101e070f
	v_mul_f32_e32 v25, v25, v25                                 ; 10323319
	v_mad_f32 v23, v20, v22, v21                                ; d5410017 04562d14
	v_mac_f32_e32 v21, v28, v22                                 ; 3e2a2d1c
	v_rcp_f32_e32 v15, v15                                      ; 7e1e550f
	v_mul_f32_e32 v25, v25, v24                                 ; 10323119
	v_rcp_f32_e32 v23, v23                                      ; 7e2e5517
	v_rcp_f32_e32 v21, v21                                      ; 7e2a5515
	v_mul_f32_e32 v3, 4.0, v20                                  ; 100628f6
	v_mad_f32 v27, v27, v25, v11                                ; d541001b 042e331b
	v_mad_f32 v29, v29, v25, v9                                 ; d541001d 0426331d
	v_mad_f32 v26, v26, v25, v10                                ; d541001a 042a331a
	v_mul_f32_e32 v1, v1, v15                                   ; 10021f01
	v_madak_f32 v3, v3, v28, 0x3a83126f                         ; 42063903 3a83126f
	v_mul_f32_e32 v23, v20, v23                                 ; 102e2f14
	v_mul_f32_e32 v31, v27, v1                                  ; 103e031b
	v_sub_f32_e32 v27, 1.0, v27                                 ; 083636f2
	v_mul_f32_e32 v21, v28, v21                                 ; 102a2b1c
	v_mul_f32_e32 v30, v26, v1                                  ; 103c031a
	v_sub_f32_e32 v26, 1.0, v26                                 ; 083434f2
	v_mul_f32_e32 v1, v29, v1                                   ; 1002031d
	v_rcp_f32_e32 v3, v3                                        ; 7e065503
	v_sub_f32_e32 v29, 1.0, v29                                 ; 083a3af2
	v_mul_f32_e32 v27, 0x3ea2f983, v27                          ; 103636ff 3ea2f983
	v_mul_f32_e32 v23, v23, v21                                 ; 102e2b17
	v_mul_f32_e32 v26, 0x3ea2f983, v26                          ; 103434ff 3ea2f983
	v_mul_f32_e32 v29, 0x3ea2f983, v29                          ; 103a3aff 3ea2f983
	v_mul_f32_e32 v27, v27, v8                                  ; 1036111b
	v_mul_f32_e32 v31, v31, v23                                 ; 103e2f1f
	v_mul_f32_e32 v1, v1, v23                                   ; 10022f01
	v_mul_f32_e32 v30, v30, v23                                 ; 103c2f1e
	v_mul_f32_e32 v26, v26, v8                                  ; 1034111a
	v_mul_f32_e32 v29, v29, v8                                  ; 103a111d
	v_mul_f32_e32 v31, v31, v3                                  ; 103e071f
	v_mul_f32_e32 v1, v1, v3                                    ; 10020701
	v_mul_f32_e32 v30, v30, v3                                  ; 103c071e
	v_mac_f32_e32 v31, s6, v27                                  ; 3e3e3606
	v_mac_f32_e32 v1, s7, v29                                   ; 3e023a07
	v_mac_f32_e32 v30, s5, v26                                  ; 3e3c3405
	v_mul_f32_e32 v31, v31, v20                                 ; 103e291f
	v_mul_f32_e32 v1, v1, v20                                   ; 10022901
	v_mul_f32_e32 v30, v30, v20                                 ; 103c291e
BB4:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	v_lshrrev_b64 v[30:31], 0, 0                                ; d700001e 00010080
BB6:
	s_buffer_load_dwordx4 s[12:15], s[20:23], 0x10              ; f428030a fa000010
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v3, s12, v6                                   ; 06060c0c
	v_add_f32_e32 v15, s13, v7                                  ; 061e0e0d
	v_add_f32_e32 v20, s14, v0                                  ; 0628000e
	v_mul_f32_e32 v21, v15, v15                                 ; 102a1f0f
	v_mac_f32_e32 v21, v20, v20                                 ; 3e2a2914
	v_mac_f32_e32 v21, v3, v3                                   ; 3e2a0703
	v_rsq_f32_e32 v21, v21                                      ; 7e2a5d15
	v_mul_f32_e32 v3, v3, v21                                   ; 10062b03
	v_mul_f32_e32 v15, v15, v21                                 ; 101e2b0f
	v_mul_f32_e32 v20, v20, v21                                 ; 10282b14
	v_add_f32_e32 v22, v12, v3                                  ; 062c070c
	v_add_f32_e32 v23, v13, v15                                 ; 062e1f0d
	v_add_f32_e32 v24, v14, v20                                 ; 0630290e
	v_mul_f32_e32 v20, v4, v20                                  ; 10282904
	v_mul_f32_e32 v25, v23, v23                                 ; 10322f17
	v_mac_f32_e32 v20, v2, v15                                  ; 3e281f02
	v_mac_f32_e32 v25, v24, v24                                 ; 3e323118
	v_mad_f32 v3, v5, v3, v20 clamp                             ; d5418003 04520705
	v_mac_f32_e32 v25, v22, v22                                 ; 3e322d16
	v_rsq_f32_e32 v25, v25                                      ; 7e325d19
	v_mul_f32_e32 v22, v22, v25                                 ; 102c3316
	v_mul_f32_e32 v23, v23, v25                                 ; 102e3317
	v_mul_f32_e32 v24, v24, v25                                 ; 10303318
	v_mul_f32_e32 v24, v4, v24                                  ; 10303104
	v_mac_f32_e32 v24, v2, v23                                  ; 3e302f02
	v_mad_f32 v22, v5, v22, v24 clamp                           ; d5418016 04622d05
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v3                                     ; 7c220680
	s_cbranch_execz BB10                                        ; bf880045
BB7:
	v_mul_f32_e32 v22, v22, v22                                 ; 102c2d16
	v_mul_f32_e64 v15, s0, s0                                   ; d508000f 00000000
	v_sub_f32_e32 v20, 1.0, v22                                 ; 08282cf2
	v_mul_f32_e32 v15, v15, v15                                 ; 101e1f0f
	v_mac_f32_e32 v20, v15, v22                                 ; 3e282d0f
	v_add_f32_e64 v22, s0, 1.0                                  ; d5030016 0001e400
	v_sub_f32_e32 v25, 1.0, v28                                 ; 083238f2
	v_mul_f32_e32 v21, 0x40490fdb, v20                          ; 102a28ff 40490fdb
	v_mul_f32_e32 v22, v22, v22                                 ; 102c2d16
	v_mul_f32_e32 v26, v25, v25                                 ; 10343319
	v_sub_f32_e32 v27, 1.0, v10                                 ; 083614f2
	v_sub_f32_e32 v29, 1.0, v11                                 ; 083a16f2
	v_mul_f32_e32 v21, v21, v20                                 ; 102a2915
	v_sub_f32_e32 v20, 1.0, v9                                  ; 082812f2
	v_mul_f32_e32 v22, 0x3e000000, v22                          ; 102c2cff 3e000000
	v_mul_f32_e32 v26, v26, v26                                 ; 1034351a
	v_rcp_f32_e32 v21, v21                                      ; 7e2a5515
	v_sub_f32_e32 v23, 1.0, v22                                 ; 082e2cf2
	v_mul_f32_e32 v26, v26, v25                                 ; 1034331a
	v_mad_f32 v24, v3, v23, v22                                 ; d5410018 045a2f03
	v_mac_f32_e32 v22, v28, v23                                 ; 3e2c2f1c
	v_mad_f32 v29, v29, v26, v11                                ; d541001d 042e351d
	v_mad_f32 v27, v27, v26, v10                                ; d541001b 042a351b
	v_mad_f32 v20, v20, v26, v9                                 ; d5410014 04263514
	v_mul_f32_e32 v23, 4.0, v3                                  ; 102e06f6
	v_mul_f32_e32 v15, v15, v21                                 ; 101e2b0f
	v_rcp_f32_e32 v24, v24                                      ; 7e305518
	v_rcp_f32_e32 v22, v22                                      ; 7e2c5516
	v_madak_f32 v23, v23, v28, 0x3a83126f                       ; 422e3917 3a83126f
	v_mul_f32_e32 v21, v27, v15                                 ; 102a1f1b
	v_sub_f32_e32 v27, 1.0, v27                                 ; 083636f2
	v_rcp_f32_e32 v23, v23                                      ; 7e2e5517
	v_mul_f32_e32 v24, v3, v24                                  ; 10303103
	v_mul_f32_e32 v27, 0x3ea2f983, v27                          ; 103636ff 3ea2f983
	v_mul_f32_e32 v22, v28, v22                                 ; 102c2d1c
	v_mul_f32_e32 v27, v27, v8                                  ; 1036111b
	v_mul_f32_e32 v24, v24, v22                                 ; 10302d18
	v_mul_f32_e32 v22, v29, v15                                 ; 102c1f1d
	v_mul_f32_e32 v15, v20, v15                                 ; 101e1f14
	v_sub_f32_e32 v29, 1.0, v29                                 ; 083a3af2
	v_sub_f32_e32 v20, 1.0, v20                                 ; 082828f2
	v_mul_f32_e32 v21, v21, v24                                 ; 102a3115
	v_mul_f32_e32 v22, v22, v24                                 ; 102c3116
	v_mul_f32_e32 v15, v15, v24                                 ; 101e310f
	v_mul_f32_e32 v29, 0x3ea2f983, v29                          ; 103a3aff 3ea2f983
	v_mul_f32_e32 v20, 0x3ea2f983, v20                          ; 102828ff 3ea2f983
	v_mul_f32_e32 v21, v21, v23                                 ; 102a2f15
	v_mul_f32_e32 v22, v22, v23                                 ; 102c2f16
	v_mul_f32_e32 v15, v15, v23                                 ; 101e2f0f
	v_mul_f32_e32 v29, v29, v8                                  ; 103a111d
	v_mul_f32_e32 v20, v20, v8                                  ; 10281114
	v_mac_f32_e32 v21, s5, v27                                  ; 3e2a3605
	v_mac_f32_e32 v22, s6, v29                                  ; 3e2c3a06
	v_mac_f32_e32 v15, s7, v20                                  ; 3e1e2807
	v_mul_f32_e32 v21, v21, v3                                  ; 102a0715
	v_mul_f32_e32 v22, v22, v3                                  ; 102c0716
	v_mul_f32_e32 v15, v15, v3                                  ; 101e070f
BB10:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	v_mov_b32_e32 v15, 0                                        ; 7e1e0280
	v_lshrrev_b64 v[21:22], 0, 0                                ; d7000015 00010080
BB12:
	s_buffer_load_dwordx4 s[12:15], s[20:23], 0x20              ; f428030a fa000020
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	v_add_f32_e32 v1, v1, v15                                   ; 06021f01
	v_add_f32_e32 v30, v30, v21                                 ; 063c2b1e
	v_add_f32_e32 v31, v31, v22                                 ; 063e2d1f
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v3, s12, v6                                   ; 06060c0c
	v_add_f32_e32 v15, s13, v7                                  ; 061e0e0d
	v_add_f32_e32 v20, s14, v0                                  ; 0628000e
	v_mul_f32_e32 v21, v15, v15                                 ; 102a1f0f
	v_mac_f32_e32 v21, v20, v20                                 ; 3e2a2914
	v_mac_f32_e32 v21, v3, v3                                   ; 3e2a0703
	v_rsq_f32_e32 v21, v21                                      ; 7e2a5d15
	v_mul_f32_e32 v3, v3, v21                                   ; 10062b03
	v_mul_f32_e32 v15, v15, v21                                 ; 101e2b0f
	v_mul_f32_e32 v20, v20, v21                                 ; 10282b14
	v_add_f32_e32 v22, v12, v3                                  ; 062c070c
	v_add_f32_e32 v23, v13, v15                                 ; 062e1f0d
	v_add_f32_e32 v24, v14, v20                                 ; 0630290e
	v_mul_f32_e32 v20, v4, v20                                  ; 10282904
	v_mul_f32_e32 v25, v23, v23                                 ; 10322f17
	v_mac_f32_e32 v20, v2, v15                                  ; 3e281f02
	v_mac_f32_e32 v25, v24, v24                                 ; 3e323118
	v_mad_f32 v3, v5, v3, v20 clamp                             ; d5418003 04520705
	v_mac_f32_e32 v25, v22, v22                                 ; 3e322d16
	v_rsq_f32_e32 v25, v25                                      ; 7e325d19
	v_mul_f32_e32 v22, v22, v25                                 ; 102c3316
	v_mul_f32_e32 v23, v23, v25                                 ; 102e3317
	v_mul_f32_e32 v24, v24, v25                                 ; 10303318
	v_mul_f32_e32 v24, v4, v24                                  ; 10303104
	v_mac_f32_e32 v24, v2, v23                                  ; 3e302f02
	v_mad_f32 v22, v5, v22, v24 clamp                           ; d5418016 04622d05
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v3                                     ; 7c220680
	s_cbranch_execz BB16                                        ; bf880045
BB13:
	v_mul_f32_e32 v22, v22, v22                                 ; 102c2d16
	v_mul_f32_e64 v15, s0, s0                                   ; d508000f 00000000
	v_sub_f32_e32 v20, 1.0, v22                                 ; 08282cf2
	v_mul_f32_e32 v15, v15, v15                                 ; 101e1f0f
	v_mac_f32_e32 v20, v15, v22                                 ; 3e282d0f
	v_add_f32_e64 v22, s0, 1.0                                  ; d5030016 0001e400
	v_sub_f32_e32 v25, 1.0, v28                                 ; 083238f2
	v_mul_f32_e32 v21, 0x40490fdb, v20                          ; 102a28ff 40490fdb
	v_mul_f32_e32 v22, v22, v22                                 ; 102c2d16
	v_mul_f32_e32 v26, v25, v25                                 ; 10343319
	v_sub_f32_e32 v27, 1.0, v10                                 ; 083614f2
	v_sub_f32_e32 v29, 1.0, v11                                 ; 083a16f2
	v_mul_f32_e32 v21, v21, v20                                 ; 102a2915
	v_sub_f32_e32 v20, 1.0, v9                                  ; 082812f2
	v_mul_f32_e32 v22, 0x3e000000, v22                          ; 102c2cff 3e000000
	v_mul_f32_e32 v26, v26, v26                                 ; 1034351a
	v_rcp_f32_e32 v21, v21                                      ; 7e2a5515
	v_sub_f32_e32 v23, 1.0, v22                                 ; 082e2cf2
	v_mul_f32_e32 v26, v26, v25                                 ; 1034331a
	v_mad_f32 v24, v3, v23, v22                                 ; d5410018 045a2f03
	v_mac_f32_e32 v22, v28, v23                                 ; 3e2c2f1c
	v_mad_f32 v29, v29, v26, v11                                ; d541001d 042e351d
	v_mad_f32 v27, v27, v26, v10                                ; d541001b 042a351b
	v_mad_f32 v20, v20, v26, v9                                 ; d5410014 04263514
	v_mul_f32_e32 v23, 4.0, v3                                  ; 102e06f6
	v_mul_f32_e32 v15, v15, v21                                 ; 101e2b0f
	v_rcp_f32_e32 v24, v24                                      ; 7e305518
	v_rcp_f32_e32 v22, v22                                      ; 7e2c5516
	v_madak_f32 v23, v23, v28, 0x3a83126f                       ; 422e3917 3a83126f
	v_mul_f32_e32 v21, v27, v15                                 ; 102a1f1b
	v_sub_f32_e32 v27, 1.0, v27                                 ; 083636f2
	v_rcp_f32_e32 v23, v23                                      ; 7e2e5517
	v_mul_f32_e32 v24, v3, v24                                  ; 10303103
	v_mul_f32_e32 v27, 0x3ea2f983, v27                          ; 103636ff 3ea2f983
	v_mul_f32_e32 v22, v28, v22                                 ; 102c2d1c
	v_mul_f32_e32 v27, v27, v8                                  ; 1036111b
	v_mul_f32_e32 v24, v24, v22                                 ; 10302d18
	v_mul_f32_e32 v22, v29, v15                                 ; 102c1f1d
	v_mul_f32_e32 v15, v20, v15                                 ; 101e1f14
	v_sub_f32_e32 v29, 1.0, v29                                 ; 083a3af2
	v_sub_f32_e32 v20, 1.0, v20                                 ; 082828f2
	v_mul_f32_e32 v21, v21, v24                                 ; 102a3115
	v_mul_f32_e32 v22, v22, v24                                 ; 102c3116
	v_mul_f32_e32 v15, v15, v24                                 ; 101e310f
	v_mul_f32_e32 v29, 0x3ea2f983, v29                          ; 103a3aff 3ea2f983
	v_mul_f32_e32 v20, 0x3ea2f983, v20                          ; 102828ff 3ea2f983
	v_mul_f32_e32 v21, v21, v23                                 ; 102a2f15
	v_mul_f32_e32 v22, v22, v23                                 ; 102c2f16
	v_mul_f32_e32 v15, v15, v23                                 ; 101e2f0f
	v_mul_f32_e32 v29, v29, v8                                  ; 103a111d
	v_mul_f32_e32 v20, v20, v8                                  ; 10281114
	v_mac_f32_e32 v21, s5, v27                                  ; 3e2a3605
	v_mac_f32_e32 v22, s6, v29                                  ; 3e2c3a06
	v_mac_f32_e32 v15, s7, v20                                  ; 3e1e2807
	v_mul_f32_e32 v21, v21, v3                                  ; 102a0715
	v_mul_f32_e32 v22, v22, v3                                  ; 102c0716
	v_mul_f32_e32 v15, v15, v3                                  ; 101e070f
BB16:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	v_mov_b32_e32 v15, 0                                        ; 7e1e0280
	v_lshrrev_b64 v[21:22], 0, 0                                ; d7000015 00010080
BB18:
	s_buffer_load_dwordx4 s[12:15], s[20:23], 0x30              ; f428030a fa000030
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	v_add_f32_e32 v1, v1, v15                                   ; 06021f01
	v_add_f32_e32 v30, v30, v21                                 ; 063c2b1e
	v_add_f32_e32 v31, v31, v22                                 ; 063e2d1f
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v6, s12, v6                                   ; 060c0c0c
	v_add_f32_e32 v7, s13, v7                                   ; 060e0e0d
	v_add_f32_e32 v0, s14, v0                                   ; 0600000e
	v_mul_f32_e32 v3, v7, v7                                    ; 10060f07
	v_mac_f32_e32 v3, v0, v0                                    ; 3e060100
	v_mac_f32_e32 v3, v6, v6                                    ; 3e060d06
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_mul_f32_e32 v7, v7, v3                                    ; 100e0707
	v_mul_f32_e32 v0, v0, v3                                    ; 10000700
	v_add_f32_e32 v12, v12, v6                                  ; 06180d0c
	v_add_f32_e32 v13, v13, v7                                  ; 061a0f0d
	v_add_f32_e32 v14, v14, v0                                  ; 061c010e
	v_mul_f32_e32 v0, v4, v0                                    ; 10000104
	v_mul_f32_e32 v15, v13, v13                                 ; 101e1b0d
	v_mac_f32_e32 v0, v2, v7                                    ; 3e000f02
	v_mac_f32_e32 v15, v14, v14                                 ; 3e1e1d0e
	v_mad_f32 v6, v5, v6, v0 clamp                              ; d5418006 04020d05
	v_mac_f32_e32 v15, v12, v12                                 ; 3e1e190c
	v_rsq_f32_e32 v15, v15                                      ; 7e1e5d0f
	v_mul_f32_e32 v12, v12, v15                                 ; 10181f0c
	v_mul_f32_e32 v13, v13, v15                                 ; 101a1f0d
	v_mul_f32_e32 v14, v14, v15                                 ; 101c1f0e
	v_mul_f32_e32 v14, v4, v14                                  ; 101c1d04
	v_mac_f32_e32 v14, v2, v13                                  ; 3e1c1b02
	v_mad_f32 v12, v5, v12, v14 clamp                           ; d541800c 043a1905
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v6                                     ; 7c220c80
	s_cbranch_execz BB22                                        ; bf880045
BB19:
	v_mul_f32_e32 v12, v12, v12                                 ; 1018190c
	v_mul_f32_e64 v0, s0, s0                                    ; d5080000 00000000
	v_sub_f32_e32 v3, 1.0, v12                                  ; 080618f2
	v_mul_f32_e32 v0, v0, v0                                    ; 10000100
	v_mac_f32_e32 v3, v0, v12                                   ; 3e061900
	v_add_f32_e64 v12, s0, 1.0                                  ; d503000c 0001e400
	v_sub_f32_e32 v15, 1.0, v28                                 ; 081e38f2
	v_mul_f32_e32 v7, 0x40490fdb, v3                            ; 100e06ff 40490fdb
	v_mul_f32_e32 v12, v12, v12                                 ; 1018190c
	v_mul_f32_e32 v20, v15, v15                                 ; 10281f0f
	v_sub_f32_e32 v21, 1.0, v10                                 ; 082a14f2
	v_sub_f32_e32 v22, 1.0, v11                                 ; 082c16f2
	v_sub_f32_e32 v23, 1.0, v9                                  ; 082e12f2
	v_mul_f32_e32 v7, v7, v3                                    ; 100e0707
	v_mul_f32_e32 v12, 0x3e000000, v12                          ; 101818ff 3e000000
	v_mul_f32_e32 v20, v20, v20                                 ; 10282914
	v_rcp_f32_e32 v7, v7                                        ; 7e0e5507
	v_sub_f32_e32 v13, 1.0, v12                                 ; 081a18f2
	v_mul_f32_e32 v20, v20, v15                                 ; 10281f14
	v_mad_f32 v14, v6, v13, v12                                 ; d541000e 04321b06
	v_mac_f32_e32 v12, v28, v13                                 ; 3e181b1c
	v_mad_f32 v23, v23, v20, v9                                 ; d5410017 04262917
	v_mad_f32 v21, v21, v20, v10                                ; d5410015 042a2915
	v_mad_f32 v22, v22, v20, v11                                ; d5410016 042e2916
	v_mul_f32_e32 v26, 4.0, v6                                  ; 10340cf6
	v_mul_f32_e32 v0, v0, v7                                    ; 10000f00
	v_rcp_f32_e32 v14, v14                                      ; 7e1c550e
	v_rcp_f32_e32 v12, v12                                      ; 7e18550c
	v_madak_f32 v26, v26, v28, 0x3a83126f                       ; 4234391a 3a83126f
	v_mul_f32_e32 v25, v22, v0                                  ; 10320116
	v_mul_f32_e32 v24, v21, v0                                  ; 10300115
	v_sub_f32_e32 v21, 1.0, v21                                 ; 082a2af2
	v_mul_f32_e32 v0, v23, v0                                   ; 10000117
	v_sub_f32_e32 v22, 1.0, v22                                 ; 082c2cf2
	v_sub_f32_e32 v23, 1.0, v23                                 ; 082e2ef2
	v_rcp_f32_e32 v26, v26                                      ; 7e34551a
	v_mul_f32_e32 v14, v6, v14                                  ; 101c1d06
	v_mul_f32_e32 v21, 0x3ea2f983, v21                          ; 102a2aff 3ea2f983
	v_mul_f32_e32 v12, v28, v12                                 ; 1018191c
	v_mul_f32_e32 v22, 0x3ea2f983, v22                          ; 102c2cff 3ea2f983
	v_mul_f32_e32 v23, 0x3ea2f983, v23                          ; 102e2eff 3ea2f983
	v_mul_f32_e32 v21, v21, v8                                  ; 102a1115
	v_mul_f32_e32 v14, v14, v12                                 ; 101c190e
	v_mul_f32_e32 v22, v22, v8                                  ; 102c1116
	v_mul_f32_e32 v23, v23, v8                                  ; 102e1117
	v_mul_f32_e32 v25, v25, v14                                 ; 10321d19
	v_mul_f32_e32 v24, v24, v14                                 ; 10301d18
	v_mul_f32_e32 v0, v0, v14                                   ; 10001d00
	v_mul_f32_e32 v25, v25, v26                                 ; 10323519
	v_mul_f32_e32 v24, v24, v26                                 ; 10303518
	v_mul_f32_e32 v0, v0, v26                                   ; 10003500
	v_mac_f32_e32 v25, s6, v22                                  ; 3e322c06
	v_mac_f32_e32 v24, s5, v21                                  ; 3e302a05
	v_mac_f32_e32 v0, s7, v23                                   ; 3e002e07
	v_mul_f32_e32 v25, v25, v6                                  ; 10320d19
	v_mul_f32_e32 v24, v24, v6                                  ; 10300d18
	v_mul_f32_e32 v0, v0, v6                                    ; 10000d00
BB22:
	s_andn2_b64 exec, s[8:9], exec                              ; 8afe7e08
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_lshrrev_b64 v[24:25], 0, 0                                ; d7000018 00010080
BB24:
	s_mov_b64 exec, s[8:9]                                      ; befe0408
	s_clause 0x5                                                ; bfa10005
	s_load_dwordx8 s[8:15], s[2:3], 0x80                        ; f40c0201 fa000080
	s_load_dwordx4 s[16:19], s[2:3], 0xd0                       ; f4080401 fa0000d0
	s_load_dwordx8 s[24:31], s[2:3], 0xe0                       ; f40c0601 fa0000e0
	s_load_dwordx4 s[32:35], s[2:3], 0x130                      ; f4080801 fa000130
	s_load_dwordx8 s[40:47], s[2:3], 0x20                       ; f40c0a01 fa000020
	s_load_dwordx4 s[36:39], s[2:3], 0x70                       ; f4080901 fa000070
	v_max_f32_e32 v6, 0, v16                                    ; 200c2080
	v_mov_b32_e32 v7, s0                                        ; 7e0e0200
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[12:13], v[6:7], s[8:15], s[16:19] dmask:0x3 dim:SQ_RSRC_IMG_2D ; f0800308 00820c06
	v_mul_f32_e64 v15, s0, 0x41100000                           ; d508000f 0001fe00 41100000
	v_cubema_f32 v3, v18, v19, v17                              ; d5470003 04462712
	v_cubesc_f32 v7, v18, v19, v17                              ; d5450007 04462712
	v_cubetc_f32 v14, v18, v19, v17                             ; d546000e 04462712
	v_cubeid_f32 v18, v18, v19, v17                             ; d5440012 04462712
	v_floor_f32_e32 v19, v15                                    ; 7e26490f
	v_ceil_f32_e32 v20, v15                                     ; 7e28450f
	v_rcp_f32_e64 v3, |v3|                                      ; d5aa0103 00000103
	v_madak_f32 v17, v14, v3, 0x3fc00000                        ; 4222070e 3fc00000
	v_madak_f32 v16, v7, v3, 0x3fc00000                         ; 42200707 3fc00000
	image_sample_l v[21:23], v[16:19], s[24:31], s[32:35] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0900718 01061510
	image_sample_l  v[26:28], [v16, v17, v18, v20], s[24:31], s[32:35] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f090071a 01061a10 00141211
	v_cubema_f32 v29, v5, v2, v4                                ; d547001d 04120505
	v_cubesc_f32 v3, v5, v2, v4                                 ; d5450003 04120505
	v_cubetc_f32 v7, v5, v2, v4                                 ; d5460007 04120505
	v_cubeid_f32 v18, v5, v2, v4                                ; d5440012 04120505
	v_rcp_f32_e64 v29, |v29|                                    ; d5aa011d 0000011d
	v_madak_f32 v16, v3, v29, 0x3fc00000                        ; 42203b03 3fc00000
	v_madak_f32 v17, v7, v29, 0x3fc00000                        ; 42223b07 3fc00000
	image_sample v[2:4], v[16:18], s[40:47], s[36:39] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0800718 012a0210
	s_buffer_load_dwordx2 s[2:3], s[20:23], 0x40                ; f424008a fa000040
	v_add_f32_e32 v30, v30, v24                                 ; 063c311e
	v_add_f32_e32 v31, v31, v25                                 ; 063e331f
	v_add_f32_e32 v1, v1, v0                                    ; 06020101
	v_sub_f32_e32 v15, v15, v19                                 ; 081e270f
	v_sub_f32_e64 v5, 1.0, s0                                   ; d5040005 000000f2
	v_sub_f32_e32 v6, 1.0, v6                                   ; 080c0cf2
	s_mov_b32 s0, 0x3e19999a                                    ; be8003ff 3e19999a
	v_max_f32_e32 v7, v5, v10                                   ; 200e1505
	v_max_f32_e32 v14, v5, v11                                  ; 201c1705
	v_max_f32_e32 v5, v5, v9                                    ; 200a1305
	v_mul_f32_e32 v16, v6, v6                                   ; 10200d06
	v_sub_f32_e32 v7, v7, v10                                   ; 080e1507
	v_sub_f32_e32 v14, v14, v11                                 ; 081c170e
	v_sub_f32_e32 v5, v5, v9                                    ; 080a1305
	v_mul_f32_e32 v16, v16, v16                                 ; 10202110
	v_mul_f32_e32 v16, v16, v6                                  ; 10200d10
	v_mac_f32_e32 v11, v14, v16                                 ; 3e16210e
	v_mac_f32_e32 v9, v5, v16                                   ; 3e122105
	v_mac_f32_e32 v10, v7, v16                                  ; 3e142107
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mad_f32 v17, v10, v12, v13                                ; d5410011 0436190a
	v_sub_f32_e32 v10, 1.0, v10                                 ; 081414f2
	v_mad_f32 v18, v11, v12, v13                                ; d5410012 0436190b
	v_sub_f32_e32 v11, 1.0, v11                                 ; 081616f2
	v_mac_f32_e32 v13, v9, v12                                  ; 3e1a1909
	v_sub_f32_e32 v9, 1.0, v9                                   ; 081212f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_rcp_f32_e32 v19, s3                                       ; 7e265403
	v_mul_f32_e32 v10, v10, v8                                  ; 1014110a
	v_mul_f32_e32 v11, v11, v8                                  ; 1016110b
	v_mul_f32_e32 v9, v9, v8                                    ; 10121109
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_sub_f32_e32 v28, v28, v23                                 ; 08382f1c
	v_sub_f32_e32 v26, v26, v21                                 ; 08342b1a
	v_sub_f32_e32 v27, v27, v22                                 ; 08362d1b
	v_mac_f32_e32 v23, v15, v28                                 ; 3e2e390f
	v_mac_f32_e32 v21, v15, v26                                 ; 3e2a350f
	v_mac_f32_e32 v22, v15, v27                                 ; 3e2c370f
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v3, s6, v3                                    ; 10060606
	v_mul_f32_e32 v2, s5, v2                                    ; 10040405
	v_mul_f32_e32 v4, s7, v4                                    ; 10080807
	v_mac_f32_e32 v31, v11, v3                                  ; 3e3e070b
	v_mac_f32_e32 v30, v10, v2                                  ; 3e3c050a
	v_mac_f32_e32 v1, v9, v4                                    ; 3e020909
	v_mac_f32_e32 v31, v22, v18                                 ; 3e3e2516
	v_mac_f32_e32 v30, v21, v17                                 ; 3e3c2315
	v_mac_f32_e32 v1, v23, v13                                  ; 3e021b17
	v_mul_f32_e32 v31, s2, v31                                  ; 103e3e02
	v_mul_f32_e32 v30, s2, v30                                  ; 103c3c02
	v_mul_f32_e32 v1, s2, v1                                    ; 10020202
	v_mad_f32 v24, s0, v31, 0.5                                 ; d5410018 03c23e00
	v_madak_f32 v21, s0, v31, 0x3d4ccccd                        ; 422a3e00 3d4ccccd
	v_madak_f32 v20, s0, v30, 0x3d4ccccd                        ; 42283c00 3d4ccccd
	v_mad_f32 v23, s0, v30, 0.5                                 ; d5410017 03c23c00
	v_madak_f32 v22, s0, v1, 0x3d4ccccd                         ; 422c0200 3d4ccccd
	v_mad_f32 v25, s0, v1, 0.5                                  ; d5410019 03c20200
	v_madak_f32 v24, v31, v24, 0x3d75c290                       ; 4230311f 3d75c290
	v_madak_f32 v31, v31, v21, 0x3b83126f                       ; 423e2b1f 3b83126f
	v_madak_f32 v23, v30, v23, 0x3d75c290                       ; 422e2f1e 3d75c290
	v_madak_f32 v30, v30, v20, 0x3b83126f                       ; 423c291e 3b83126f
	v_madak_f32 v25, v1, v25, 0x3d75c290                        ; 42323301 3d75c290
	v_madak_f32 v1, v1, v22, 0x3b83126f                         ; 42022d01 3b83126f
	v_rcp_f32_e32 v24, v24                                      ; 7e305518
	v_rcp_f32_e32 v23, v23                                      ; 7e2e5517
	v_rcp_f32_e32 v25, v25                                      ; 7e325519
	v_madak_f32 v31, v31, v24, 0xbd888888                       ; 423e311f bd888888
	v_madak_f32 v30, v30, v23, 0xbd888888                       ; 423c2f1e bd888888
	v_mul_f32_e32 v31, 0x3fb0852e, v31                          ; 103e3eff 3fb0852e
	v_madak_f32 v1, v1, v25, 0xbd888888                         ; 42023301 bd888888
	v_mul_f32_e32 v30, 0x3fb0852e, v30                          ; 103c3cff 3fb0852e
	v_log_f32_e32 v31, v31                                      ; 7e3e4f1f
	v_mul_f32_e32 v1, 0x3fb0852e, v1                            ; 100202ff 3fb0852e
	v_log_f32_e32 v30, v30                                      ; 7e3c4f1e
	v_log_f32_e32 v1, v1                                        ; 7e024f01
	v_mul_legacy_f32_e32 v31, v31, v19                          ; 0e3e271f
	v_mul_legacy_f32_e32 v30, v30, v19                          ; 0e3c271e
	v_exp_f32_e32 v31, v31                                      ; 7e3e4b1f
	v_mul_legacy_f32_e32 v1, v1, v19                            ; 0e022701
	v_exp_f32_e32 v30, v30                                      ; 7e3c4b1e
	v_exp_f32_e32 v1, v1                                        ; 7e024b01
	v_cvt_pkrtz_f16_f32_e32 v30, v30, v31                       ; 5e3c3f1e
	v_cvt_pkrtz_f16_f32_e64 v1, v1, 1.0                         ; d52f0001 0001e501
	exp mrt0 v30, v30, v1, v1 done compr vm                     ; f8001c0f 8080011e
	s_endpgm                                                    ; bf810000
