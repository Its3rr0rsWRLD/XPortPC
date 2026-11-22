# Pixel Shader
BB0:
	s_bfe_u32 s2, s2, 0x20016                                   ; 9382ff02 00020016
	s_cbranch_scc1 BB2                                          ; bf850004
BB1:
	v_lshrrev_b64 v[2:3], 0, 0                                  ; d7000002 00010080
	v_mov_b32_e32 v4, 1.0                                       ; 7e0802f2
	s_branch BB6                                                ; bf82001d
BB2:
	s_cmp_eq_i32 s2, 1                                          ; bf008102
	s_cbranch_scc0 BB4                                          ; bf840005
BB3:
	v_add_f32_e32 v2, v0, v1                                    ; 06040300
	v_sub_f32_e32 v3, 1.0, v2                                   ; 080604f2
	v_mov_b32_e32 v4, v3                                        ; 7e080303
	v_mov_b32_e32 v3, 0                                         ; 7e060280
	s_branch BB6                                                ; bf820016
BB4:
	v_mbcnt_lo_u32_b32 v2, -1, 0                                ; d7650002 000100c1
	v_sub_f32_e32 v3, 1.0, v1                                   ; 080602f2
	v_mbcnt_hi_u32_b32 v2, -1, v2                               ; d7660002 000204c1
	v_sub_f32_e32 v3, v3, v0                                    ; 08060103
	v_lshrrev_b32_e32 v2, 2, v2                                 ; 2c040482
	v_lshlrev_b32_e32 v2, 1, v2                                 ; 34040481
	v_bfe_u32 v2, s4, v2, 2                                     ; d5480002 020a0404
	v_cmp_eq_i32_e32 vcc, 1, v2                                 ; 7d040481
	v_cmp_eq_i32_e64 s[0:1], 2, v2                              ; d4820000 00020482
	v_cndmask_b32_e32 v4, v3, v0, vcc                           ; 02080103
	v_cndmask_b32_e32 v5, v0, v1, vcc                           ; 020a0300
	v_cndmask_b32_e64 v4, v4, v1, s[0:1]                        ; d5010004 00020304
	v_cndmask_b32_e64 v2, v5, v3, s[0:1]                        ; d5010002 00020705
	v_cndmask_b32_e32 v3, v1, v3, vcc                           ; 02060701
	v_cndmask_b32_e64 v3, v3, v0, s[0:1]                        ; d5010003 00020103
BB6:
	s_mov_b32 m0, s3                                            ; befc0303
	v_min3_f32 v4, v4, v3, v2                                   ; d5510004 040a0704
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_cmp_gt_f32_e32 vcc, 0x3ca3d70a, v4                        ; 7c0808ff 3ca3d70a
	v_interp_p1_f32_e32 v4, v0, attr0.y                         ; c8100100
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v4, v1, attr0.y                         ; c8110101
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mul_f32_e32 v3, 0.5, v2                                   ; 100604f0
	v_mul_f32_e32 v2, 2.0, v2                                   ; 100404f4
	v_cndmask_b32_e64 v7, 0.5, 2.0, vcc                         ; d5010007 01a9e8f0
	v_mul_f32_e32 v5, 2.0, v4                                   ; 100a08f4
	v_mul_f32_e32 v4, 0.5, v4                                   ; 100808f0
	v_mul_f32_e32 v6, 2.0, v0                                   ; 100c00f4
	v_mul_f32_e32 v0, 0.5, v0                                   ; 100000f0
	v_cndmask_b32_e32 v3, v3, v2, vcc                           ; 02060503
	v_cndmask_b32_e32 v4, v4, v5, vcc                           ; 02080b04
	v_cndmask_b32_e32 v0, v0, v6, vcc                           ; 02000d00
	v_cvt_pkrtz_f16_f32_e32 v3, v3, v4                          ; 5e060903
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v7                          ; 5e000f00
	exp mrt0 v3, v3, v0, v0 done compr vm                       ; f8001c0f 80800003
	s_endpgm                                                    ; bf810000
