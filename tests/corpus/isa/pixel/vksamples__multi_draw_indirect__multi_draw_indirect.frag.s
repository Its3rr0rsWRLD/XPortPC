# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_mov_f32_e32 v2, p0, attr1.x                        ; c80a0402
	v_mul_lo_u32 v2, 0x60, v2                                   ; d5690002 000204ff 00000060
	v_readfirstlane_b32 s1, v2                                  ; 7e020502
	v_add_nc_u32_e32 v2, 0x50, v2                               ; 4a0404ff 00000050
	v_readfirstlane_b32 s4, v2                                  ; 7e080502
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], s1                          ; f40c0201 02000000
	s_load_dwordx4 s[0:3], s[2:3], s4                           ; f4080001 08000000
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[0:3], [v0, v3], s[8:15], s[0:3] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00020000 00000003
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v4, 0, v0, neg(0) op_sel_hi:[0,0,1]         ; cc214004 820200ff 3fc00000
	v_fma_mixhi_f16 v4, 0, v1, neg(0) op_sel_hi:[0,0,1]         ; cc224004 820202ff 3fc00000
	v_mul_f32_e32 v2, 0x3fc00000, v2                            ; 100404ff 3fc00000
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v3                          ; 5e040702
	exp mrt0 v4, v4, v2, v2 done compr vm                       ; f8001c0f 80800204
	s_endpgm                                                    ; bf810000
