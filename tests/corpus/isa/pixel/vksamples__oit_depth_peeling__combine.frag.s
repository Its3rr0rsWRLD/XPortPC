# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_mov_b32 m0, s0                                            ; befc0300
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx2 s[0:1], s[4:7], 0x48                  ; f4240002 fa000048
	s_wqm_b64 exec, exec                                        ; befe0a7e
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_mov_b32_e32 v22, v2                                       ; 7e2c0302
	v_lshrrev_b64 v[2:3], 0, 0                                  ; d7000002 00010080
	v_mov_b32_e32 v23, v0                                       ; 7e2e0300
	v_lshrrev_b64 v[0:1], 0, 0x3f800000                         ; d7000000 0001fe80 3f800000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_max_i32 s0, s0, 0                                         ; 84008000
	s_min_i32 s0, s0, 7                                         ; 83008700
	s_max_i32 s1, s1, s0                                        ; 84010001
	s_min_i32 s1, s1, 7                                         ; 83018701
BB1:
	s_cmp_lt_i32 s1, s0                                         ; bf040001
	s_cbranch_scc1 BB5                                          ; bf850015
BB4:
	s_mul_i32 s4, s1, 0x60                                      ; 9304ff01 00000060
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], s4 offset:0x20              ; f40c0201 08000020
	s_load_dwordx4 s[4:7], s[2:3], s4 offset:0x70               ; f4080101 08000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[4:7], v[22:23], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220416
	s_add_u32 s1, s1, -1                                        ; 8001c101
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_sub_f32_e32 v4, v4, v3                                    ; 08080704
	v_sub_f32_e32 v5, v5, v2                                    ; 080a0505
	v_sub_f32_e32 v6, v6, v1                                    ; 080c0306
	v_mac_f32_e32 v3, v7, v4                                    ; 3e060907
	v_mac_f32_e32 v2, v7, v5                                    ; 3e040b07
	v_mac_f32_e32 v1, v7, v6                                    ; 3e020d07
	v_sub_f32_e32 v7, 1.0, v7                                   ; 080e0ef2
	v_mul_f32_e32 v0, v0, v7                                    ; 10000f00
	s_branch BB1                                                ; bf82ffe9
BB5:
	v_cvt_pkrtz_f16_f32_e32 v3, v3, v2                          ; 5e060503
	v_sub_f32_e32 v0, 1.0, v0                                   ; 080000f2
	v_cvt_pkrtz_f16_f32_e32 v1, v1, v0                          ; 5e020101
	exp mrt0 v3, v3, v1, v1 done compr vm                       ; f8001c0f 80800103
	s_endpgm                                                    ; bf810000
