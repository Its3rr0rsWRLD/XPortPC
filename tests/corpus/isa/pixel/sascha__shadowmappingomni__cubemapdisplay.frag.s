# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s3                                            ; befc0303
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_mul_f32_e32 v3, 0x40400000, v2                            ; 100604ff 40400000
	v_mul_f32_e32 v5, 4.0, v0                                   ; 100a00f6
	v_floor_f32_e32 v3, v3                                      ; 7e064903
	v_floor_f32_e32 v6, v5                                      ; 7e0c4905
	v_cvt_i32_f32_e32 v4, v3                                    ; 7e081103
	v_cvt_i32_f32_e32 v7, v6                                    ; 7e0e1106
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_eq_i32_e32 1, v4                                     ; 7d240881
	s_cbranch_execz BB3                                         ; bf88001f
BB1:
	v_sub_f32_e64 v5, v5, v6 mul:2                              ; d5040005 08020d05
	v_cmp_eq_i32_e32 vcc, 0, v7                                 ; 7d040e80
	v_add_f32_e32 v2, 0xbeaaaaab, v2                            ; 060404ff beaaaaab
	v_cmp_ge_u32_e64 s[4:5], 3, v7                              ; d4c60004 00020e83
	v_add_f32_e32 v5, -1.0, v5                                  ; 060a0af3
	v_cndmask_b32_e64 v1, 0, 1.0, vcc                           ; d5010001 01a9e480
	v_mad_f32 v2, 0x40c00000, v2, -1.0                          ; d5410002 03ce04ff 40c00000
	v_cndmask_b32_e32 v0, 0, v5, vcc                            ; 02000a80
	v_cmp_eq_i32_e32 vcc, 1, v7                                 ; 7d040e81
	v_cndmask_b32_e64 v2, 0, v2, s[4:5]                         ; d5010002 00120480
	v_cndmask_b32_e64 v1, -v1, v5, vcc                          ; d5010001 21aa0b01
	v_cndmask_b32_e64 v0, v0, 1.0, vcc                          ; d5010000 01a9e500
	v_cmp_eq_i32_e32 vcc, 2, v7                                 ; 7d040e82
	v_cndmask_b32_e64 v1, v1, 1.0, vcc                          ; d5010001 01a9e501
	v_cndmask_b32_e64 v0, v0, -v5, vcc                          ; d5010000 41aa0b00
	v_cmp_eq_i32_e32 vcc, 3, v7                                 ; 7d040e83
	v_cndmask_b32_e64 v0, v0, -1.0, vcc                         ; d5010000 01a9e700
	v_cndmask_b32_e64 v1, v1, -v5, vcc                          ; d5010001 41aa0b01
BB3:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	s_cbranch_execz BB12                                        ; bf880021
BB4:
	s_mov_b64 s[4:5], exec                                      ; be84047e
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_eq_i32_e32 1, v7                                     ; 7d240e81
	s_cbranch_execz BB8                                         ; bf880019
BB5:
	v_mad_f32 v3, 0x3eaaaaab, -v3, v2                           ; d5410003 440a06ff 3eaaaaab
	v_cmp_eq_i32_e32 vcc, 0, v4                                 ; 7d040880
	v_cmp_eq_i32_e64 s[6:7], 2, v4                              ; d4820006 00020882
	v_add_f32_e32 v0, 0xbe800000, v0                            ; 060000ff be800000
	v_mad_f32 v3, 0x40c00000, v3, -1.0                          ; d5410003 03ce06ff 40c00000
	v_cndmask_b32_e64 v2, 0, 1.0, vcc                           ; d5010002 01a9e480
	s_or_b64 s[8:9], s[6:7], vcc                                ; 88886a06
	v_mad_f32 v0, 0x41000000, v0, -1.0                          ; d5410000 03ce00ff 41000000
	v_cndmask_b32_e32 v1, 0, v3, vcc                            ; 02020680
	v_cndmask_b32_e64 v2, -v2, 1.0, s[6:7]                      ; d5010002 2019e502
	v_cndmask_b32_e64 v0, 0, v0, s[8:9]                         ; d5010000 00220080
	v_cndmask_b32_e64 v1, v1, -v3, s[6:7]                       ; d5010001 401a0701
	v_swap_b32 v0, v1                                           ; 7e00cb01
BB8:
	s_andn2_b64 exec, s[4:5], exec                              ; 8afe7e04
	v_lshrrev_b64 v[0:1], 0, 0                                  ; d7000000 00010080
	v_mov_b32_e32 v2, 0                                         ; 7e040280
BB12:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_min_f32_e64 v3, |v1|, |v2|                                ; d50f0303 00020501
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_neq_f32_e32 0, v3                                    ; 7c3a0680
	s_cbranch_execz BB16                                        ; bf88001e
BB13:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	v_cubema_f32 v3, v1, v2, v0                                 ; d5470003 04020501
	v_cubesc_f32 v4, v1, v2, v0                                 ; d5450004 04020501
	v_cubetc_f32 v5, v1, v2, v0                                 ; d5460005 04020501
	v_cubeid_f32 v8, v1, v2, v0                                 ; d5440008 04020501
	v_rcp_f32_e64 v3, |v3|                                      ; d5aa0103 00000103
	v_madak_f32 v6, v4, v3, 0x3fc00000                          ; 420c0704 3fc00000
	v_madak_f32 v7, v5, v3, 0x3fc00000                          ; 420e0705 3fc00000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[9:11], v[6:8], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0800718 00220906
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v10, v10, v10                                 ; 1014150a
	v_mac_f32_e32 v10, v11, v11                                 ; 3e14170b
	v_mac_f32_e32 v10, v9, v9                                   ; 3e141309
	v_sqrt_f32_e32 v10, v10                                     ; 7e14670a
	v_mul_f32_e32 v10, 0x3ba3d70a, v10                          ; 101414ff 3ba3d70a
BB16:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_mov_b32_e32 v10, 0x3d4ccccd                               ; 7e1402ff 3d4ccccd
BB18:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cvt_pkrtz_f16_f32_e64 v0, v10, 1.0                        ; d52f0000 0001e50a
	v_cvt_pkrtz_f16_f32_e32 v10, v10, v10                       ; 5e14150a
	exp mrt0 v10, v10, v0, v0 done compr vm                     ; f8001c0f 8080000a
	s_endpgm                                                    ; bf810000
