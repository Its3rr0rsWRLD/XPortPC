# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x3                                                ; bfa10003
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x50                       ; f4080401 fa000050
	s_load_dwordx8 s[24:31], s[2:3], 0x60                       ; f40c0601 fa000060
	s_load_dwordx4 s[20:23], s[2:3], 0xb0                       ; f4080501 fa0000b0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v3, v2], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00820403 00000002
	image_sample  v[8:11], [v3, v2], s[24:31], s[20:23] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00a60803 00000002
	v_interp_p1_f32_e32 v14, v0, attr1.x                        ; c8380400
	v_interp_p1_f32_e32 v12, v0, attr0.w                        ; c8300300
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v14, v1, attr1.x                        ; c8390401
	v_interp_p2_f32_e32 v12, v1, attr0.w                        ; c8310301
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_cvt_pk_u16_u32 v16, s0, 0                                 ; d76a0010 00010000
	v_mul_f32_e32 v13, v12, v12                                 ; 101a190c
	v_mac_f32_e32 v13, v14, v14                                 ; 3e1a1d0e
	v_mac_f32_e32 v13, v0, v0                                   ; 3e1a0100
	v_rsq_f32_e32 v13, v13                                      ; 7e1a5d0d
	v_fma_mixlo_f16 v15, v0, v13, neg(0) op_sel_hi:[0,0,1]      ; cc21400f 82021b00
	v_mul_f32_e32 v14, v14, v13                                 ; 101c1b0e
	v_fma_mixhi_f16 v15, v12, v13, neg(0) op_sel_hi:[0,0,1]     ; cc22400f 82021b0c
	v_cvt_pkrtz_f16_f32_e64 v14, v14, 1.0                       ; d52f000e 0001e50e
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v7                          ; 5e0c0f06
	v_cvt_pkrtz_f16_f32_e32 v4, v4, v5                          ; 5e080b04
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v10, v10, v11                       ; 5e14170a
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v9                          ; 5e101308
	exp mrt0 v4, v4, v6, v6 compr                               ; f800040f 80800604
	exp mrt1 v8, v8, v10, v10 compr                             ; f800041f 80800a08
	exp mrt2 v15, v15, v14, v14 compr                           ; f800042f 80800e0f
	exp mrt3 v16, v16, off, off done compr vm                   ; f8001c33 80808010
	s_endpgm                                                    ; bf810000
