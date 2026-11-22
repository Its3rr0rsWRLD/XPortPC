# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v9, v0, attr1.x                         ; c8240400
	v_interp_p1_f32_e32 v7, v0, attr0.x                         ; c81c0000
	v_interp_p1_f32_e32 v8, v0, attr0.w                         ; c8200300
	v_interp_p1_f32_e32 v2, v0, attr0.z                         ; c8080200
	v_interp_p1_f32_e32 v3, v0, attr2.x                         ; c80c0800
	v_interp_p1_f32_e32 v4, v0, attr1.w                         ; c8100700
	v_interp_p1_f32_e32 v5, v0, attr0.y                         ; c8140100
	v_interp_p1_f32_e32 v6, v0, attr1.z                         ; c8180600
	v_interp_p1_f32_e32 v10, v0, attr1.y                        ; c8280500
	v_interp_p1_f32_e32 v11, v0, attr2.w                        ; c82c0b00
	v_interp_p1_f32_e32 v12, v0, attr2.y                        ; c8300900
	v_interp_p2_f32_e32 v9, v1, attr1.x                         ; c8250401
	v_interp_p2_f32_e32 v7, v1, attr0.x                         ; c81d0001
	v_interp_p1_f32_e32 v0, v0, attr2.z                         ; c8000a00
	v_interp_p2_f32_e32 v8, v1, attr0.w                         ; c8210301
	v_interp_p2_f32_e32 v2, v1, attr0.z                         ; c8090201
	v_interp_p2_f32_e32 v3, v1, attr2.x                         ; c80d0801
	v_interp_p2_f32_e32 v11, v1, attr2.w                        ; c82d0b01
	v_interp_p2_f32_e32 v12, v1, attr2.y                        ; c8310901
	v_interp_p2_f32_e32 v0, v1, attr2.z                         ; c8010a01
	v_cubema_f32 v13, v12, v0, v11                              ; d547000d 042e010c
	v_cubesc_f32 v14, v12, v0, v11                              ; d545000e 042e010c
	v_cubeid_f32 v18, v12, v0, v11                              ; d5440012 042e010c
	v_cubetc_f32 v15, v12, v0, v11                              ; d546000f 042e010c
	v_rcp_f32_e64 v13, |v13|                                    ; d5aa010d 0000010d
	v_madak_f32 v17, v15, v13, 0x3fc00000                       ; 42221b0f 3fc00000
	v_madak_f32 v16, v14, v13, 0x3fc00000                       ; 42201b0e 3fc00000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v16, v[16:18], s[8:15], s[4:7] dmask:0x1 dim:SQ_RSRC_IMG_CUBE ; f0800118 00221010
	v_interp_p2_f32_e32 v4, v1, attr1.w                         ; c8110701
	v_interp_p2_f32_e32 v5, v1, attr0.y                         ; c8150101
	v_interp_p2_f32_e32 v6, v1, attr1.z                         ; c8190601
	v_interp_p2_f32_e32 v10, v1, attr1.y                        ; c8290501
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v0, v0, v0                                    ; 10000100
	v_mac_f32_e32 v2, v5, v4                                    ; 3e040905
	v_mac_f32_e32 v0, v11, v11                                  ; 3e00170b
	v_mac_f32_e32 v2, v7, v6                                    ; 3e040d07
	v_mac_f32_e32 v0, v12, v12                                  ; 3e00190c
	v_max_f32_e32 v2, 0, v2                                     ; 20040480
	v_sqrt_f32_e32 v0, v0                                       ; 7e006700
	v_madak_f32 v8, v2, v8, 0x3d4ccccd                          ; 42101102 3d4ccccd
	v_madak_f32 v9, v2, v9, 0x3d4ccccd                          ; 42121302 3d4ccccd
	v_fma_mixhi_f16 v19, 1.0, v2, 1.0 op_sel_hi:[0,0,1]         ; cc224013 03ca04f2
	v_madak_f32 v10, v2, v10, 0x3d4ccccd                        ; 42141502 3d4ccccd
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v16, 0x3e19999a, v16                          ; 062020ff 3e19999a
	v_cmp_ge_f32_e32 vcc, v16, v0                               ; 7c0c0110
	v_cndmask_b32_e64 v20, 0.5, 1.0, vcc                        ; d5010014 01a9e4f0
	v_fma_mixlo_f16 v19, v10, v20, neg(0) op_sel_hi:[0,0,1]     ; cc214013 8202290a
	v_fma_mixlo_f16 v21, v8, v20, neg(0) op_sel_hi:[0,0,1]      ; cc214015 82022908
	v_fma_mixhi_f16 v21, v9, v20, neg(0) op_sel_hi:[0,0,1]      ; cc224015 82022909
	exp mrt0 v21, v21, v19, v19 done compr vm                   ; f8001c0f 80801315
	s_endpgm                                                    ; bf810000
