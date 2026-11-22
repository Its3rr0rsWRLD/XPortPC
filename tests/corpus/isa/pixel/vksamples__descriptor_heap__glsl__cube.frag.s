# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_lshl_b32 s4, s4, 4                                        ; 8f048404
	s_load_dwordx4 s[8:11], s[0:1], s4                          ; f4080200 08000000
	s_mov_b32 m0, s5                                            ; befc0305
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_mov_b64 s[6:7], exec                                      ; be86047e
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_mov_f32_e32 v3, p0, attr0.z                        ; c80e0202
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_mov_b32_e32 v22, v2                                       ; 7e2c0302
	v_mov_b32_e32 v23, v0                                       ; 7e2e0300
BB1:
	v_readfirstlane_b32 s4, v3                                  ; 7e080503
	v_cmpx_eq_i32_e32 s4, v3                                    ; 7d240604
	s_cbranch_execz BB9                                         ; bf880006
BB2:
	s_lshl_b32 s4, s4, 6                                        ; 8f048604
	s_load_dwordx8 s[16:23], s[2:3], s4                         ; f40c0401 08000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[0:3], v[22:23], s[16:23], s[8:11] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00440016
BB9:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_andn2_wrexec_b64 s[6:7], s[6:7]                           ; be863a06
	s_cbranch_scc1 BB1                                          ; bf85fff4
BB10:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v1                          ; 5e000300
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v3                          ; 5e040702
	exp mrt0 v0, v0, v2, v2 done compr vm                       ; f8001c0f 80800200
	s_endpgm                                                    ; bf810000
