# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_lz  v[0:3], [v0, v2], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f09c0f0a 00220000 00000002
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v4, 0x3f19999a, v1                            ; 100802ff 3f19999a
	v_sub_f32_e32 v5, 1.0, v3                                   ; 080a06f2
	v_madmk_f32 v4, v2, 0x3dcccccd, v4                          ; 40080902 3dcccccd
	v_madmk_f32 v4, v0, 0x3e99999a, v4                          ; 40080900 3e99999a
	v_mul_f32_e32 v4, v4, v5                                    ; 10080b04
	v_fma_mixlo_f16 v6, v0, v3, v4                              ; cc210006 04120700
	v_fma_mixhi_f16 v6, v1, v3, v4                              ; cc220006 04120701
	v_mac_f32_e32 v4, v2, v3                                    ; 3e080702
	v_cvt_pkrtz_f16_f32_e64 v4, v4, 1.0                         ; d52f0004 0001e504
	exp mrt0 v6, v6, v4, v4 done compr vm                       ; f8001c0f 80800406
	s_endpgm                                                    ; bf810000
