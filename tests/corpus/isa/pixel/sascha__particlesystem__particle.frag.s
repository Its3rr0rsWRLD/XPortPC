# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s3                                            ; befc0303
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v4, v0, attr0.x                         ; c8100000
	v_interp_p1_f32_e32 v5, v0, attr2.x                         ; c8140800
	v_interp_p1_f32_e32 v7, v0, attr0.y                         ; c81c0100
	v_interp_mov_f32_e32 v10, p0, attr3.x                       ; c82a0c02
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p2_f32_e32 v4, v1, attr0.x                         ; c8110001
	v_interp_p2_f32_e32 v5, v1, attr2.x                         ; c8150801
	v_interp_p2_f32_e32 v7, v1, attr0.y                         ; c81d0101
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_sub_f32_e32 v3, 2.0, v2                                   ; 080604f4
	v_cmp_ge_f32_e32 vcc, 1.0, v2                               ; 7c0c04f2
	v_add_f32_e32 v4, -0.5, v4                                  ; 060808f1
	v_cos_f32_e32 v6, v5                                        ; 7e0c6d05
	v_sin_f32_e32 v5, v5                                        ; 7e0a6b05
	v_add_f32_e32 v7, -0.5, v7                                  ; 060e0ef1
	v_cndmask_b32_e32 v3, v3, v2, vcc                           ; 02060503
	v_mad_f32 v8, v6, v4, 0.5                                   ; d5410008 03c20906
	v_mad_f32 v6, v6, v7, 0.5                                   ; d5410006 03c20f06
	v_mac_f32_e32 v8, v5, v7                                    ; 3e100f05
	v_mad_f32 v9, v5, -v4, v6                                   ; d5410009 441a0905
	v_cmpx_eq_i32_e32 0, v10                                    ; 7d241480
	s_cbranch_execz BB3                                         ; bf88000b
BB1:
	s_mov_b32 s4, s2                                            ; be840302
	s_movk_i32 s5, 0x8000                                       ; b0058000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[4:5], 0x80                        ; f40c0202 fa000080
	s_load_dwordx4 s[4:7], s[4:5], 0xd0                         ; f4080102 fa0000d0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[4:6], v[8:9], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220408
	v_mov_b32_e32 v7, 0                                         ; 7e0e0280
BB3:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	s_cbranch_execz BB6                                         ; bf88000b
BB4:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[4:7], v[8:9], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220408
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v7, v7, v3                                    ; 100e0707
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v8, v0, attr1.y                         ; c8200500
	v_interp_p1_f32_e32 v0, v0, attr1.z                         ; c8000600
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v8, v1, attr1.y                         ; c8210501
	v_interp_p2_f32_e32 v0, v1, attr1.z                         ; c8010601
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v4, v4, v2                                    ; 10080504
	v_mul_f32_e32 v5, v5, v8                                    ; 100a1105
	v_mul_f32_e32 v6, v6, v0                                    ; 100c0106
	v_fma_mixlo_f16 v9, v4, v3, neg(0) op_sel_hi:[0,0,1]        ; cc214009 82020704
	v_fma_mixhi_f16 v9, v5, v3, neg(0) op_sel_hi:[0,0,1]        ; cc224009 82020705
	v_mul_f32_e32 v6, v6, v3                                    ; 100c0706
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v7                          ; 5e0c0f06
	exp mrt0 v9, v9, v6, v6 done compr vm                       ; f8001c0f 80800609
	s_endpgm                                                    ; bf810000
