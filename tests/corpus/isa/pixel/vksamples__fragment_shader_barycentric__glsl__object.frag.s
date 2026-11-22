# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s5                                            ; befc0305
	s_cmp_eq_i32 s3, 0                                          ; bf008003
	v_interp_mov_f32_e32 v4, p0, attr0.x                        ; c8120002
	v_interp_mov_f32_e32 v5, p0, attr0.y                        ; c8160102
	v_interp_mov_f32_e32 v6, p0, attr0.z                        ; c81a0202
	v_interp_mov_f32_e32 v7, p10, attr0.x                       ; c81e0000
	v_interp_mov_f32_e32 v8, p10, attr0.y                       ; c8220100
	v_interp_mov_f32_e32 v9, p10, attr0.z                       ; c8260200
	v_interp_mov_f32_e32 v10, p20, attr0.x                      ; c82a0001
	v_interp_mov_f32_e32 v11, p20, attr0.y                      ; c82e0101
	v_interp_mov_f32_e32 v12, p20, attr0.z                      ; c8320201
	s_cbranch_scc0 BB9                                          ; bf84002e
BB1:
	s_bfe_u32 s0, s4, 0x20016                                   ; 9380ff04 00020016
	s_cbranch_scc1 BB3                                          ; bf850005
BB2:
	v_lshrrev_b64 v[13:14], 0, 0x3f800000                       ; d700000d 0001fe80 3f800000
	v_mov_b32_e32 v15, 0                                        ; 7e1e0280
	s_branch BB7                                                ; bf82001d
BB3:
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	s_cbranch_scc0 BB5                                          ; bf840004
BB4:
	v_add_f32_e32 v14, v0, v1                                   ; 061c0300
	v_mov_b32_e32 v15, 0                                        ; 7e1e0280
	v_sub_f32_e32 v13, 1.0, v14                                 ; 081a1cf2
	s_branch BB7                                                ; bf820017
BB5:
	v_mbcnt_lo_u32_b32 v13, -1, 0                               ; d765000d 000100c1
	v_sub_f32_e32 v16, 1.0, v1                                  ; 082002f2
	v_mbcnt_hi_u32_b32 v13, -1, v13                             ; d766000d 00021ac1
	v_sub_f32_e32 v16, v16, v0                                  ; 08200110
	v_lshrrev_b32_e32 v13, 2, v13                               ; 2c1a1a82
	v_lshlrev_b32_e32 v13, 1, v13                               ; 341a1a81
	v_bfe_u32 v13, s6, v13, 2                                   ; d548000d 020a1a06
	v_cmp_eq_i32_e32 vcc, 1, v13                                ; 7d041a81
	v_cmp_eq_i32_e64 s[0:1], 2, v13                             ; d4820000 00021a82
	v_cndmask_b32_e32 v17, v16, v0, vcc                         ; 02220110
	v_cndmask_b32_e32 v18, v0, v1, vcc                          ; 02240300
	v_cndmask_b32_e32 v15, v1, v16, vcc                         ; 021e2101
	v_cndmask_b32_e64 v13, v17, v1, s[0:1]                      ; d501000d 00020311
	v_cndmask_b32_e64 v18, v18, v16, s[0:1]                     ; d5010012 00022112
	v_cndmask_b32_e64 v15, v15, v0, s[0:1]                      ; d501000f 0002010f
	v_mov_b32_e32 v14, v18                                      ; 7e1c0312
BB7:
	v_mul_f32_e32 v16, v4, v13                                  ; 10201b04
	v_mul_f32_e32 v17, v5, v13                                  ; 10221b05
	v_mul_f32_e32 v13, v6, v13                                  ; 101a1b06
	v_mac_f32_e32 v16, v7, v14                                  ; 3e201d07
	v_mac_f32_e32 v17, v8, v14                                  ; 3e221d08
	v_mac_f32_e32 v13, v9, v14                                  ; 3e1a1d09
	v_mac_f32_e32 v16, v10, v15                                 ; 3e201f0a
	v_mac_f32_e32 v17, v11, v15                                 ; 3e221f0b
	v_mac_f32_e32 v13, v12, v15                                 ; 3e1a1f0c
BB9:
	s_cmp_eq_i32 s3, 1                                          ; bf008103
	s_cbranch_scc0 BB21                                         ; bf840058
BB10:
	s_bfe_u32 s0, s4, 0x20016                                   ; 9380ff04 00020016
	s_cbranch_scc1 BB12                                         ; bf850008
BB11:
	v_lshrrev_b64 v[2:3], 0, 0                                  ; d7000002 00010080
	v_lshrrev_b64 v[13:14], 0, 0x3f800000                       ; d700000d 0001fe80 3f800000
	v_mov_b32_e32 v15, 0                                        ; 7e1e0280
	v_mov_b32_e32 v18, 1.0                                      ; 7e2402f2
	s_branch BB19                                               ; bf82003a
BB12:
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	s_cbranch_scc0 BB14                                         ; bf840004
BB13:
	v_add_f32_e32 v14, v0, v1                                   ; 061c0300
	v_mov_b32_e32 v15, 0                                        ; 7e1e0280
	v_sub_f32_e32 v13, 1.0, v14                                 ; 081a1cf2
	s_branch BB15                                               ; bf820017
BB14:
	v_mbcnt_lo_u32_b32 v13, -1, 0                               ; d765000d 000100c1
	v_sub_f32_e32 v16, 1.0, v1                                  ; 082002f2
	v_mbcnt_hi_u32_b32 v13, -1, v13                             ; d766000d 00021ac1
	v_sub_f32_e32 v16, v16, v0                                  ; 08200110
	v_lshrrev_b32_e32 v13, 2, v13                               ; 2c1a1a82
	v_lshlrev_b32_e32 v13, 1, v13                               ; 341a1a81
	v_bfe_u32 v13, s6, v13, 2                                   ; d548000d 020a1a06
	v_cmp_eq_i32_e32 vcc, 1, v13                                ; 7d041a81
	v_cmp_eq_i32_e64 s[0:1], 2, v13                             ; d4820000 00021a82
	v_cndmask_b32_e32 v17, v16, v0, vcc                         ; 02220110
	v_cndmask_b32_e32 v18, v0, v1, vcc                          ; 02240300
	v_cndmask_b32_e32 v15, v1, v16, vcc                         ; 021e2101
	v_cndmask_b32_e64 v13, v17, v1, s[0:1]                      ; d501000d 00020311
	v_cndmask_b32_e64 v18, v18, v16, s[0:1]                     ; d5010012 00022112
	v_cndmask_b32_e64 v15, v15, v0, s[0:1]                      ; d501000f 0002010f
	v_mov_b32_e32 v14, v18                                      ; 7e1c0312
BB15:
	s_cbranch_scc0 BB17                                         ; bf840005
BB16:
	v_add_f32_e32 v2, v2, v3                                    ; 06040702
	v_sub_f32_e32 v3, 1.0, v2                                   ; 080604f2
	v_mov_b32_e32 v18, v3                                       ; 7e240303
	v_mov_b32_e32 v3, 0                                         ; 7e060280
	s_branch BB19                                               ; bf820017
BB17:
	v_mbcnt_lo_u32_b32 v16, -1, 0                               ; d7650010 000100c1
	v_sub_f32_e32 v17, 1.0, v3                                  ; 082206f2
	v_mbcnt_hi_u32_b32 v16, -1, v16                             ; d7660010 000220c1
	v_sub_f32_e32 v17, v17, v2                                  ; 08220511
	v_lshrrev_b32_e32 v16, 2, v16                               ; 2c202082
	v_lshlrev_b32_e32 v16, 1, v16                               ; 34202081
	v_bfe_u32 v16, s6, v16, 2                                   ; d5480010 020a2006
	v_cmp_eq_i32_e32 vcc, 1, v16                                ; 7d042081
	v_cmp_eq_i32_e64 s[0:1], 2, v16                             ; d4820000 00022082
	v_cndmask_b32_e32 v18, v17, v2, vcc                         ; 02240511
	v_cndmask_b32_e32 v19, v2, v3, vcc                          ; 02260702
	v_cndmask_b32_e64 v18, v18, v3, s[0:1]                      ; d5010012 00020712
	v_cndmask_b32_e32 v3, v3, v17, vcc                          ; 02062303
	v_cndmask_b32_e64 v19, v19, v17, s[0:1]                     ; d5010013 00022313
	v_cndmask_b32_e64 v3, v3, v2, s[0:1]                        ; d5010003 00020503
	v_mov_b32_e32 v2, v19                                       ; 7e040313
BB19:
	v_sub_f32_e32 v13, v13, v18                                 ; 081a250d
	v_sub_f32_e32 v15, v15, v3                                  ; 081e070f
	v_sub_f32_e32 v14, v14, v2                                  ; 081c050e
	v_mul_f32_e32 v13, 0x4166d4ca, v13                          ; 101a1aff 4166d4ca
	v_mul_f32_e32 v15, 0x4166d4ca, v15                          ; 101e1eff 4166d4ca
	v_mul_f32_e32 v14, 0x4166d4ca, v14                          ; 101c1cff 4166d4ca
	v_exp_f32_e64 v13, -v13                                     ; d5a5000d 2000010d
	v_exp_f32_e64 v15, -v15                                     ; d5a5000f 2000010f
	v_exp_f32_e64 v14, -v14                                     ; d5a5000e 2000010e
	v_sub_f32_e32 v16, 1.0, v13                                 ; 08201af2
	v_sub_f32_e32 v15, 1.0, v15                                 ; 081e1ef2
	v_sub_f32_e32 v17, 1.0, v14                                 ; 08221cf2
	v_mov_b32_e32 v13, v15                                      ; 7e1a030f
BB21:
	s_cmp_eq_i32 s3, 2                                          ; bf008203
	s_cbranch_scc0 BB30                                         ; bf84002d
BB22:
	s_bfe_u32 s0, s4, 0x20016                                   ; 9380ff04 00020016
	s_cbranch_scc1 BB24                                         ; bf850004
BB23:
	v_lshrrev_b64 v[2:3], 0, 0                                  ; d7000002 00010080
	v_mov_b32_e32 v15, 1.0                                      ; 7e1e02f2
	s_branch BB28                                               ; bf82001e
BB24:
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	s_cbranch_scc0 BB26                                         ; bf840005
BB25:
	v_add_f32_e32 v2, v0, v1                                    ; 06040300
	v_sub_f32_e32 v3, 1.0, v2                                   ; 080604f2
	v_mov_b32_e32 v15, v3                                       ; 7e1e0303
	v_mov_b32_e32 v3, 0                                         ; 7e060280
	s_branch BB28                                               ; bf820017
BB26:
	v_mbcnt_lo_u32_b32 v13, -1, 0                               ; d765000d 000100c1
	v_sub_f32_e32 v14, 1.0, v1                                  ; 081c02f2
	v_mbcnt_hi_u32_b32 v13, -1, v13                             ; d766000d 00021ac1
	v_sub_f32_e32 v14, v14, v0                                  ; 081c010e
	v_lshrrev_b32_e32 v13, 2, v13                               ; 2c1a1a82
	v_lshlrev_b32_e32 v13, 1, v13                               ; 341a1a81
	v_bfe_u32 v13, s6, v13, 2                                   ; d548000d 020a1a06
	v_cmp_eq_i32_e32 vcc, 1, v13                                ; 7d041a81
	v_cmp_eq_i32_e64 s[0:1], 2, v13                             ; d4820000 00021a82
	v_cndmask_b32_e32 v15, v14, v0, vcc                         ; 021e010e
	v_cndmask_b32_e32 v16, v0, v1, vcc                          ; 02200300
	v_cndmask_b32_e32 v3, v1, v14, vcc                          ; 02061d01
	v_cndmask_b32_e64 v15, v15, v1, s[0:1]                      ; d501000f 0002030f
	v_cndmask_b32_e64 v16, v16, v14, s[0:1]                     ; d5010010 00021d10
	v_cndmask_b32_e64 v3, v3, v0, s[0:1]                        ; d5010003 00020103
	v_mov_b32_e32 v2, v16                                       ; 7e040310
BB28:
	v_min3_f32 v15, v15, v3, v2                                 ; d551000f 040a070f
	v_cmp_gt_f32_e32 vcc, 0x3c23d70a, v15                       ; 7c081eff 3c23d70a
	v_cndmask_b32_e64 v13, 0.5, 0, vcc                          ; d501000d 01a900f0
	v_mov_b32_e32 v16, v13                                      ; 7e20030d
	v_mov_b32_e32 v17, v13                                      ; 7e22030d
BB30:
	s_cmp_eq_i32 s3, 3                                          ; bf008303
	s_cbranch_scc0 BB45                                         ; bf84003d
BB31:
	s_bfe_u32 s0, s4, 0x20016                                   ; 9380ff04 00020016
	s_cbranch_scc0 BB36                                         ; bf84001f
BB32:
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	s_cbranch_scc0 BB34                                         ; bf840005
BB33:
	v_add_f32_e32 v2, v0, v1                                    ; 06040300
	v_sub_f32_e32 v3, 1.0, v2                                   ; 080604f2
	v_mov_b32_e32 v15, v3                                       ; 7e1e0303
	v_mov_b32_e32 v3, 0                                         ; 7e060280
	s_branch BB37                                               ; bf82001b
BB34:
	v_mbcnt_lo_u32_b32 v13, -1, 0                               ; d765000d 000100c1
	v_sub_f32_e32 v14, 1.0, v1                                  ; 081c02f2
	v_mbcnt_hi_u32_b32 v13, -1, v13                             ; d766000d 00021ac1
	v_sub_f32_e32 v14, v14, v0                                  ; 081c010e
	v_lshrrev_b32_e32 v13, 2, v13                               ; 2c1a1a82
	v_lshlrev_b32_e32 v13, 1, v13                               ; 341a1a81
	v_bfe_u32 v13, s6, v13, 2                                   ; d548000d 020a1a06
	v_cmp_eq_i32_e32 vcc, 1, v13                                ; 7d041a81
	v_cmp_eq_i32_e64 s[0:1], 2, v13                             ; d4820000 00021a82
	v_cndmask_b32_e32 v15, v14, v0, vcc                         ; 021e010e
	v_cndmask_b32_e32 v16, v0, v1, vcc                          ; 02200300
	v_cndmask_b32_e32 v3, v1, v14, vcc                          ; 02061d01
	v_cndmask_b32_e64 v15, v15, v1, s[0:1]                      ; d501000f 0002030f
	v_cndmask_b32_e64 v16, v16, v14, s[0:1]                     ; d5010010 00021d10
	v_cndmask_b32_e64 v3, v3, v0, s[0:1]                        ; d5010003 00020103
	v_mov_b32_e32 v2, v16                                       ; 7e040310
	s_branch BB37                                               ; bf820003
BB36:
	v_lshrrev_b64 v[2:3], 0, 0                                  ; d7000002 00010080
	v_mov_b32_e32 v15, 1.0                                      ; 7e1e02f2
BB37:
	v_cmp_ge_f32_e32 vcc, v2, v15                               ; 7c0c1f02
	v_cmp_ge_f32_e64 s[0:1], v3, v15                            ; d4060000 00021f03
	s_and_b64 s[0:1], vcc, s[0:1]                               ; 8780006a
	s_and_saveexec_b64 s[0:1], s[0:1]                           ; be802400
BB38:
	v_mul_f32_e32 v16, v4, v15                                  ; 10201f04
	v_mul_f32_e32 v17, v5, v15                                  ; 10221f05
	v_mul_f32_e32 v13, v6, v15                                  ; 101a1f06
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	s_cbranch_execz BB43                                        ; bf88000d
BB41:
	v_cmp_lt_f32_e32 vcc, v2, v15                               ; 7c021f02
	v_cmp_ge_f32_e64 s[8:9], v3, v2                             ; d4060008 00020503
	v_mul_f32_e32 v7, v7, v2                                    ; 100e0507
	v_mul_f32_e32 v8, v8, v2                                    ; 10100508
	v_mul_f32_e32 v9, v9, v2                                    ; 10120509
	v_mul_f32_e32 v10, v10, v3                                  ; 1014070a
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	v_mul_f32_e32 v12, v12, v3                                  ; 1018070c
	s_and_b64 vcc, vcc, s[8:9]                                  ; 87ea086a
	v_cndmask_b32_e32 v16, v10, v7, vcc                         ; 02200f0a
	v_cndmask_b32_e32 v17, v11, v8, vcc                         ; 0222110b
	v_cndmask_b32_e32 v13, v12, v9, vcc                         ; 021a130c
BB43:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
BB45:
	s_cmp_eq_i32 s3, 4                                          ; bf008403
	s_cbranch_scc0 BB53                                         ; bf84003b
BB46:
	s_bfe_u32 s4, s4, 0x20016                                   ; 9384ff04 00020016
	s_cbranch_scc0 BB51                                         ; bf84001f
BB47:
	s_cmp_eq_i32 s4, 1                                          ; bf008104
	s_cbranch_scc0 BB49                                         ; bf840005
BB48:
	v_add_f32_e32 v0, v0, v1                                    ; 06000300
	v_sub_f32_e32 v1, 1.0, v0                                   ; 080200f2
	v_mov_b32_e32 v4, v1                                        ; 7e080301
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	s_branch BB52                                               ; bf82001b
BB49:
	v_mbcnt_lo_u32_b32 v2, -1, 0                                ; d7650002 000100c1
	v_sub_f32_e32 v3, 1.0, v1                                   ; 080602f2
	v_mbcnt_hi_u32_b32 v2, -1, v2                               ; d7660002 000204c1
	v_sub_f32_e32 v3, v3, v0                                    ; 08060103
	v_lshrrev_b32_e32 v2, 2, v2                                 ; 2c040482
	v_lshlrev_b32_e32 v2, 1, v2                                 ; 34040481
	v_bfe_u32 v2, s6, v2, 2                                     ; d5480002 020a0406
	v_cmp_eq_i32_e32 vcc, 1, v2                                 ; 7d040481
	v_cmp_eq_i32_e64 s[0:1], 2, v2                              ; d4820000 00020482
	v_cndmask_b32_e32 v4, v3, v0, vcc                           ; 02080103
	v_cndmask_b32_e32 v5, v0, v1, vcc                           ; 020a0300
	v_cndmask_b32_e64 v4, v4, v1, s[0:1]                        ; d5010004 00020304
	v_cndmask_b32_e32 v1, v1, v3, vcc                           ; 02020701
	v_cndmask_b32_e64 v5, v5, v3, s[0:1]                        ; d5010005 00020705
	v_cndmask_b32_e64 v1, v1, v0, s[0:1]                        ; d5010001 00020101
	v_mov_b32_e32 v0, v5                                        ; 7e000305
	s_branch BB52                                               ; bf820003
BB51:
	v_lshrrev_b64 v[0:1], 0, 0                                  ; d7000000 00010080
	v_mov_b32_e32 v4, 1.0                                       ; 7e0802f2
BB52:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[0:3], s[2:3], 0x70                         ; f4080001 fa000070
	v_mul_f32_e32 v1, 0x3ea2f983, v1                            ; 100202ff 3ea2f983
	v_mul_f32_e32 v4, 0.15915494, v4                            ; 100808f8
	v_mul_f32_e32 v0, 0x3ea2f983, v0                            ; 100000ff 3ea2f983
	v_cos_f32_e32 v1, v1                                        ; 7e026d01
	v_sin_f32_e32 v4, v4                                        ; 7e086b04
	v_cos_f32_e32 v0, v0                                        ; 7e006d00
	v_add_f32_e32 v2, v4, v1                                    ; 06040304
	v_add_f32_e32 v3, v4, v0                                    ; 06060104
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[16:19], v[2:3], s[8:15], s[0:3] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00021002
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mov_b32_e32 v13, v18                                      ; 7e1a0312
	s_branch BB54                                               ; bf820001
BB53:
	v_mov_b32_e32 v19, 1.0                                      ; 7e2602f2
BB54:
	v_cvt_pkrtz_f16_f32_e32 v16, v16, v17                       ; 5e202310
	v_cvt_pkrtz_f16_f32_e32 v13, v13, v19                       ; 5e1a270d
	exp mrt0 v16, v16, v13, v13 done compr vm                   ; f8001c0f 80800d10
	s_endpgm                                                    ; bf810000
