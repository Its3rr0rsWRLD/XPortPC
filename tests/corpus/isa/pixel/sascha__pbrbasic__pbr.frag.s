# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx8 s[16:23], s[2:3], null                       ; f40c0401 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx4 s[12:15], s[16:19], 0xc0              ; f4280308 fa0000c0
	s_buffer_load_dwordx4 s[16:19], s[20:23], null              ; f428040a fa000000
	s_mov_b32 m0, s8                                            ; befc0308
	v_interp_p1_f32_e32 v6, v0, attr0.x                         ; c8180000
	v_interp_p1_f32_e32 v7, v0, attr0.y                         ; c81c0100
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v4, v0, attr1.y                         ; c8100500
	v_interp_p1_f32_e32 v5, v0, attr0.w                         ; c8140300
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v6, v1, attr0.x                         ; c8190001
	v_interp_p2_f32_e32 v7, v1, attr0.y                         ; c81d0101
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v4, v1, attr1.y                         ; c8110501
	v_interp_p2_f32_e32 v5, v1, attr0.w                         ; c8150301
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v10, s14, v0                                  ; 0614000e
	v_add_f32_e32 v8, s12, v6                                   ; 06100c0c
	v_add_f32_e32 v9, s13, v7                                   ; 06120e0d
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_add_f32_e32 v13, s17, v7                                  ; 061a0e11
	v_add_f32_e32 v12, s16, v6                                  ; 06180c10
	v_add_f32_e32 v14, s18, v0                                  ; 061c0012
	v_mul_f32_e32 v11, v9, v9                                   ; 10161309
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v15, v13, v13                                 ; 101e1b0d
	v_mac_f32_e32 v11, v10, v10                                 ; 3e16150a
	v_mac_f32_e32 v15, v14, v14                                 ; 3e1e1d0e
	v_mac_f32_e32 v11, v8, v8                                   ; 3e161108
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mac_f32_e32 v15, v12, v12                                 ; 3e1e190c
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_rsq_f32_e32 v15, v15                                      ; 7e1e5d0f
	v_mul_f32_e32 v9, v9, v11                                   ; 10121709
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v8, v8, v11                                   ; 10101708
	v_mul_f32_e32 v13, v13, v15                                 ; 101a1f0d
	v_mul_f32_e32 v12, v12, v15                                 ; 10181f0c
	v_mul_f32_e32 v14, v14, v15                                 ; 101c1f0e
	v_mul_f32_e32 v20, v4, v10                                  ; 10281504
	v_add_f32_e32 v17, v9, v13                                  ; 06221b09
	v_add_f32_e32 v16, v8, v12                                  ; 06201908
	v_add_f32_e32 v18, v10, v14                                 ; 06241d0a
	v_mul_f32_e32 v14, v4, v14                                  ; 101c1d04
	v_mac_f32_e32 v20, v2, v9                                   ; 3e281302
	s_mov_b64 s[2:3], exec                                      ; be82047e
	v_mul_f32_e32 v19, v17, v17                                 ; 10262311
	v_mac_f32_e32 v14, v2, v13                                  ; 3e1c1b02
	v_mad_f32 v20, v5, v8, v20 clamp                            ; d5418014 04521105
	v_mac_f32_e32 v19, v18, v18                                 ; 3e262512
	v_mad_f32 v12, v5, v12, v14 clamp                           ; d541800c 043a1905
	v_mac_f32_e32 v19, v16, v16                                 ; 3e262110
	v_rsq_f32_e32 v19, v19                                      ; 7e265d13
	v_mul_f32_e32 v16, v16, v19                                 ; 10202710
	v_mul_f32_e32 v17, v17, v19                                 ; 10222711
	v_mul_f32_e32 v18, v18, v19                                 ; 10242712
	v_mul_f32_e32 v18, v4, v18                                  ; 10242504
	v_mac_f32_e32 v18, v2, v17                                  ; 3e242302
	v_mad_f32 v16, v5, v16, v18 clamp                           ; d5418010 044a2105
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v12                                    ; 7c221880
	s_cbranch_execz BB4                                         ; bf88003e
BB1:
	v_mul_f32_e32 v16, v16, v16                                 ; 10202110
	v_mul_f32_e64 v1, s0, s0                                    ; d5080001 00000000
	v_max_f32_e64 v13, 0x3d4ccccd, s0                           ; d510000d 000000ff 3d4ccccd
	v_sub_f32_e32 v3, 1.0, v16                                  ; 080620f2
	v_mul_f32_e32 v1, v1, v1                                    ; 10020301
	v_add_f32_e32 v13, 1.0, v13                                 ; 061a1af2
	v_mac_f32_e32 v3, v1, v16                                   ; 3e062101
	v_sub_f32_e64 v16, 1.0, s4                                  ; d5040010 000008f2
	v_mul_f32_e32 v13, v13, v13                                 ; 101a1b0d
	v_mul_f32_e32 v11, 0x40490fdb, v3                           ; 101606ff 40490fdb
	v_mul_f32_e32 v16, 0x3d23d70a, v16                          ; 102020ff 3d23d70a
	v_sub_f32_e32 v19, 1.0, v20                                 ; 082628f2
	v_mul_f32_e32 v13, 0x3e000000, v13                          ; 101a1aff 3e000000
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mad_f32 v17, s5, s4, v16                                  ; d5410011 04400805
	v_mad_f32 v18, s6, s4, v16                                  ; d5410012 04400806
	v_mad_f32 v16, s7, s4, v16                                  ; d5410010 04400807
	v_mul_f32_e32 v21, v19, v19                                 ; 102a2713
	v_sub_f32_e32 v14, 1.0, v13                                 ; 081c1af2
	v_rcp_f32_e32 v11, v11                                      ; 7e16550b
	v_sub_f32_e32 v22, 1.0, v17                                 ; 082c22f2
	v_sub_f32_e32 v23, 1.0, v18                                 ; 082e24f2
	v_sub_f32_e32 v3, 1.0, v16                                  ; 080620f2
	v_mul_f32_e32 v21, v21, v21                                 ; 102a2b15
	v_mad_f32 v15, v12, v14, v13                                ; d541000f 04361d0c
	v_mac_f32_e32 v13, v20, v14                                 ; 3e1a1d14
	v_mul_f32_e32 v21, v21, v19                                 ; 102a2715
	v_mul_f32_e32 v1, v1, v11                                   ; 10021701
	v_mul_f32_e32 v11, 4.0, v12                                 ; 101618f6
	v_rcp_f32_e32 v15, v15                                      ; 7e1e550f
	v_rcp_f32_e32 v13, v13                                      ; 7e1a550d
	v_mac_f32_e32 v17, v22, v21                                 ; 3e222b16
	v_mac_f32_e32 v16, v3, v21                                  ; 3e202b03
	v_mac_f32_e32 v18, v23, v21                                 ; 3e242b17
	v_mul_f32_e32 v11, v11, v20                                 ; 1016290b
	v_mul_f32_e32 v15, v12, v15                                 ; 101e1f0c
	v_mul_f32_e32 v17, v17, v1                                  ; 10220311
	v_mul_f32_e32 v16, v16, v1                                  ; 10200310
	v_mul_f32_e32 v18, v18, v1                                  ; 10240312
	v_rcp_f32_e32 v11, v11                                      ; 7e16550b
	v_mul_f32_e32 v13, v20, v13                                 ; 101a1b14
	v_mul_f32_e32 v15, v15, v13                                 ; 101e1b0f
	v_mul_f32_e32 v16, v16, v15                                 ; 10201f10
	v_mul_f32_e32 v17, v17, v15                                 ; 10221f11
	v_mul_f32_e32 v18, v18, v15                                 ; 10241f12
	v_mul_f32_e32 v16, v16, v11                                 ; 10201710
	v_mul_f32_e32 v17, v17, v11                                 ; 10221711
	v_mul_f32_e32 v18, v18, v11                                 ; 10241712
	v_mul_f32_e32 v16, v16, v12                                 ; 10201910
	v_mul_f32_e32 v17, v17, v12                                 ; 10221911
	v_mul_f32_e32 v18, v18, v12                                 ; 10241912
BB4:
	s_andn2_b64 exec, s[2:3], exec                              ; 8afe7e02
	v_lshrrev_b64 v[16:17], 0, 0                                ; d7000010 00010080
	v_mov_b32_e32 v18, 0                                        ; 7e240280
BB6:
	s_buffer_load_dwordx4 s[8:11], s[20:23], 0x10               ; f428020a fa000010
	s_mov_b64 exec, s[2:3]                                      ; befe0402
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v1, s8, v6                                    ; 06020c08
	v_add_f32_e32 v3, s9, v7                                    ; 06060e09
	v_add_f32_e32 v11, s10, v0                                  ; 0616000a
	v_mul_f32_e32 v12, v3, v3                                   ; 10180703
	v_mac_f32_e32 v12, v11, v11                                 ; 3e18170b
	v_mac_f32_e32 v12, v1, v1                                   ; 3e180301
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_mul_f32_e32 v1, v1, v12                                   ; 10021901
	v_mul_f32_e32 v3, v3, v12                                   ; 10061903
	v_mul_f32_e32 v11, v11, v12                                 ; 1016190b
	v_add_f32_e32 v13, v8, v1                                   ; 061a0308
	v_add_f32_e32 v14, v9, v3                                   ; 061c0709
	v_add_f32_e32 v15, v10, v11                                 ; 061e170a
	v_mul_f32_e32 v11, v4, v11                                  ; 10161704
	v_mul_f32_e32 v19, v14, v14                                 ; 10261d0e
	v_mac_f32_e32 v11, v2, v3                                   ; 3e160702
	v_mac_f32_e32 v19, v15, v15                                 ; 3e261f0f
	v_mad_f32 v1, v5, v1, v11 clamp                             ; d5418001 042e0305
	v_mac_f32_e32 v19, v13, v13                                 ; 3e261b0d
	v_rsq_f32_e32 v19, v19                                      ; 7e265d13
	v_mul_f32_e32 v13, v13, v19                                 ; 101a270d
	v_mul_f32_e32 v14, v14, v19                                 ; 101c270e
	v_mul_f32_e32 v15, v15, v19                                 ; 101e270f
	v_mul_f32_e32 v15, v4, v15                                  ; 101e1f04
	v_mac_f32_e32 v15, v2, v14                                  ; 3e1e1d02
	v_mad_f32 v13, v5, v13, v15 clamp                           ; d541800d 043e1b05
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v1                                     ; 7c220280
	s_cbranch_execz BB10                                        ; bf88003e
BB7:
	v_mul_f32_e32 v13, v13, v13                                 ; 101a1b0d
	v_mul_f32_e64 v3, s0, s0                                    ; d5080003 00000000
	v_sub_f32_e32 v11, 1.0, v13                                 ; 08161af2
	v_mul_f32_e32 v3, v3, v3                                    ; 10060703
	v_mac_f32_e32 v11, v3, v13                                  ; 3e161b03
	v_max_f32_e64 v13, 0x3d4ccccd, s0                           ; d510000d 000000ff 3d4ccccd
	v_sub_f32_e64 v19, 1.0, s4                                  ; d5040013 000008f2
	v_mul_f32_e32 v12, 0x40490fdb, v11                          ; 101816ff 40490fdb
	v_add_f32_e32 v13, 1.0, v13                                 ; 061a1af2
	v_mul_f32_e32 v19, 0x3d23d70a, v19                          ; 102626ff 3d23d70a
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_sub_f32_e32 v23, 1.0, v20                                 ; 082e28f2
	v_mul_f32_e32 v13, v13, v13                                 ; 101a1b0d
	v_mad_f32 v21, s5, s4, v19                                  ; d5410015 044c0805
	v_mad_f32 v22, s6, s4, v19                                  ; d5410016 044c0806
	v_mad_f32 v19, s7, s4, v19                                  ; d5410013 044c0807
	v_rcp_f32_e32 v12, v12                                      ; 7e18550c
	v_mul_f32_e32 v11, v23, v23                                 ; 10162f17
	v_mul_f32_e32 v13, 0x3e000000, v13                          ; 101a1aff 3e000000
	v_mul_f32_e32 v11, v11, v11                                 ; 1016170b
	v_sub_f32_e32 v14, 1.0, v13                                 ; 081c1af2
	v_mul_f32_e32 v3, v3, v12                                   ; 10061903
	v_sub_f32_e32 v12, 1.0, v21                                 ; 08182af2
	v_mul_f32_e32 v11, v11, v23                                 ; 10162f0b
	v_mad_f32 v15, v1, v14, v13                                 ; d541000f 04361d01
	v_mac_f32_e32 v13, v20, v14                                 ; 3e1a1d14
	v_sub_f32_e32 v14, 1.0, v19                                 ; 081c26f2
	v_mac_f32_e32 v21, v12, v11                                 ; 3e2a170c
	v_rcp_f32_e32 v15, v15                                      ; 7e1e550f
	v_rcp_f32_e32 v13, v13                                      ; 7e1a550d
	v_mac_f32_e32 v19, v14, v11                                 ; 3e26170e
	v_mul_f32_e32 v21, v21, v3                                  ; 102a0715
	v_mul_f32_e32 v15, v1, v15                                  ; 101e1f01
	v_mul_f32_e32 v19, v19, v3                                  ; 10260713
	v_mul_f32_e32 v13, v20, v13                                 ; 101a1b14
	v_mul_f32_e32 v15, v15, v13                                 ; 101e1b0f
	v_sub_f32_e32 v13, 1.0, v22                                 ; 081a2cf2
	v_mul_f32_e32 v19, v19, v15                                 ; 10261f13
	v_mul_f32_e32 v21, v21, v15                                 ; 102a1f15
	v_mac_f32_e32 v22, v13, v11                                 ; 3e2c170d
	v_mul_f32_e32 v22, v22, v3                                  ; 102c0716
	v_mul_f32_e32 v22, v22, v15                                 ; 102c1f16
	v_mul_f32_e32 v15, 4.0, v1                                  ; 101e02f6
	v_mul_f32_e32 v15, v15, v20                                 ; 101e290f
	v_rcp_f32_e32 v15, v15                                      ; 7e1e550f
	v_mul_f32_e32 v21, v21, v15                                 ; 102a1f15
	v_mul_f32_e32 v22, v22, v15                                 ; 102c1f16
	v_mul_f32_e32 v19, v19, v15                                 ; 10261f13
	v_mul_f32_e32 v21, v21, v1                                  ; 102a0315
	v_mul_f32_e32 v22, v22, v1                                  ; 102c0316
	v_mul_f32_e32 v19, v19, v1                                  ; 10260313
BB10:
	s_andn2_b64 exec, s[2:3], exec                              ; 8afe7e02
	v_mov_b32_e32 v19, 0                                        ; 7e260280
	v_lshrrev_b64 v[21:22], 0, 0                                ; d7000015 00010080
BB12:
	s_buffer_load_dwordx4 s[8:11], s[20:23], 0x20               ; f428020a fa000020
	s_mov_b64 exec, s[2:3]                                      ; befe0402
	v_add_f32_e32 v16, v16, v19                                 ; 06202710
	v_add_f32_e32 v17, v17, v21                                 ; 06222b11
	v_add_f32_e32 v18, v18, v22                                 ; 06242d12
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v1, s8, v6                                    ; 06020c08
	v_add_f32_e32 v3, s9, v7                                    ; 06060e09
	v_add_f32_e32 v11, s10, v0                                  ; 0616000a
	v_mul_f32_e32 v12, v3, v3                                   ; 10180703
	v_mac_f32_e32 v12, v11, v11                                 ; 3e18170b
	v_mac_f32_e32 v12, v1, v1                                   ; 3e180301
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_mul_f32_e32 v1, v1, v12                                   ; 10021901
	v_mul_f32_e32 v3, v3, v12                                   ; 10061903
	v_mul_f32_e32 v11, v11, v12                                 ; 1016190b
	v_add_f32_e32 v13, v8, v1                                   ; 061a0308
	v_add_f32_e32 v14, v9, v3                                   ; 061c0709
	v_add_f32_e32 v15, v10, v11                                 ; 061e170a
	v_mul_f32_e32 v11, v4, v11                                  ; 10161704
	v_mul_f32_e32 v19, v14, v14                                 ; 10261d0e
	v_mac_f32_e32 v11, v2, v3                                   ; 3e160702
	v_mac_f32_e32 v19, v15, v15                                 ; 3e261f0f
	v_mad_f32 v1, v5, v1, v11 clamp                             ; d5418001 042e0305
	v_mac_f32_e32 v19, v13, v13                                 ; 3e261b0d
	v_rsq_f32_e32 v19, v19                                      ; 7e265d13
	v_mul_f32_e32 v13, v13, v19                                 ; 101a270d
	v_mul_f32_e32 v14, v14, v19                                 ; 101c270e
	v_mul_f32_e32 v15, v15, v19                                 ; 101e270f
	v_mul_f32_e32 v15, v4, v15                                  ; 101e1f04
	v_mac_f32_e32 v15, v2, v14                                  ; 3e1e1d02
	v_mad_f32 v13, v5, v13, v15 clamp                           ; d541800d 043e1b05
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v1                                     ; 7c220280
	s_cbranch_execz BB16                                        ; bf88003e
BB13:
	v_mul_f32_e32 v13, v13, v13                                 ; 101a1b0d
	v_mul_f32_e64 v3, s0, s0                                    ; d5080003 00000000
	v_sub_f32_e32 v11, 1.0, v13                                 ; 08161af2
	v_mul_f32_e32 v3, v3, v3                                    ; 10060703
	v_mac_f32_e32 v11, v3, v13                                  ; 3e161b03
	v_max_f32_e64 v13, 0x3d4ccccd, s0                           ; d510000d 000000ff 3d4ccccd
	v_sub_f32_e64 v19, 1.0, s4                                  ; d5040013 000008f2
	v_mul_f32_e32 v12, 0x40490fdb, v11                          ; 101816ff 40490fdb
	v_add_f32_e32 v13, 1.0, v13                                 ; 061a1af2
	v_mul_f32_e32 v19, 0x3d23d70a, v19                          ; 102626ff 3d23d70a
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_sub_f32_e32 v23, 1.0, v20                                 ; 082e28f2
	v_mul_f32_e32 v13, v13, v13                                 ; 101a1b0d
	v_mad_f32 v21, s5, s4, v19                                  ; d5410015 044c0805
	v_mad_f32 v22, s6, s4, v19                                  ; d5410016 044c0806
	v_mad_f32 v19, s7, s4, v19                                  ; d5410013 044c0807
	v_rcp_f32_e32 v12, v12                                      ; 7e18550c
	v_mul_f32_e32 v11, v23, v23                                 ; 10162f17
	v_mul_f32_e32 v13, 0x3e000000, v13                          ; 101a1aff 3e000000
	v_mul_f32_e32 v11, v11, v11                                 ; 1016170b
	v_sub_f32_e32 v14, 1.0, v13                                 ; 081c1af2
	v_mul_f32_e32 v3, v3, v12                                   ; 10061903
	v_sub_f32_e32 v12, 1.0, v21                                 ; 08182af2
	v_mul_f32_e32 v11, v11, v23                                 ; 10162f0b
	v_mad_f32 v15, v1, v14, v13                                 ; d541000f 04361d01
	v_mac_f32_e32 v13, v20, v14                                 ; 3e1a1d14
	v_sub_f32_e32 v14, 1.0, v19                                 ; 081c26f2
	v_mac_f32_e32 v21, v12, v11                                 ; 3e2a170c
	v_rcp_f32_e32 v15, v15                                      ; 7e1e550f
	v_rcp_f32_e32 v13, v13                                      ; 7e1a550d
	v_mac_f32_e32 v19, v14, v11                                 ; 3e26170e
	v_mul_f32_e32 v21, v21, v3                                  ; 102a0715
	v_mul_f32_e32 v15, v1, v15                                  ; 101e1f01
	v_mul_f32_e32 v19, v19, v3                                  ; 10260713
	v_mul_f32_e32 v13, v20, v13                                 ; 101a1b14
	v_mul_f32_e32 v15, v15, v13                                 ; 101e1b0f
	v_sub_f32_e32 v13, 1.0, v22                                 ; 081a2cf2
	v_mul_f32_e32 v19, v19, v15                                 ; 10261f13
	v_mul_f32_e32 v21, v21, v15                                 ; 102a1f15
	v_mac_f32_e32 v22, v13, v11                                 ; 3e2c170d
	v_mul_f32_e32 v22, v22, v3                                  ; 102c0716
	v_mul_f32_e32 v22, v22, v15                                 ; 102c1f16
	v_mul_f32_e32 v15, 4.0, v1                                  ; 101e02f6
	v_mul_f32_e32 v15, v15, v20                                 ; 101e290f
	v_rcp_f32_e32 v15, v15                                      ; 7e1e550f
	v_mul_f32_e32 v21, v21, v15                                 ; 102a1f15
	v_mul_f32_e32 v22, v22, v15                                 ; 102c1f16
	v_mul_f32_e32 v19, v19, v15                                 ; 10261f13
	v_mul_f32_e32 v21, v21, v1                                  ; 102a0315
	v_mul_f32_e32 v22, v22, v1                                  ; 102c0316
	v_mul_f32_e32 v19, v19, v1                                  ; 10260313
BB16:
	s_andn2_b64 exec, s[2:3], exec                              ; 8afe7e02
	v_mov_b32_e32 v19, 0                                        ; 7e260280
	v_lshrrev_b64 v[21:22], 0, 0                                ; d7000015 00010080
BB18:
	s_buffer_load_dwordx4 s[8:11], s[20:23], 0x30               ; f428020a fa000030
	s_mov_b64 exec, s[2:3]                                      ; befe0402
	v_add_f32_e32 v16, v16, v19                                 ; 06202710
	v_add_f32_e32 v17, v17, v21                                 ; 06222b11
	v_add_f32_e32 v18, v18, v22                                 ; 06242d12
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v6, s8, v6                                    ; 060c0c08
	v_add_f32_e32 v7, s9, v7                                    ; 060e0e09
	v_add_f32_e32 v0, s10, v0                                   ; 0600000a
	v_mul_f32_e32 v1, v7, v7                                    ; 10020f07
	v_mac_f32_e32 v1, v0, v0                                    ; 3e020100
	v_mac_f32_e32 v1, v6, v6                                    ; 3e020d06
	v_rsq_f32_e32 v1, v1                                        ; 7e025d01
	v_mul_f32_e32 v6, v6, v1                                    ; 100c0306
	v_mul_f32_e32 v7, v7, v1                                    ; 100e0307
	v_mul_f32_e32 v0, v0, v1                                    ; 10000300
	v_add_f32_e32 v8, v8, v6                                    ; 06100d08
	v_add_f32_e32 v9, v9, v7                                    ; 06120f09
	v_add_f32_e32 v10, v10, v0                                  ; 0614010a
	v_mul_f32_e32 v0, v4, v0                                    ; 10000104
	v_mul_f32_e32 v3, v9, v9                                    ; 10061309
	v_mac_f32_e32 v0, v2, v7                                    ; 3e000f02
	v_mac_f32_e32 v3, v10, v10                                  ; 3e06150a
	v_mad_f32 v6, v5, v6, v0 clamp                              ; d5418006 04020d05
	v_mac_f32_e32 v3, v8, v8                                    ; 3e061108
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v8, v8, v3                                    ; 10100708
	v_mul_f32_e32 v9, v9, v3                                    ; 10120709
	v_mul_f32_e32 v10, v10, v3                                  ; 1014070a
	v_mul_f32_e32 v4, v4, v10                                   ; 10081504
	v_mac_f32_e32 v4, v2, v9                                    ; 3e081302
	v_mad_f32 v5, v5, v8, v4 clamp                              ; d5418005 04121105
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v6                                     ; 7c220c80
	s_cbranch_execz BB22                                        ; bf88003e
BB19:
	v_mul_f32_e32 v5, v5, v5                                    ; 100a0b05
	v_mul_f32_e64 v0, s0, s0                                    ; d5080000 00000000
	v_max_f32_e64 v3, 0x3d4ccccd, s0                            ; d5100003 000000ff 3d4ccccd
	v_sub_f32_e32 v1, 1.0, v5                                   ; 08020af2
	v_mul_f32_e32 v0, v0, v0                                    ; 10000100
	v_add_f32_e32 v3, 1.0, v3                                   ; 060606f2
	v_sub_f32_e64 v7, 1.0, s4                                   ; d5040007 000008f2
	v_mac_f32_e32 v1, v0, v5                                    ; 3e020b00
	v_mul_f32_e32 v3, v3, v3                                    ; 10060703
	v_mul_f32_e32 v7, 0x3d23d70a, v7                            ; 100e0eff 3d23d70a
	v_mul_f32_e32 v2, 0x40490fdb, v1                            ; 100402ff 40490fdb
	v_sub_f32_e32 v10, 1.0, v20                                 ; 081428f2
	v_mul_f32_e32 v3, 0x3e000000, v3                            ; 100606ff 3e000000
	v_mad_f32 v8, s5, s4, v7                                    ; d5410008 041c0805
	v_mad_f32 v9, s6, s4, v7                                    ; d5410009 041c0806
	v_mad_f32 v7, s7, s4, v7                                    ; d5410007 041c0807
	v_mul_f32_e32 v2, v2, v1                                    ; 10040302
	v_mul_f32_e32 v11, v10, v10                                 ; 1016150a
	v_sub_f32_e32 v4, 1.0, v3                                   ; 080806f2
	v_sub_f32_e32 v12, 1.0, v8                                  ; 081810f2
	v_sub_f32_e32 v13, 1.0, v9                                  ; 081a12f2
	v_sub_f32_e32 v14, 1.0, v7                                  ; 081c0ef2
	v_rcp_f32_e32 v2, v2                                        ; 7e045502
	v_mul_f32_e32 v11, v11, v11                                 ; 1016170b
	v_mad_f32 v5, v6, v4, v3                                    ; d5410005 040e0906
	v_mac_f32_e32 v3, v20, v4                                   ; 3e060914
	v_mul_f32_e32 v11, v11, v10                                 ; 1016150b
	v_mul_f32_e32 v15, 4.0, v6                                  ; 101e0cf6
	v_rcp_f32_e32 v5, v5                                        ; 7e0a5505
	v_rcp_f32_e32 v3, v3                                        ; 7e065503
	v_mul_f32_e32 v0, v0, v2                                    ; 10000500
	v_mac_f32_e32 v8, v12, v11                                  ; 3e10170c
	v_mac_f32_e32 v7, v14, v11                                  ; 3e0e170e
	v_mac_f32_e32 v9, v13, v11                                  ; 3e12170d
	v_mul_f32_e32 v15, v15, v20                                 ; 101e290f
	v_mul_f32_e32 v5, v6, v5                                    ; 100a0b06
	v_mul_f32_e32 v8, v8, v0                                    ; 10100108
	v_mul_f32_e32 v7, v7, v0                                    ; 100e0107
	v_mul_f32_e32 v9, v9, v0                                    ; 10120109
	v_mul_f32_e32 v3, v20, v3                                   ; 10060714
	v_rcp_f32_e32 v15, v15                                      ; 7e1e550f
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v7, v7, v5                                    ; 100e0b07
	v_mul_f32_e32 v8, v8, v5                                    ; 10100b08
	v_mul_f32_e32 v9, v9, v5                                    ; 10120b09
	v_mul_f32_e32 v7, v7, v15                                   ; 100e1f07
	v_mul_f32_e32 v8, v8, v15                                   ; 10101f08
	v_mul_f32_e32 v9, v9, v15                                   ; 10121f09
	v_mul_f32_e32 v7, v7, v6                                    ; 100e0d07
	v_mul_f32_e32 v8, v8, v6                                    ; 10100d08
	v_mul_f32_e32 v9, v9, v6                                    ; 10120d09
BB22:
	s_andn2_b64 exec, s[2:3], exec                              ; 8afe7e02
	v_lshrrev_b64 v[7:8], 0, 0                                  ; d7000007 00010080
	v_mov_b32_e32 v9, 0                                         ; 7e120280
BB24:
	s_mov_b64 exec, s[2:3]                                      ; befe0402
	v_add_f32_e32 v17, v17, v8                                  ; 06221111
	v_add_f32_e32 v18, v18, v9                                  ; 06241312
	v_add_f32_e32 v16, v16, v7                                  ; 06200f10
	v_madmk_f32 v17, s5, 0x3ca3d70a, v17                        ; 40222205 3ca3d70a
	v_madmk_f32 v18, s6, 0x3ca3d70a, v18                        ; 40242406 3ca3d70a
	v_madmk_f32 v16, s7, 0x3ca3d70a, v16                        ; 40202007 3ca3d70a
	v_log_f32_e32 v17, v17                                      ; 7e224f11
	v_log_f32_e32 v18, v18                                      ; 7e244f12
	v_log_f32_e32 v16, v16                                      ; 7e204f10
	v_mul_f32_e32 v17, 0x3ee8b439, v17                          ; 102222ff 3ee8b439
	v_mul_f32_e32 v18, 0x3ee8b439, v18                          ; 102424ff 3ee8b439
	v_exp_f32_e32 v17, v17                                      ; 7e224b11
	v_mul_f32_e32 v16, 0x3ee8b439, v16                          ; 102020ff 3ee8b439
	v_exp_f32_e32 v18, v18                                      ; 7e244b12
	v_exp_f32_e32 v16, v16                                      ; 7e204b10
	v_cvt_pkrtz_f16_f32_e32 v17, v17, v18                       ; 5e222511
	v_cvt_pkrtz_f16_f32_e64 v16, v16, 1.0                       ; d52f0010 0001e510
	exp mrt0 v17, v17, v16, v16 done compr vm                   ; f8001c0f 80801011
	s_endpgm                                                    ; bf810000
