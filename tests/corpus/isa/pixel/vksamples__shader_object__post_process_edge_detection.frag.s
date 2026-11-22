# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_mov_b32_e32 v3, 0x100                                     ; 7e0602ff 00000100
	v_mov_b32_e32 v4, 63                                        ; 7e0802bf
	v_mov_b32_e32 v5, 1                                         ; 7e0a0281
	v_mov_b32_e32 v6, 0x3f00                                    ; 7e0c02ff 00003f00
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_o  v[7:9], [v3, v2, v0], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0c0070a 00220703 00000002
	image_sample_o  v[10:12], [v4, v2, v0], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0c0070a 00220a04 00000002
	image_sample  v[13:15], [v2, v0], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220d02 00000000
	image_sample_o  v[16:18], [v5, v2, v0], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0c0070a 00221005 00000002
	image_sample_o  v[19:21], [v6, v2, v0], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0c0070a 00221306 00000002
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v8, v8, v11                                   ; 06101708
	v_add_f32_e32 v7, v7, v10                                   ; 060e1507
	v_add_f32_e32 v9, v9, v12                                   ; 06121909
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v8, -4.0, v14                                 ; 3e101cf7
	v_mac_f32_e32 v7, -4.0, v13                                 ; 3e0e1af7
	v_mac_f32_e32 v9, -4.0, v15                                 ; 3e121ef7
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v8, v8, v17                                   ; 06102308
	v_add_f32_e32 v7, v7, v16                                   ; 060e2107
	v_add_f32_e32 v9, v9, v18                                   ; 06122509
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e64 v8, v8, v20 mul:2                             ; d5030008 08022908
	v_add_f32_e64 v7, v7, v19 mul:2                             ; d5030007 08022707
	v_add_f32_e64 v9, v9, v21 mul:2                             ; d5030009 08022b09
	v_cvt_f16_f32_e32 v22, v7                                   ; 7e2c1507
	v_cvt_f16_f32_sdwa v22, v8 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:DWORD ; 7e2c14f9 00061508
	v_cvt_pkrtz_f16_f32_e64 v9, v9, 1.0                         ; d52f0009 0001e509
	exp mrt0 v22, v22, v9, v9 done compr vm                     ; f8001c0f 80800916
	s_endpgm                                                    ; bf810000
