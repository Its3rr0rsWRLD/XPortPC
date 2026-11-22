# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v3, v0, attr0.w                         ; c80c0300
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v3, v1, attr0.w                         ; c80d0301
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v3, v2], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220403 00000002
	v_interp_p1_f32_e32 v11, v0, attr0.x                        ; c82c0000
	v_interp_p1_f32_e32 v8, v0, attr0.y                         ; c8200100
	v_interp_p1_f32_e32 v10, v0, attr0.z                        ; c8280200
	v_interp_p1_f32_e32 v12, v0, attr1.z                        ; c8300600
	v_interp_p1_f32_e32 v14, v0, attr1.w                        ; c8380700
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v11, v1, attr0.x                        ; c82d0001
	v_interp_p2_f32_e32 v8, v1, attr0.y                         ; c8210101
	v_interp_p2_f32_e32 v10, v1, attr0.z                        ; c8290201
	v_interp_p2_f32_e32 v12, v1, attr1.z                        ; c8310601
	v_interp_p2_f32_e32 v14, v1, attr1.w                        ; c8390701
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mul_f32_e32 v9, v8, v8                                    ; 10121108
	v_mul_f32_e32 v13, v12, v12                                 ; 101a190c
	v_mac_f32_e32 v9, v10, v10                                  ; 3e12150a
	v_mac_f32_e32 v13, v14, v14                                 ; 3e1a1d0e
	v_mac_f32_e32 v9, v11, v11                                  ; 3e12170b
	v_mac_f32_e32 v13, v0, v0                                   ; 3e1a0100
	v_rsq_f32_e32 v9, v9                                        ; 7e125d09
	v_rsq_f32_e32 v13, v13                                      ; 7e1a5d0d
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v8, v8, v9                                    ; 10101308
	v_mul_f32_e32 v10, v10, v9                                  ; 1014130a
	v_mul_f32_e32 v14, v14, v13                                 ; 101c1b0e
	v_mul_f32_e32 v0, v0, v13                                   ; 10001b00
	v_mul_f32_e32 v12, v12, v13                                 ; 10181b0c
	v_mul_f32_e32 v10, v10, v14                                 ; 10141d0a
	v_mac_f32_e32 v10, v8, v12                                  ; 3e141908
	v_mac_f32_e32 v10, v11, v0                                  ; 3e14010b
	v_max_f32_e32 v10, 0.5, v10                                 ; 201414f0
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v15, v4, v10, neg(0) op_sel_hi:[0,0,1]      ; cc21400f 82021504
	v_mul_f32_e32 v6, v6, v10                                   ; 100c1506
	v_fma_mixhi_f16 v15, v5, v10, neg(0) op_sel_hi:[0,0,1]      ; cc22400f 82021505
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v7                          ; 5e0c0f06
	exp mrt0 v15, v15, v6, v6 done compr vm                     ; f8001c0f 8080060f
	s_endpgm                                                    ; bf810000
