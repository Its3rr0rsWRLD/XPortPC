# Pixel Shader
BB0:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x80                        ; f40c0201 fa000080
	s_load_dwordx4 s[0:3], s[2:3], 0xd0                         ; f4080001 fa0000d0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	v_mov_b32_e32 v0, 0x7fc00000                                ; 7e0002ff 7fc00000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[0:3], [v0, v0], s[8:15], s[0:3] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00020000 00000000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v1                          ; 5e000300
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v3                          ; 5e040702
	exp mrt0 v0, v0, v2, v2 done compr vm                       ; f8001c0f 80800200
	s_endpgm                                                    ; bf810000
