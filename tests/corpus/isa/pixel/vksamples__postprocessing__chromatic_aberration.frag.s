# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[16:19], s[2:3], 0x70                       ; f4080401 fa000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s1, s[4:7], null                        ; f4200042 fa000000
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_add_f32_e32 v3, -0.5, v2                                  ; 060604f1
	v_add_f32_e32 v4, -0.5, v0                                  ; 060800f1
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v3, s1, v3                                    ; 10060601
	v_mul_f32_e32 v4, s1, v4                                    ; 10080801
	v_mad_f32 v6, 0x3bc49ba6, -v3, v2                           ; d5410006 440a06ff 3bc49ba6
	v_madmk_f32 v8, v3, 0x3b03126f, v2                          ; 40100503 3b03126f
	v_mad_f32 v2, 0x3b83126f, -v3, v2                           ; d5410002 440a06ff 3b83126f
	v_mad_f32 v7, 0x3bc49ba6, -v4, v0                           ; d5410007 440208ff 3bc49ba6
	v_madmk_f32 v9, v4, 0x3b03126f, v0                          ; 40120104 3b03126f
	v_mad_f32 v3, 0x3b83126f, -v4, v0                           ; d5410003 440208ff 3b83126f
	s_clause 0x2                                                ; bfa10002
	image_sample v6, v[6:7], s[8:15], s[16:19] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f0800108 00820606
	image_sample v8, v[8:9], s[8:15], s[16:19] dmask:0x2 dim:SQ_RSRC_IMG_2D ; f0800208 00820808
	image_sample v2, v[2:3], s[8:15], s[16:19] dmask:0x4 dim:SQ_RSRC_IMG_2D ; f0800408 00820202
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v8                          ; 5e0c1106
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e64 v2, v2, 1.0                         ; d52f0002 0001e502
	exp mrt0 v6, v6, v2, v2 done compr vm                       ; f8001c0f 80800206
	s_endpgm                                                    ; bf810000
