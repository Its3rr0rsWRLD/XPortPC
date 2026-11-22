# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx4 s[8:11], s[2:3], null                        ; f4080201 fa000000
	s_load_dwordx4 s[0:3], s[0:1], null                         ; f4080000 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx4 s[8:11], s[8:11], 0xc0                ; f4280204 fa0000c0
	s_mov_b32 m0, s4                                            ; befc0304
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
	v_mul_f32_e32 v12, v7, v7                                   ; 10180f07
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v10, s10, v0                                  ; 0614000a
	v_add_f32_e32 v0, 0x41200000, v0                            ; 060000ff 41200000
	v_sub_f32_e32 v8, s8, v6                                    ; 08100c08
	v_sub_f32_e32 v9, s9, v7                                    ; 08120e09
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mac_f32_e32 v12, v0, v0                                   ; 3e180100
	v_mul_f32_e32 v11, v9, v9                                   ; 10161309
	v_mac_f32_e32 v12, v6, v6                                   ; 3e180d06
	v_mac_f32_e32 v11, v10, v10                                 ; 3e16150a
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_mac_f32_e32 v11, v8, v8                                   ; 3e161108
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_mul_f32_e32 v0, v0, v12                                   ; 10001900
	v_mul_f32_e32 v6, v6, v12                                   ; 100c1906
	v_mul_f32_e32 v7, v7, v12                                   ; 100e1907
	v_mul_f32_e32 v9, v9, v11                                   ; 10121709
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v8, v8, v11                                   ; 10101708
	v_sub_f32_e32 v14, v9, v7                                   ; 081c0f09
	v_add_f32_e32 v15, v10, v0                                  ; 061e010a
	v_mul_f32_e32 v0, v4, v0                                    ; 10000104
	v_mul_f32_e32 v10, v4, v10                                  ; 10141504
	v_sub_f32_e32 v13, v8, v6                                   ; 081a0d08
	s_mov_b64 s[4:5], exec                                      ; be84047e
	v_mul_f32_e32 v16, v14, v14                                 ; 10201d0e
	v_mad_f32 v7, v7, -v2, v0                                   ; d5410007 44020507
	v_mac_f32_e32 v10, v2, v9                                   ; 3e141302
	v_mac_f32_e32 v16, v15, v15                                 ; 3e201f0f
	v_mad_f32 v6, v6, -v5, v7 clamp                             ; d5418006 441e0b06
	v_mad_f32 v8, v5, v8, v10 clamp                             ; d5418008 042a1105
	v_mac_f32_e32 v16, v13, v13                                 ; 3e201b0d
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_mul_f32_e32 v14, v14, v16                                 ; 101c210e
	v_mul_f32_e32 v15, v15, v16                                 ; 101e210f
	v_mul_f32_e32 v13, v13, v16                                 ; 101a210d
	v_mul_f32_e32 v4, v4, v15                                   ; 10081f04
	v_mac_f32_e32 v4, v2, v14                                   ; 3e081d02
	v_mad_f32 v5, v5, v13, v4 clamp                             ; d5418005 04121b05
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v6                                     ; 7c220c80
	s_cbranch_execz BB4                                         ; bf880043
BB1:
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx2 s[6:7], s[0:3], null                  ; f4240180 fa000000
	s_buffer_load_dwordx4 s[8:11], s[0:3], 0x8                  ; f4280200 fa000008
	v_mul_f32_e32 v5, v5, v5                                    ; 100a0b05
	v_sub_f32_e32 v0, 1.0, v5                                   ; 08000af2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_max_f32_e64 v1, 0x3d4ccccd, s6                            ; d5100001 00000cff 3d4ccccd
	v_mul_f32_e32 v2, v1, v1                                    ; 10040301
	v_add_f32_e32 v1, 1.0, v1                                   ; 060202f2
	v_mul_f32_e32 v2, v2, v2                                    ; 10040502
	v_sub_f32_e64 v7, 1.0, s7                                   ; d5040007 00000ef2
	v_mul_f32_e32 v1, v1, v1                                    ; 10020301
	v_sub_f32_e32 v9, 1.0, v8                                   ; 081210f2
	v_mac_f32_e32 v0, v2, v5                                    ; 3e000b02
	v_mul_f32_e32 v7, 0x3d23d70a, v7                            ; 100e0eff 3d23d70a
	v_mul_f32_e32 v1, 0x3e000000, v1                            ; 100202ff 3e000000
	v_mul_f32_e32 v10, v9, v9                                   ; 10141309
	v_mul_f32_e32 v11, 4.0, v6                                  ; 10160cf6
	v_mul_f32_e32 v3, 0x40490fdb, v0                            ; 100600ff 40490fdb
	v_mad_f32 v12, s8, s7, v7                                   ; d541000c 041c0e08
	v_mad_f32 v13, s9, s7, v7                                   ; d541000d 041c0e09
	v_sub_f32_e32 v4, 1.0, v1                                   ; 080802f2
	v_mul_f32_e32 v10, v10, v10                                 ; 1014150a
	v_mad_f32 v7, s10, s7, v7                                   ; d5410007 041c0e0a
	v_mul_f32_e32 v11, v11, v8                                  ; 1016110b
	v_mul_f32_e32 v3, v3, v0                                    ; 10060103
	v_sub_f32_e32 v14, 1.0, v12                                 ; 081c18f2
	v_sub_f32_e32 v15, 1.0, v13                                 ; 081e1af2
	v_mad_f32 v5, v6, v4, v1                                    ; d5410005 04060906
	v_mac_f32_e32 v1, v8, v4                                    ; 3e020908
	v_mul_f32_e32 v10, v10, v9                                  ; 1014130a
	v_sub_f32_e32 v16, 1.0, v7                                  ; 08200ef2
	v_rcp_f32_e32 v11, v11                                      ; 7e16550b
	v_rcp_f32_e32 v3, v3                                        ; 7e065503
	v_rcp_f32_e32 v5, v5                                        ; 7e0a5505
	v_rcp_f32_e32 v1, v1                                        ; 7e025501
	v_mac_f32_e32 v13, v15, v10                                 ; 3e1a150f
	v_mac_f32_e32 v12, v14, v10                                 ; 3e18150e
	v_mac_f32_e32 v7, v16, v10                                  ; 3e0e1510
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v5, v6, v5                                    ; 100a0b06
	v_mul_f32_e32 v13, v13, v2                                  ; 101a050d
	v_mul_f32_e32 v7, v7, v2                                    ; 100e0507
	v_mul_f32_e32 v12, v12, v2                                  ; 1018050c
	v_mul_f32_e32 v1, v8, v1                                    ; 10020308
	v_mul_f32_e32 v5, v5, v1                                    ; 100a0305
	v_mul_f32_e32 v12, v12, v5                                  ; 10180b0c
	v_mul_f32_e32 v13, v13, v5                                  ; 101a0b0d
	v_mul_f32_e32 v7, v7, v5                                    ; 100e0b07
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_mul_f32_e32 v13, v13, v11                                 ; 101a170d
	v_mul_f32_e32 v7, v7, v11                                   ; 100e1707
	v_mul_f32_e32 v12, v12, v6                                  ; 10180d0c
	v_mul_f32_e32 v13, v13, v6                                  ; 101a0d0d
	v_mul_f32_e32 v7, v7, v6                                    ; 100e0d07
BB4:
	s_andn2_b64 exec, s[4:5], exec                              ; 8afe7e04
	v_mov_b32_e32 v7, 0                                         ; 7e0e0280
	v_lshrrev_b64 v[12:13], 0, 0                                ; d700000c 00010080
BB6:
	s_buffer_load_dwordx4 s[0:3], s[0:3], 0x8                   ; f4280000 fa000008
	s_mov_b64 exec, s[4:5]                                      ; befe0404
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v12, s0, s3, v12                                  ; d541000c 04300600
	v_mad_f32 v13, s1, s3, v13                                  ; d541000d 04340601
	v_mad_f32 v7, s2, s3, v7                                    ; d5410007 041c0602
	v_log_f32_e32 v12, v12                                      ; 7e184f0c
	v_log_f32_e32 v13, v13                                      ; 7e1a4f0d
	v_log_f32_e32 v7, v7                                        ; 7e0e4f07
	v_mul_f32_e32 v12, 0x3ee8b439, v12                          ; 101818ff 3ee8b439
	v_mul_f32_e32 v13, 0x3ee8b439, v13                          ; 101a1aff 3ee8b439
	v_exp_f32_e32 v12, v12                                      ; 7e184b0c
	v_mul_f32_e32 v7, 0x3ee8b439, v7                            ; 100e0eff 3ee8b439
	v_exp_f32_e32 v13, v13                                      ; 7e1a4b0d
	v_exp_f32_e32 v7, v7                                        ; 7e0e4b07
	v_cvt_pkrtz_f16_f32_e32 v12, v12, v13                       ; 5e181b0c
	v_cvt_pkrtz_f16_f32_e64 v7, v7, 1.0                         ; d52f0007 0001e507
	exp mrt0 v12, v12, v7, v7 done compr vm                     ; f8001c0f 8080070c
	s_endpgm                                                    ; bf810000
