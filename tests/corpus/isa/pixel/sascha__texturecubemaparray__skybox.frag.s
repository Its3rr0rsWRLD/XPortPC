# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[16:19], s[2:3], 0x70                       ; f4080401 fa000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx2 s[2:3], s[4:7], 0xc0                  ; f4240082 fa0000c0
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.z                         ; c8080200
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.z                         ; c8090201
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_cubema_f32 v4, v3, v0, v2                                 ; d5470004 040a0103
	v_cubesc_f32 v5, v3, v0, v2                                 ; d5450005 040a0103
	v_cubetc_f32 v6, v3, v0, v2                                 ; d5460006 040a0103
	v_cubeid_f32 v3, v3, v0, v2                                 ; d5440003 040a0103
	v_rcp_f32_e64 v4, |v4|                                      ; d5aa0104 00000104
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cvt_f32_i32_e32 v7, s3                                    ; 7e0e0a03
	v_mov_b32_e32 v11, s2                                       ; 7e160202
	v_madmk_f32 v10, v7, 0x41000000, v3                         ; 40140707 41000000
	v_madak_f32 v8, v5, v4, 0x3fc00000                          ; 42100905 3fc00000
	v_madak_f32 v9, v6, v4, 0x3fc00000                          ; 42120906 3fc00000
	image_sample_l v[0:3], v[8:11], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_CUBE ; f0900f18 00820008
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v1                          ; 5e000300
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v3                          ; 5e040702
	exp mrt0 v0, v0, v2, v2 done compr vm                       ; f8001c0f 80800200
	s_endpgm                                                    ; bf810000
