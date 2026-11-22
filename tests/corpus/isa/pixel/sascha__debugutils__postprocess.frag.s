# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_add_f32_e32 v4, 0xbc23d70a, v2                            ; 060804ff bc23d70a
	v_add_f32_e32 v3, 0x3c23d70a, v2                            ; 060604ff 3c23d70a
	v_add_f32_e32 v5, 0xbc23d70a, v0                            ; 060a00ff bc23d70a
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[6:8], v[4:5], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220604
	image_sample  v[9:11], [v2, v5], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220902 00000005
	image_sample  v[12:14], [v3, v5], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220c03 00000005
	image_sample  v[15:17], [v4, v0], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220f04 00000000
	image_sample  v[18:20], [v2, v0], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00221202 00000000
	image_sample  v[21:23], [v3, v0], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00221503 00000000
	v_add_f32_e32 v5, 0x3c23d70a, v0                            ; 060a00ff 3c23d70a
	image_sample v[24:26], v[4:5], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00221804
	image_sample  v[0:2], [v2, v5], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220002 00000005
	image_sample  v[3:5], [v3, v5], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220303 00000005
	s_waitcnt vmcnt(7)                                          ; bf8c3f77
	v_mac_f32_e32 v7, 2.0, v10                                  ; 3e0e14f4
	v_mac_f32_e32 v6, 2.0, v9                                   ; 3e0c12f4
	v_mac_f32_e32 v8, 2.0, v11                                  ; 3e1016f4
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v7, v7, v13                                   ; 060e1b07
	v_add_f32_e32 v6, v6, v12                                   ; 060c1906
	v_add_f32_e32 v8, v8, v14                                   ; 06101d08
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mac_f32_e32 v7, 2.0, v16                                  ; 3e0e20f4
	v_mac_f32_e32 v6, 2.0, v15                                  ; 3e0c1ef4
	v_mac_f32_e32 v8, 2.0, v17                                  ; 3e1022f4
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v7, 4.0, v19                                  ; 3e0e26f6
	v_mac_f32_e32 v6, 4.0, v18                                  ; 3e0c24f6
	v_mac_f32_e32 v8, 4.0, v20                                  ; 3e1028f6
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mac_f32_e32 v7, 2.0, v22                                  ; 3e0e2cf4
	v_mac_f32_e32 v6, 2.0, v21                                  ; 3e0c2af4
	v_mac_f32_e32 v8, 2.0, v23                                  ; 3e102ef4
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v7, v7, v25                                   ; 060e3307
	v_add_f32_e32 v6, v6, v24                                   ; 060c3106
	v_add_f32_e32 v8, v8, v26                                   ; 06103508
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v7, 2.0, v1                                   ; 3e0e02f4
	v_mac_f32_e32 v6, 2.0, v0                                   ; 3e0c00f4
	v_mac_f32_e32 v8, 2.0, v2                                   ; 3e1004f4
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v7, v7, v4                                    ; 060e0907
	v_add_f32_e32 v6, v6, v3                                    ; 060c0706
	v_add_f32_e32 v8, v8, v5                                    ; 06100b08
	v_fma_mixlo_f16 v6, 0, v6, neg(0) op_sel_hi:[0,0,1]         ; cc214006 82020cff 3d800000
	v_fma_mixhi_f16 v6, 0, v7, neg(0) op_sel_hi:[0,0,1]         ; cc224006 82020eff 3d800000
	v_mul_f32_e32 v8, 0x3d800000, v8                            ; 101010ff 3d800000
	v_cvt_pkrtz_f16_f32_e64 v8, v8, 1.0                         ; d52f0008 0001e508
	exp mrt0 v6, v6, v8, v8 done compr vm                       ; f8001c0f 80800806
	s_endpgm                                                    ; bf810000
