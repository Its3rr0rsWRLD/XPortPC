# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_load_dwordx4 s[16:19], s[2:3], 0x10                       ; f4080401 fa000010
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.z                         ; c8080200
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.z                         ; c8090201
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_cubeid_f32 v9, v3, v0, v2                                 ; d5440009 040a0103
	v_cubema_f32 v4, v3, v0, v2                                 ; d5470004 040a0103
	v_cubesc_f32 v5, v3, v0, v2                                 ; d5450005 040a0103
	v_cubetc_f32 v6, v3, v0, v2                                 ; d5460006 040a0103
	v_rcp_f32_e64 v4, |v4|                                      ; d5aa0104 00000104
	v_madak_f32 v7, v5, v4, 0x3fc00000                          ; 420e0905 3fc00000
	v_madak_f32 v8, v6, v4, 0x3fc00000                          ; 42100906 3fc00000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[10:12], v[7:9], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0800718 00220a07
	s_buffer_load_dwordx2 s[0:1], s[16:19], 0x40                ; f4240008 fa000040
	s_mov_b32 s2, 0x3e19999a                                    ; be8203ff 3e19999a
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_rcp_f32_e32 v13, s1                                       ; 7e1a5401
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v12, s0, v12                                  ; 10181800
	v_mul_f32_e32 v10, s0, v10                                  ; 10141400
	v_mul_f32_e32 v11, s0, v11                                  ; 10161600
	v_madak_f32 v16, s2, v12, 0x3d4ccccd                        ; 42201802 3d4ccccd
	v_mad_f32 v19, s2, v12, 0.5                                 ; d5410013 03c21802
	v_madak_f32 v14, s2, v10, 0x3d4ccccd                        ; 421c1402 3d4ccccd
	v_mad_f32 v17, s2, v10, 0.5                                 ; d5410011 03c21402
	v_madak_f32 v15, s2, v11, 0x3d4ccccd                        ; 421e1602 3d4ccccd
	v_mad_f32 v18, s2, v11, 0.5                                 ; d5410012 03c21602
	v_madak_f32 v19, v12, v19, 0x3d75c290                       ; 4226270c 3d75c290
	v_madak_f32 v12, v12, v16, 0x3b83126f                       ; 4218210c 3b83126f
	v_madak_f32 v17, v10, v17, 0x3d75c290                       ; 4222230a 3d75c290
	v_madak_f32 v10, v10, v14, 0x3b83126f                       ; 42141d0a 3b83126f
	v_madak_f32 v18, v11, v18, 0x3d75c290                       ; 4224250b 3d75c290
	v_madak_f32 v11, v11, v15, 0x3b83126f                       ; 42161f0b 3b83126f
	v_rcp_f32_e32 v19, v19                                      ; 7e265513
	v_rcp_f32_e32 v17, v17                                      ; 7e225511
	v_rcp_f32_e32 v18, v18                                      ; 7e245512
	v_madak_f32 v12, v12, v19, 0xbd888888                       ; 4218270c bd888888
	v_madak_f32 v10, v10, v17, 0xbd888888                       ; 4214230a bd888888
	v_mul_f32_e32 v12, 0x3fb0852e, v12                          ; 101818ff 3fb0852e
	v_madak_f32 v11, v11, v18, 0xbd888888                       ; 4216250b bd888888
	v_mul_f32_e32 v10, 0x3fb0852e, v10                          ; 101414ff 3fb0852e
	v_log_f32_e32 v12, v12                                      ; 7e184f0c
	v_mul_f32_e32 v11, 0x3fb0852e, v11                          ; 101616ff 3fb0852e
	v_log_f32_e32 v10, v10                                      ; 7e144f0a
	v_log_f32_e32 v11, v11                                      ; 7e164f0b
	v_mul_legacy_f32_e32 v12, v12, v13                          ; 0e181b0c
	v_mul_legacy_f32_e32 v10, v10, v13                          ; 0e141b0a
	v_exp_f32_e32 v12, v12                                      ; 7e184b0c
	v_mul_legacy_f32_e32 v11, v11, v13                          ; 0e161b0b
	v_exp_f32_e32 v10, v10                                      ; 7e144b0a
	v_exp_f32_e32 v11, v11                                      ; 7e164b0b
	v_cvt_pkrtz_f16_f32_e64 v12, v12, 1.0                       ; d52f000c 0001e50c
	v_cvt_pkrtz_f16_f32_e32 v10, v10, v11                       ; 5e14170a
	exp mrt0 v10, v10, v12, v12 done compr vm                   ; f8001c0f 80800c0a
	s_endpgm                                                    ; bf810000
