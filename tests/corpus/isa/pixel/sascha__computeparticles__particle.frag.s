# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x3                                                ; bfa10003
	s_load_dwordx8 s[8:15], s[2:3], 0x60                        ; f40c0201 fa000060
	s_load_dwordx4 s[4:7], s[2:3], 0xb0                         ; f4080101 fa0000b0
	s_load_dwordx8 s[16:23], s[2:3], null                       ; f40c0401 fa000000
	s_load_dwordx4 s[24:27], s[2:3], 0x50                       ; f4080601 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_mov_b32_e32 v3, 0                                         ; 7e060280
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[3:5], v[2:3], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220302
	v_interp_p1_f32_e32 v6, v0, attr0.y                         ; c8180100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v6, v1, attr0.y                         ; c8190101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	image_sample  v[7:9], [v0, v6], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00c40700 00000006
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v10, v7, v3, neg(0) op_sel_hi:[0,0,1]       ; cc21400a 82020707
	v_fma_mixhi_f16 v10, v8, v4, neg(0) op_sel_hi:[0,0,1]       ; cc22400a 82020908
	v_mul_f32_e32 v9, v9, v5                                    ; 10120b09
	v_cvt_pkrtz_f16_f32_e64 v9, v9, 0                           ; d52f0009 00010109
	exp mrt0 v10, v10, v9, v9 done compr vm                     ; f8001c0f 8080090a
	s_endpgm                                                    ; bf810000
