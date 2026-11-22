# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x5                                                ; bfa10005
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_load_dwordx8 s[16:23], s[2:3], 0x60                       ; f40c0401 fa000060
	s_load_dwordx4 s[24:27], s[2:3], 0xb0                       ; f4080601 fa0000b0
	s_load_dwordx8 s[32:39], s[2:3], 0xc0                       ; f40c0801 fa0000c0
	s_load_dwordx8 s[40:47], s[2:3], 0x110                      ; f40c0a01 fa000110
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[3:5], [v0, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220300 00000002
	image_sample  v[6:8], [v0, v2], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00c40600 00000002
	s_bfe_u32 s1, s9, 0x2001e                                   ; 9381ff09 0002001e
	s_add_u32 s1, s1, 1                                         ; 80018101
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_and_b32 s16, s10, 0x3fff                                  ; 8710ff0a 00003fff
	s_lshl2_add_u32 s16, s16, s1                                ; 97900110
	s_load_dwordx4 s[0:3], s[2:3], 0x130                        ; f4080001 fa000130
	s_bfe_u32 s19, s11, 0x4000c                                 ; 9393ff0b 0004000c
	s_lshr_b32 s16, s16, s19                                    ; 90101310
	s_bfe_u32 s18, s10, 0x10000e                                ; 9392ff0a 0010000e
	s_add_u32 s18, s18, 1                                       ; 80128112
	s_lshr_b32 s18, s18, s19                                    ; 90121312
	s_max_u32 s16, s16, 1                                       ; 84908110
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_cselect_b32 s16, 0, s16                                   ; 85101080
	s_max_u32 s18, s18, 1                                       ; 84928112
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	v_cvt_f32_i32_e32 v9, s16                                   ; 7e120a10
	s_cselect_b32 s18, 0, s18                                   ; 85121280
	s_bfe_u32 s20, s33, 0x2001e                                 ; 9394ff21 0002001e
	v_cvt_f32_i32_e32 v10, s18                                  ; 7e140a12
	s_add_u32 s20, s20, 1                                       ; 80148114
	s_and_b32 s21, s34, 0x3fff                                  ; 8715ff22 00003fff
	s_lshl2_add_u32 s21, s21, s20                               ; 97951415
	s_bfe_u32 s19, s35, 0x4000c                                 ; 9393ff23 0004000c
	s_lshr_b32 s21, s21, s19                                    ; 90151315
	s_bfe_u32 s18, s34, 0x10000e                                ; 9392ff22 0010000e
	s_add_u32 s18, s18, 1                                       ; 80128112
	s_lshr_b32 s18, s18, s19                                    ; 90121312
	s_max_u32 s21, s21, 1                                       ; 84958115
	s_cmp_eq_i32 s33, 0                                         ; bf008021
	s_cselect_b32 s21, 0, s21                                   ; 85151580
	s_max_u32 s18, s18, 1                                       ; 84928112
	s_cmp_eq_i32 s33, 0                                         ; bf008021
	v_cvt_f32_i32_e32 v11, s21                                  ; 7e160a15
	s_cselect_b32 s18, 0, s18                                   ; 85121280
	v_cvt_f32_i32_e32 v12, s18                                  ; 7e180a12
	v_rcp_f32_e32 v11, v11                                      ; 7e16550b
	v_rcp_f32_e32 v12, v12                                      ; 7e18550c
	v_mul_f32_e32 v9, v9, v11                                   ; 10121709
	v_mul_f32_e32 v10, v10, v12                                 ; 1014190a
	v_mul_f32_e32 v0, v9, v0                                    ; 10000109
	v_mul_f32_e32 v1, v10, v2                                   ; 1002050a
	image_sample v[13:15], v[0:1], s[32:39], s[40:43] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 01480d00
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx16 s[16:31], s[0:3], null               ; f4300400 fa000000
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mad_f32 v6, 2.0, v6, -1.0                                 ; d5410006 03ce0cf4
	v_mad_f32 v7, 2.0, v7, -1.0                                 ; d5410007 03ce0ef4
	v_mad_f32 v8, 2.0, v8, -1.0                                 ; d5410008 03ce10f4
	v_mul_f32_e32 v16, v7, v7                                   ; 10200f07
	v_mac_f32_e32 v16, v8, v8                                   ; 3e201108
	v_mac_f32_e32 v16, v6, v6                                   ; 3e200d06
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_mul_f32_e32 v7, v7, v16                                   ; 100e2107
	v_mul_f32_e32 v8, v8, v16                                   ; 10102108
	v_mul_f32_e32 v6, v6, v16                                   ; 100c2106
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v15, 2.0, v15, -1.0                               ; d541000f 03ce1ef4
	v_mad_f32 v14, 2.0, v14, -1.0                               ; d541000e 03ce1cf4
	v_mad_f32 v13, 2.0, v13, -1.0                               ; d541000d 03ce1af4
	v_mul_f32_e32 v17, v15, v8                                  ; 1022110f
	v_mac_f32_e32 v17, v14, v7                                  ; 3e220f0e
	v_mac_f32_e32 v17, v13, v6                                  ; 3e220d0d
	v_mad_f32 v13, v6, -v17, v13                                ; d541000d 44362306
	v_mad_f32 v14, v7, -v17, v14                                ; d541000e 443a2307
	v_mad_f32 v17, v8, -v17, v15                                ; d5410011 443e2308
	s_mov_b32 s0, 0                                             ; be800380
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_mul_f32_e32 v18, v14, v14                                 ; 10241d0e
	v_mac_f32_e32 v18, v17, v17                                 ; 3e242311
	v_mac_f32_e32 v18, v13, v13                                 ; 3e241b0d
	v_rsq_f32_e32 v18, v18                                      ; 7e245d12
	v_mul_f32_e32 v13, v13, v18                                 ; 101a250d
	v_mul_f32_e32 v14, v14, v18                                 ; 101c250e
	v_mul_f32_e32 v17, v17, v18                                 ; 10222511
	v_mul_f32_e32 v20, v13, v8                                  ; 1028110d
	v_mul_f32_e32 v21, v14, v6                                  ; 102a0d0e
	v_mul_f32_e32 v19, v17, v7                                  ; 10260f11
	v_mad_f32 v20, v17, v6, -v20                                ; d5410014 84520d11
	v_mad_f32 v21, v13, v7, -v21                                ; d5410015 84560f0d
	v_mad_f32 v19, v14, v8, -v19                                ; d5410013 844e110e
BB1:
	s_lshl_b32 s1, s0, 4                                        ; 8f018400
	s_buffer_load_dwordx4 s[32:35], s[44:47], s1                ; f4280816 02000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v1, s34, v6                                   ; 10020c22
	v_mul_f32_e32 v2, s34, v7                                   ; 10040e22
	v_mul_f32_e32 v9, s34, v8                                   ; 10121022
	v_mac_f32_e32 v1, s33, v19                                  ; 3e022621
	v_mac_f32_e32 v2, s33, v20                                  ; 3e042821
	v_mac_f32_e32 v9, s33, v21                                  ; 3e122a21
	v_mad_f32 v1, s32, v13, v1 div:2                            ; d5410001 1c061a20
	v_mad_f32 v2, s32, v14, v2 div:2                            ; d5410002 1c0a1c20
	v_mad_f32 v9, s32, v17, v9 div:2                            ; d5410009 1c262220
	v_add_f32_e32 v1, v3, v1                                    ; 06020303
	v_add_f32_e32 v2, v4, v2                                    ; 06040504
	v_add_f32_e32 v9, v5, v9                                    ; 06121305
	v_mad_f32 v12, s27, v9, s31                                 ; d541000c 007e121b
	v_mad_f32 v10, s24, v9, s28                                 ; d541000a 00721218
	v_mad_f32 v11, s25, v9, s29                                 ; d541000b 00761219
	v_mac_f32_e32 v12, s23, v2                                  ; 3e180417
	v_mac_f32_e32 v10, s20, v2                                  ; 3e140414
	v_mac_f32_e32 v11, s21, v2                                  ; 3e160415
	v_mac_f32_e32 v12, s19, v1                                  ; 3e180213
	v_mad_f32 v10, s16, v1, v10 div:2                           ; d541000a 1c2a0210
	v_mad_f32 v11, s17, v1, v11 div:2                           ; d541000b 1c2e0211
	v_rcp_f32_e32 v12, v12                                      ; 7e18550c
	v_mad_f32 v23, v11, v12, 0.5                                ; d5410017 03c2190b
	v_mad_f32 v22, v10, v12, 0.5                                ; d5410016 03c2190a
	image_sample v22, v[22:23], s[8:15], s[4:7] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f0800808 00221616
	s_add_u32 s0, s0, 1                                         ; 80008100
	v_add_f32_e32 v9, 0x3ccccccd, v9                            ; 061212ff 3ccccccd
	s_cmp_ge_i32 s0, 64                                         ; bf03c000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v15, v5, v22                                  ; 061e2d05
	v_cmp_ge_f32_e64 vcc, -v22, v9                              ; d406006a 20021316
	v_rcp_f32_e64 v15, |v15| clamp div:2                        ; d5aa810f 1800010f
	v_madak_f32 v16, -2.0, v15, 0x40400000                      ; 42201ef5 40400000
	v_mul_f32_e32 v16, v15, v16                                 ; 1020210f
	v_mul_f32_e32 v15, v15, v16                                 ; 101e210f
	v_cndmask_b32_e32 v15, 0, v15, vcc                          ; 021e1e80
	v_add_f32_e32 v0, v0, v15                                   ; 06001f00
	s_cbranch_scc0 BB1                                          ; bf84ffc7
BB5:
	v_mad_f32 v0, 0x3c800000, -v0, 1.0                          ; d5410000 43ca00ff 3c800000
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 0                           ; d52f0000 00010100
	exp mrt0 v0, v0, off, off done compr vm                     ; f8001c03 80808000
	s_endpgm                                                    ; bf810000
