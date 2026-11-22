# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_load_dwordx4 s[16:19], s[2:3], null                       ; f4080401 fa000000
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v2], s[8:15], s[4:7] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00220000 00000002
	s_buffer_load_dwordx2 s[0:1], s[16:19], 0x110               ; f4240008 fa000110
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e64 v3, s1, s0                                    ; d5030003 00000001
	v_sub_f32_e64 v4, s1, s0                                    ; d5040004 00000001
	v_mul_f32_e64 v5, 2.0, s0                                   ; d5080005 000000f4
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v0, v0, -v4, v3                                   ; d5410000 440e0900
	v_rcp_f32_e32 v0, v0                                        ; 7e005500
	v_mad_f32 v5, v5, -v0, 1.0                                  ; d5410005 43ca0105
	v_cvt_pkrtz_f16_f32_e64 v6, v5, 1.0                         ; d52f0006 0001e505
	v_cvt_pkrtz_f16_f32_e32 v5, v5, v5                          ; 5e0a0b05
	exp mrt0 v5, v5, v6, v6 done compr vm                       ; f8001c0f 80800605
	s_endpgm                                                    ; bf810000
