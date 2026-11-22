# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx4 s[4:7], s[2:3], 0x40                         ; f4080101 fa000040
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx2 s[4:5], s[4:7], 0x80                  ; f4240102 fa000080
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_lshl_b32 s5, s5, 4                                        ; 8f058405
	s_load_dwordx4 s[16:19], s[2:3], s5 offset:0x50             ; f4080401 0a000050
	s_mov_b32 m0, s0                                            ; befc0300
	v_mov_b32_e32 v3, s4                                        ; 7e060204
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_b  v[4:6], [v3, v0, v2], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f094070a 00820403 00000200
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e64 v6, v6, 1.0                         ; d52f0006 0001e506
	v_cvt_pkrtz_f16_f32_e32 v4, v4, v5                          ; 5e080b04
	exp mrt0 v4, v4, v6, v6 done compr vm                       ; f8001c0f 80800604
	s_endpgm                                                    ; bf810000
