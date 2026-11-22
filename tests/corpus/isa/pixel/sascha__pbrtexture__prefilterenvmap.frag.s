# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_mov_b32 m0, s5                                            ; befc0305
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_mov_b32 s1, 0                                             ; be810380
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	v_lshrrev_b64 v[6:7], 0, 0                                  ; d7000006 00010080
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mac_f32_e32 v3, v0, v0                                    ; 3e060100
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_bfe_u32 s19, s11, 0x4000c                                 ; 9393ff0b 0004000c
	s_bfe_u32 s18, s10, 0x10000e                                ; 9392ff0a 0010000e
	s_add_u32 s18, s18, 1                                       ; 80128112
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	s_lshr_b32 s18, s18, s19                                    ; 90121312
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_cselect_b32 s18, 0, s18                                   ; 85121280
	v_cvt_f32_i32_e32 v5, s18                                   ; 7e0a0a12
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mul_f32_e32 v0, v0, v3                                    ; 10000700
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mov_b32_e32 v3, 0                                         ; 7e060280
BB1:
	s_cmp_ge_u32 s1, s4                                         ; bf090401
	s_cbranch_scc1 BB11                                         ; bf8500cc
BB4:
	s_mov_b32 s6, s1                                            ; be860301
	s_mov_b32 s7, s1                                            ; be870301
	s_lshr_b64 s[6:7], s[6:7], 16                               ; 90869006
	s_and_b32 s5, s6, 0xaaaaaaaa                                ; 8705ff06 aaaaaaaa
	s_lshr_b32 s5, s5, 1                                        ; 90058105
	s_and_b32 s6, s6, 0x55555555                                ; 8706ff06 55555555
	s_lshl_b32 s6, s6, 1                                        ; 8f068106
	s_or_b32 s6, s6, s5                                         ; 88060506
	v_cvt_f32_u32_e32 v8, s1                                    ; 7e100c01
	s_and_b32 s7, s6, 0xcccccccc                                ; 8707ff06 cccccccc
	v_cvt_f32_u32_e32 v9, s4                                    ; 7e120c04
	s_lshr_b32 s7, s7, 2                                        ; 90078207
	s_and_b32 s6, s6, 0x33333333                                ; 8706ff06 33333333
	v_mul_f32_e32 v8, 0x40c90fdb, v8                            ; 101010ff 40c90fdb
	v_mul_f32_e32 v11, 0x414fd639, v0                           ; 101600ff 414fd639
	v_rcp_f32_e32 v10, v9                                       ; 7e145509
	s_lshl_b32 s6, s6, 2                                        ; 8f068206
	v_madmk_f32 v11, v4, 0x429c774c, v11                        ; 40161704 429c774c
	s_or_b32 s6, s6, s7                                         ; 88060706
	s_and_b32 s16, s6, 0xf0f0f0f0                               ; 8710ff06 f0f0f0f0
	v_mul_f32_e32 v12, 0x3ea30eac, v11                          ; 101816ff 3ea30eac
	s_lshr_b32 s16, s16, 4                                      ; 90108410
	s_and_b32 s6, s6, 0xf0f0f0f                                 ; 8706ff06 0f0f0f0f
	v_mul_f32_e32 v8, v8, v10                                   ; 10101508
	v_mul_f32_e64 v13, s0, s0                                   ; d508000d 00000000
	s_lshl_b32 s6, s6, 4                                        ; 8f068406
	v_floor_f32_e32 v12, v12                                    ; 7e18490c
	s_or_b32 s6, s6, s16                                        ; 88061006
	v_mul_f32_e32 v13, v13, v13                                 ; 101a1b0d
	s_and_b32 s17, s6, 0xff00ff00                               ; 8711ff06 ff00ff00
	v_mad_f32 v12, 0x4048f5c3, -v12, v11                        ; d541000c 442e18ff 4048f5c3
	s_lshr_b32 s17, s17, 8                                      ; 90118811
	s_and_b32 s6, s6, 0xff00ff                                  ; 8706ff06 00ff00ff
	s_lshl_b32 s6, s6, 8                                        ; 8f068806
	v_mul_f32_e32 v12, 0.15915494, v12                          ; 101818f8
	s_or_b32 s6, s6, s17                                        ; 88061106
	v_cvt_f32_u32_e32 v14, s6                                   ; 7e1c0c06
	v_sin_f32_e32 v12, v12                                      ; 7e186b0c
	v_cmp_gt_f32_e64 s[6:7], 0x3f7fbe77, |v4|                   ; d4040206 000208ff 3f7fbe77
	v_mul_f32_e32 v14, 0x2f800000, v14                          ; 101c1cff 2f800000
	v_cndmask_b32_e64 v18, 0, 1.0, s[6:7]                       ; d5010012 0019e480
	v_sub_f32_e32 v15, 1.0, v14                                 ; 081e1cf2
	s_not_b64 s[6:7], s[6:7]                                    ; be860806
	v_mul_f32_e32 v12, 0x472aee8c, v12                          ; 101818ff 472aee8c
	v_cndmask_b32_e64 v20, 0, 1.0, s[6:7]                       ; d5010014 0019e480
	v_mul_f32_e32 v19, v18, v2                                  ; 10260512
	v_mad_f32 v14, v13, v14, v15                                ; d541000e 043e1d0d
	v_fract_f32_e32 v12, v12                                    ; 7e18410c
	v_mul_f32_e32 v21, v20, v4                                  ; 102a0914
	v_mul_f32_e32 v20, v20, v2                                  ; 10280514
	v_rcp_f32_e32 v14, v14                                      ; 7e1c550e
	v_madmk_f32 v12, v12, 0x3dcccccd, v8                        ; 4018110c 3dcccccd
	v_mad_f32 v18, v18, v0, -v21                                ; d5410012 84560112
	v_mul_f32_e32 v12, 0.15915494, v12                          ; 101818f8
	v_mul_f32_e32 v22, v18, v18                                 ; 102c2512
	v_mul_f32_e32 v15, v15, v14                                 ; 101e1d0f
	v_cos_f32_e32 v16, v12                                      ; 7e206d0c
	v_sin_f32_e32 v12, v12                                      ; 7e186b0c
	v_mac_f32_e32 v22, v20, v20                                 ; 3e2c2914
	v_sub_f32_e64 v17, 1.0, |v15|                               ; d5040211 00021ef2
	v_mac_f32_e32 v22, v19, v19                                 ; 3e2c2713
	v_sqrt_f32_e32 v17, v17                                     ; 7e226711
	v_rsq_f32_e32 v22, v22                                      ; 7e2c5d16
	v_mul_f32_e32 v16, v17, v16                                 ; 10202111
	v_mul_f32_e32 v17, v17, v12                                 ; 10221911
	v_mul_f32_e32 v19, v19, v22                                 ; 10262d13
	v_mul_f32_e32 v18, v18, v22                                 ; 10242d12
	v_mul_f32_e32 v20, v20, v22                                 ; 10282d14
	v_mul_f32_e32 v10, v19, v2                                  ; 10140513
	v_mul_f32_e32 v23, v4, v18                                  ; 102e2504
	v_mul_f32_e32 v8, v0, v20                                   ; 10102900
	v_mac_f32_e32 v10, v0, v18                                  ; 3e142500
	v_mul_f32_e32 v18, v18, v16                                 ; 10242112
	v_mad_f32 v23, v2, v20, -v23                                ; d5410017 845e2902
	v_mul_f32_e32 v20, v20, v16                                 ; 10282114
	v_sqrt_f32_e32 v15, v15                                     ; 7e1e670f
	v_mad_f32 v8, v19, -v4, -v8                                 ; d5410008 c4220913
	v_mul_f32_e32 v19, v19, v16                                 ; 10262113
	v_mul_f32_e32 v11, v8, v8                                   ; 10161108
	v_mac_f32_e32 v11, v10, v10                                 ; 3e16150a
	v_mac_f32_e32 v11, v23, v23                                 ; 3e162f17
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_mul_f32_e32 v8, v8, v11                                   ; 10101708
	v_mul_f32_e32 v23, v23, v11                                 ; 102e1717
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mac_f32_e32 v18, v8, v17                                  ; 3e242308
	v_mad_f32 v23, v23, v17, -v19                               ; d5410017 844e2317
	v_mac_f32_e32 v20, v10, v17                                 ; 3e28230a
	v_mac_f32_e32 v18, v2, v15                                  ; 3e241f02
	v_mac_f32_e32 v23, v0, v15                                  ; 3e2e1f00
	v_mac_f32_e32 v20, v4, v15                                  ; 3e281f04
	v_mul_f32_e32 v12, v18, v18                                 ; 10182512
	v_mac_f32_e32 v12, v20, v20                                 ; 3e182914
	s_mov_b64 s[6:7], exec                                      ; be86047e
	v_mac_f32_e32 v12, v23, v23                                 ; 3e182f17
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_mul_f32_e32 v23, v23, v12                                 ; 102e1917
	v_mul_f32_e32 v20, v20, v12                                 ; 10281914
	v_mul_f32_e32 v18, v18, v12                                 ; 10241912
	v_mul_f32_e32 v14, v4, v20                                  ; 101c2904
	v_mac_f32_e32 v14, v2, v18                                  ; 3e1c2502
	v_mac_f32_e32 v14, v0, v23                                  ; 3e1c2f00
	v_mul_f32_e32 v15, 2.0, v14                                 ; 101e1cf4
	v_mad_f32 v23, v23, v15, -v0                                ; d5410017 84021f17
	v_mad_f32 v20, v20, v15, -v4                                ; d5410014 84121f14
	v_mad_f32 v18, v18, v15, -v2                                ; d5410012 840a1f12
	v_mul_f32_e32 v16, v4, v20                                  ; 10202904
	v_mac_f32_e32 v16, v2, v18                                  ; 3e202502
	v_mad_f32 v16, v0, v23, v16 clamp                           ; d5418010 04422f00
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v16                                    ; 7c222080
	s_cbranch_execz BB10                                        ; bf880039
BB5:
	s_load_dwordx4 s[16:19], s[2:3], 0x50                       ; f4080401 fa000050
	v_add_f32_e64 v14, v14, 0 clamp                             ; d503800e 0001010e
	v_mul_f32_e32 v12, 0x40c00000, v5                           ; 10180aff 40c00000
	v_mul_f32_e32 v8, v14, v14                                  ; 10101d0e
	v_mul_f32_e32 v12, v12, v5                                  ; 10180b0c
	v_sub_f32_e32 v10, 1.0, v8                                  ; 081410f2
	v_rcp_f32_e32 v12, v12                                      ; 7e18550c
	v_mac_f32_e32 v10, v13, v8                                  ; 3e14110d
	v_mul_f32_e32 v11, 0x40490fdb, v10                          ; 101614ff 40490fdb
	v_cmp_eq_f32_e64 s[20:21], s0, 0                            ; d4020014 00010000
	v_mul_f32_e32 v12, 0x41490fdb, v12                          ; 101818ff 41490fdb
	v_mul_f32_e32 v11, v11, v10                                 ; 1016150b
	v_rcp_f32_e32 v12, v12                                      ; 7e18550c
	v_rcp_f32_e32 v11, v11                                      ; 7e16550b
	v_cubetc_f32 v15, v23, v18, v20                             ; d546000f 04522517
	v_cubeid_f32 v10, v23, v18, v20                             ; d544000a 04522517
	v_mul_f32_e32 v13, v13, v11                                 ; 101a170d
	v_mul_f32_e32 v13, v13, v14                                 ; 101a1d0d
	v_mul_f32_e32 v14, 4.0, v14                                 ; 101c1cf6
	v_rcp_f32_e32 v14, v14                                      ; 7e1c550e
	v_madak_f32 v13, v13, v14, 0x38d1b717                       ; 421a1d0d 38d1b717
	v_cubesc_f32 v14, v23, v18, v20                             ; d545000e 04522517
	v_mul_f32_e32 v9, v9, v13                                   ; 10121b09
	v_cubema_f32 v13, v23, v18, v20                             ; d547000d 04522517
	v_rcp_f32_e32 v9, v9                                        ; 7e125509
	v_rcp_f32_e64 v13, |v13|                                    ; d5aa010d 0000010d
	v_mul_f32_e32 v9, v9, v12                                   ; 10121909
	v_madak_f32 v8, v14, v13, 0x3fc00000                        ; 42101b0e 3fc00000
	v_log_f32_e64 v9, v9 div:2                                  ; d5a70009 18000109
	v_add_f32_e32 v9, 1.0, v9                                   ; 061212f2
	v_max_f32_e32 v9, 0, v9                                     ; 20121280
	v_cndmask_b32_e64 v11, v9, 0, s[20:21]                      ; d501000b 00510109
	v_madak_f32 v9, v15, v13, 0x3fc00000                        ; 42121b0f 3fc00000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_l v[17:19], v[8:11], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0900718 00821108
	v_add_f32_e32 v7, v7, v16                                   ; 060e2107
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v6, v17, v16                                  ; 3e0c2111
	v_mac_f32_e32 v3, v18, v16                                  ; 3e062112
	v_mac_f32_e32 v1, v19, v16                                  ; 3e022113
BB10:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	s_add_u32 s1, s1, 1                                         ; 80018101
	s_branch BB1                                                ; bf82ff32
BB11:
	v_rcp_f32_e32 v7, v7                                        ; 7e0e5507
	v_fma_mixlo_f16 v0, v6, v7, neg(0) op_sel_hi:[0,0,1]        ; cc214000 82020f06
	v_fma_mixhi_f16 v0, v3, v7, neg(0) op_sel_hi:[0,0,1]        ; cc224000 82020f03
	v_mul_f32_e32 v1, v1, v7                                    ; 10020f01
	v_cvt_pkrtz_f16_f32_e64 v1, v1, 1.0                         ; d52f0001 0001e501
	exp mrt0 v0, v0, v1, v1 done compr vm                       ; f8001c0f 80800100
	s_endpgm                                                    ; bf810000
