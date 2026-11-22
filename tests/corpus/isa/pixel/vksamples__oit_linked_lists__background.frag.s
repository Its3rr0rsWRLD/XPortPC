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
	image_sample  v[0:3], [v0, v2], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220000 00000002
	s_buffer_load_dword s1, s[16:19], 0x80                      ; f4200048 fa000080
	s_waitcnt vmcnt(0) lgkmcnt(0)                               ; bf8c0070
	v_fma_mixlo_f16 v4, s1, v0, neg(0) op_sel_hi:[0,0,1]        ; cc214004 82020001
	v_fma_mixhi_f16 v4, s1, v1, neg(0) op_sel_hi:[0,0,1]        ; cc224004 82020201
	v_fma_mixlo_f16 v5, s1, v2, neg(0) op_sel_hi:[0,0,1]        ; cc214005 82020401
	v_fma_mixhi_f16 v5, s1, v3, neg(0) op_sel_hi:[0,0,1]        ; cc224005 82020601
	exp mrt0 v4, v4, v5, v5 done compr vm                       ; f8001c0f 80800504
	s_endpgm                                                    ; bf810000
