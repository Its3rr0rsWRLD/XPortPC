# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s2                                            ; befc0302
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_p1_f32_e32 v5, v0, attr0.w                         ; c8140300
	v_interp_p1_f32_e32 v6, v0, attr1.y                         ; c8180500
	v_interp_p1_f32_e32 v7, v0, attr0.x                         ; c81c0000
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	v_interp_p2_f32_e32 v5, v1, attr0.w                         ; c8150301
	v_interp_p2_f32_e32 v6, v1, attr1.y                         ; c8190501
	v_interp_p2_f32_e32 v7, v1, attr0.x                         ; c81d0001
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_rcp_f32_e32 v4, v3                                        ; 7e085503
	v_mul_f32_e32 v4, v2, v4                                    ; 10080902
	v_mad_f32 v6, v4, -v6, v0                                   ; d5410006 44020d04
	v_mad_f32 v5, v4, -v5, v7                                   ; d5410005 441e0b04
	v_mad_f32 v3, v4, -v3, v2                                   ; d5410003 440a0704
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 -1.0, v4                                  ; 7c2208f3
	s_cbranch_execz BB4                                         ; bf880033
BB1:
	v_subrev_f32_dpp v0, v5, v5 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a000afa ff0c0005
	v_subrev_f32_dpp v2, v6, v6 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 0a040cfa ff0c0006
	v_add_f32_e32 v8, -0.5, v5                                  ; 06100af1
	v_add_f32_e32 v10, -0.5, v6                                 ; 06140cf1
	v_interp_mov_f32_e32 v11, p0, attr2.x                       ; c82e0802
	v_interp_mov_f32_e32 v12, p0, attr2.y                       ; c8320902
	v_interp_mov_f32_e32 v13, p0, attr1.w                       ; c8360702
	v_interp_mov_f32_e32 v14, p0, attr1.z                       ; c83a0602
	v_mov_b32_dpp v1, v0 quad_perm:[2,2,2,2] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e0202fa ff0caa00
	v_mov_b32_dpp v4, v2 quad_perm:[2,2,2,2] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 7e0802fa ff0caa02
	v_fract_f32_e32 v8, v8                                      ; 7e104108
	v_fract_f32_e32 v10, v10                                    ; 7e14410a
	v_mac_f32_e32 v12, v11, v6                                  ; 3e180d0b
	v_add_f32_dpp v0, |v0|, |v1| quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 060002fa ffac5500
	v_add_f32_dpp v2, |v2|, |v4| quad_perm:[1,1,1,1] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1 ; 060408fa ffac5502
	v_add_f32_e32 v8, -0.5, v8                                  ; 061010f1
	v_add_f32_e32 v10, -0.5, v10                                ; 061414f1
	v_mac_f32_e32 v12, v13, v3                                  ; 3e18070d
	v_rcp_f32_e32 v7, v0                                        ; 7e0e5500
	v_add_f32_e64 v0, v0, 0 clamp                               ; d5038000 00010100
	v_rcp_f32_e32 v9, v2                                        ; 7e125502
	v_add_f32_e64 v2, v2, 0 clamp                               ; d5038002 00010102
	v_mac_f32_e32 v12, v14, v5                                  ; 3e180b0e
	v_cmp_lt_f32_e64 s[2:3], |v5|, v0                           ; d4010102 00020105
	v_mov_b32_e32 v0, 0.5                                       ; 7e0002f0
	v_mul_f32_e64 v8, |v8|, v7                                  ; d5080108 00020f08
	v_mad_f32 v12, 0x40c00000, v12, -0.5                        ; d541000c 03c618ff 40c00000
	v_cndmask_b32_e64 v15, 0.5, 1.0, s[2:3]                     ; d501000f 0009e4f0
	v_cmp_lt_f32_e64 s[2:3], |v6|, v2                           ; d4010102 00020506
	v_mul_f32_e64 v10, |v10|, v9                                ; d508010a 0002130a
	v_cndmask_b32_e64 v16, 0.5, 1.0, s[2:3]                     ; d5010010 0009e4f0
	v_min3_f32 v8, v8, v10, 1.0                                 ; d5510008 03ca1508
	v_sub_f32_e32 v8, 1.0, v8                                   ; 081010f2
	v_mul_f32_e32 v8, v8, v12                                   ; 10101908
BB4:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_mov_b32_e32 v8, 0                                         ; 7e100280
	v_lshrrev_b64 v[15:16], 0, 0                                ; d700000f 00010080
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v8                          ; 5e001100
	v_cvt_pkrtz_f16_f32_e32 v16, v16, v15                       ; 5e201f10
	exp mrt0 v16, v16, v0, v0 done compr vm                     ; f8001c0f 80800010
	s_endpgm                                                    ; bf810000
