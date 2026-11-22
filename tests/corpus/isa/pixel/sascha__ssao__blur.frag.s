# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_mov_b32 m0, s0                                            ; befc0300
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[0:3], s[2:3], 0x50                         ; f4080001 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_bfe_u32 s4, s9, 0x2001e                                   ; 9384ff09 0002001e
	s_add_u32 s4, s4, 1                                         ; 80048104
	s_and_b32 s5, s10, 0x3fff                                   ; 8705ff0a 00003fff
	s_lshl2_add_u32 s5, s5, s4                                  ; 97850405
	s_bfe_u32 s19, s11, 0x4000c                                 ; 9393ff0b 0004000c
	s_lshr_b32 s5, s5, s19                                      ; 90051305
	s_bfe_u32 s18, s10, 0x10000e                                ; 9392ff0a 0010000e
	s_add_u32 s18, s18, 1                                       ; 80128112
	s_lshr_b32 s18, s18, s19                                    ; 90121312
	s_max_u32 s5, s5, 1                                         ; 84858105
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_cselect_b32 s5, 0, s5                                     ; 85050580
	s_max_u32 s18, s18, 1                                       ; 84928112
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	v_cvt_f32_i32_e32 v3, s5                                    ; 7e060a05
	s_cselect_b32 s18, 0, s18                                   ; 85121280
	v_cvt_f32_i32_e32 v5, s18                                   ; 7e0a0a12
	v_rcp_f32_e32 v3, v3                                        ; 7e065503
	v_rcp_f32_e32 v5, v5                                        ; 7e0a5505
	v_add_f32_e32 v10, v2, v3                                   ; 06140702
	v_sub_f32_e32 v9, v2, v3                                    ; 08120702
	v_mad_f32 v4, -2.0, v3, v2                                  ; d5410004 040a06f5
	v_add_f32_e32 v8, v0, v5                                    ; 06100b00
	v_mad_f32 v6, -2.0, v5, v0                                  ; d5410006 04020af5
	v_sub_f32_e32 v7, v0, v5                                    ; 080e0b00
	v_mad_f32 v5, 2.0, v5, v0                                   ; d5410005 04020af4
	image_sample  v11, [v4, v6], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020b04 00000006
	image_sample  v12, [v4, v7], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020c04 00000007
	image_sample  v13, [v4, v0], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020d04 00000000
	image_sample  v14, [v4, v8], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020e04 00000008
	image_sample v4, v[4:5], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f0800108 00020404
	image_sample  v15, [v9, v6], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020f09 00000006
	image_sample  v16, [v9, v7], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021009 00000007
	image_sample  v17, [v9, v0], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021109 00000000
	image_sample  v18, [v9, v8], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021209 00000008
	image_sample  v9, [v9, v5], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020909 00000005
	image_sample  v19, [v2, v6], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021302 00000006
	image_sample  v20, [v2, v7], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021402 00000007
	image_sample  v21, [v2, v0], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021502 00000000
	image_sample  v22, [v2, v8], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021602 00000008
	image_sample  v23, [v2, v5], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021702 00000005
	image_sample  v24, [v10, v6], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 0002180a 00000006
	image_sample  v25, [v10, v7], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 0002190a 00000007
	image_sample  v26, [v10, v0], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021a0a 00000000
	image_sample  v27, [v10, v8], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00021b0a 00000008
	image_sample  v10, [v10, v5], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020a0a 00000005
	v_mac_f32_e32 v2, 2.0, v3                                   ; 3e0406f4
	image_sample  v6, [v2, v6], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020602 00000006
	image_sample  v7, [v2, v7], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020702 00000007
	image_sample  v0, [v2, v0], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020002 00000000
	image_sample  v8, [v2, v8], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020802 00000008
	image_sample  v2, [v2, v5], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020202 00000005
	s_waitcnt vmcnt(23)                                         ; bf8c7f77
	v_add_f32_e32 v11, v11, v12                                 ; 0616190b
	s_waitcnt vmcnt(22)                                         ; bf8c7f76
	v_add_f32_e32 v11, v11, v13                                 ; 06161b0b
	s_waitcnt vmcnt(21)                                         ; bf8c7f75
	v_add_f32_e32 v11, v11, v14                                 ; 06161d0b
	s_waitcnt vmcnt(20)                                         ; bf8c7f74
	v_add_f32_e32 v11, v11, v4                                  ; 0616090b
	s_waitcnt vmcnt(19)                                         ; bf8c7f73
	v_add_f32_e32 v11, v11, v15                                 ; 06161f0b
	s_waitcnt vmcnt(18)                                         ; bf8c7f72
	v_add_f32_e32 v11, v11, v16                                 ; 0616210b
	s_waitcnt vmcnt(17)                                         ; bf8c7f71
	v_add_f32_e32 v11, v11, v17                                 ; 0616230b
	s_waitcnt vmcnt(16)                                         ; bf8c7f70
	v_add_f32_e32 v11, v11, v18                                 ; 0616250b
	s_waitcnt vmcnt(15)                                         ; bf8c3f7f
	v_add_f32_e32 v11, v11, v9                                  ; 0616130b
	s_waitcnt vmcnt(14)                                         ; bf8c3f7e
	v_add_f32_e32 v11, v11, v19                                 ; 0616270b
	s_waitcnt vmcnt(13)                                         ; bf8c3f7d
	v_add_f32_e32 v11, v11, v20                                 ; 0616290b
	s_waitcnt vmcnt(12)                                         ; bf8c3f7c
	v_add_f32_e32 v11, v11, v21                                 ; 06162b0b
	s_waitcnt vmcnt(11)                                         ; bf8c3f7b
	v_add_f32_e32 v11, v11, v22                                 ; 06162d0b
	s_waitcnt vmcnt(10)                                         ; bf8c3f7a
	v_add_f32_e32 v11, v11, v23                                 ; 06162f0b
	s_waitcnt vmcnt(9)                                          ; bf8c3f79
	v_add_f32_e32 v11, v11, v24                                 ; 0616310b
	s_waitcnt vmcnt(8)                                          ; bf8c3f78
	v_add_f32_e32 v11, v11, v25                                 ; 0616330b
	s_waitcnt vmcnt(7)                                          ; bf8c3f77
	v_add_f32_e32 v11, v11, v26                                 ; 0616350b
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v11, v11, v27                                 ; 0616370b
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v11, v11, v10                                 ; 0616150b
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v11, v11, v6                                  ; 06160d0b
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v11, v11, v7                                  ; 06160f0b
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v11, v11, v0                                  ; 0616010b
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v11, v11, v8                                  ; 0616110b
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v11, v11, v2                                  ; 0616050b
	v_mul_f32_e32 v11, 0x3d23d70a, v11                          ; 101616ff 3d23d70a
	v_cvt_pkrtz_f16_f32_e64 v11, v11, 0                         ; d52f000b 0001010b
	exp mrt0 v11, v11, off, off done compr vm                   ; f8001c03 8080800b
	s_endpgm                                                    ; bf810000
