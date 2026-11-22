# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_mov_f32_e32 v3, p0, attr0.z                        ; c80e0202
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_rndne_f32_e32 v3, v3                                      ; 7e064703
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v2, [v2, v0, v3], s[8:15], s[4:7] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f080012a 00220202 00000300
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e64 v4, v2, 1.0                         ; d52f0004 0001e502
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v2                          ; 5e040502
	exp mrt0 v2, v2, v4, v4 done compr vm                       ; f8001c0f 80800402
	s_endpgm                                                    ; bf810000
