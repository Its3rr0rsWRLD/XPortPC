# Pixel Shader
BB0:
	s_mov_b32 s4, s3                                            ; be840303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x50                       ; f4080401 fa000050
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v2], s[8:15], s[16:19] dmask:0x8 dim:SQ_RSRC_IMG_2D ; f080080a 00820000 00000002
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_gt_f32_e32 vcc, 0.5, v0                               ; 7c0800f0
	s_andn2_b64 exec, s[0:1], vcc                               ; 8afe6a00
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
