# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x3                                                ; bfa10003
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_load_dwordx8 s[16:23], s[2:3], 0x60                       ; f40c0401 fa000060
	s_load_dwordx4 s[24:27], s[2:3], 0xb0                       ; f4080601 fa0000b0
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_lz  v[3:5], [v0, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f09c070a 00220300 00000002
	image_sample_lz  v[6:8], [v0, v2], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f09c070a 00c40600 00000002
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v3, v3, v6                                    ; 06060d03
	v_add_f32_e32 v4, v4, v7                                    ; 06080f04
	v_add_f32_e32 v5, v5, v8                                    ; 060a1105
	v_add_f32_e32 v9, 1.0, v3                                   ; 061206f2
	v_add_f32_e32 v11, 1.0, v4                                  ; 061608f2
	v_add_f32_e32 v12, 1.0, v5                                  ; 06180af2
	v_rcp_f32_e32 v9, v9                                        ; 7e125509
	v_rcp_f32_e32 v11, v11                                      ; 7e16550b
	v_rcp_f32_e32 v12, v12                                      ; 7e18550c
	v_fma_mixlo_f16 v10, v3, v9, neg(0) op_sel_hi:[0,0,1]       ; cc21400a 82021303
	v_fma_mixhi_f16 v10, v4, v11, neg(0) op_sel_hi:[0,0,1]      ; cc22400a 82021704
	v_mul_f32_e32 v5, v5, v12                                   ; 100a1905
	v_cvt_pkrtz_f16_f32_e64 v5, v5, 1.0                         ; d52f0005 0001e505
	exp mrt0 v10, v10, v5, v5 done compr vm                     ; f8001c0f 8080050a
	s_endpgm                                                    ; bf810000
