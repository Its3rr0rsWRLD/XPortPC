# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x50                       ; f4080401 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[3:5], [v0, v2], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00820300 00000002
	v_mul_f32_e64 v6, 0x3e2aaaab, s0                            ; d5080006 000000ff 3e2aaaab
	v_floor_f32_e32 v6, v6                                      ; 7e0c4906
	v_mul_f32_e32 v6, 0x43b40000, v6                            ; 100c0cff 43b40000
	v_mad_f32 v6, s0, 0x42700000, -v6                           ; d5410006 8419fe00 42700000
	v_mul_f32_e32 v7, 0x3c888889, v6                            ; 100e0cff 3c888889
	v_mul_f32_e32 v6, 0x3c088889, v6                            ; 100c0cff 3c088889
	v_add_f32_e32 v8, -1.0, v7                                  ; 06100ef3
	v_cmp_ngt_f32_e32 vcc, 1.0, v7                              ; 7c160ef2
	v_floor_f32_e64 v6, v6 mul:2                                ; d5a40006 08000106
	v_sub_f32_e32 v8, v8, v6                                    ; 08100d08
	v_sub_f32_e64 v8, 1.0, |v8|                                 ; d5040208 000210f2
	s_cbranch_vccz BB5                                          ; bf860018
BB1:
	v_cmp_ngt_f32_e32 vcc, 2.0, v7                              ; 7c160ef4
	s_cbranch_vccz BB3                                          ; bf860012
BB2:
	v_cmp_gt_f32_e32 vcc, 0x40a00000, v7                        ; 7c080eff 40a00000
	v_cmp_gt_f32_e64 s[0:1], 4.0, v7                            ; d4040000 00020ef6
	v_cndmask_b32_e32 v0, 1.0, v8, vcc                          ; 020010f2
	v_cndmask_b32_e64 v1, 0, v8, s[0:1]                         ; d5010001 00021080
	v_cndmask_b32_e64 v0, v0, 0, s[0:1]                         ; d5010000 00010100
	v_cmp_gt_f32_e64 s[0:1], 0x40400000, v7                     ; d4040000 00020eff 40400000
	v_cndmask_b32_e64 v1, v1, 1.0, s[0:1]                       ; d5010001 0001e501
	s_andn2_b64 s[0:1], vcc, s[0:1]                             ; 8a80006a
	v_cndmask_b32_e64 v8, v8, 1.0, s[0:1]                       ; d5010008 0001e508
	s_branch BB6                                                ; bf820007
BB3:
	v_mov_b32_e32 v0, v8                                        ; 7e000308
	v_mov_b32_e32 v1, 1.0                                       ; 7e0202f2
	v_mov_b32_e32 v8, 0                                         ; 7e100280
	s_branch BB6                                                ; bf820003
BB5:
	v_mov_b32_e32 v0, 1.0                                       ; 7e0002f2
	v_mov_b32_e32 v1, v8                                        ; 7e020308
	v_mov_b32_e32 v8, 0                                         ; 7e100280
BB6:
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v0, v3, v0, neg(0) op_sel_hi:[0,0,1]        ; cc214000 82020103
	v_fma_mixhi_f16 v0, v4, v1, neg(0) op_sel_hi:[0,0,1]        ; cc224000 82020304
	v_mul_f32_e32 v5, v5, v8                                    ; 100a1105
	v_cvt_pkrtz_f16_f32_e64 v5, v5, 1.0                         ; d52f0005 0001e505
	exp mrt0 v0, v0, v5, v5 done compr vm                       ; f8001c0f 80800500
	s_endpgm                                                    ; bf810000
