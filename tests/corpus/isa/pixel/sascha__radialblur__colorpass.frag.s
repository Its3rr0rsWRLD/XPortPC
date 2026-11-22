# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s3                                            ; befc0303
	v_mov_b32_e32 v23, 0                                        ; 7e2e0280
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_mov_f32_e32 v5, p0, attr0.w                        ; c8160302
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mov_b32_e32 v22, v5                                       ; 7e2c0305
	v_max3_f32 v4, v2, v3, v0                                   ; d5540004 04020702
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_le_f32_e32 0x3f666666, v4                            ; 7c2608ff 3f666666
	s_cbranch_execz BB6                                         ; bf88000b
BB1:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[2:4], v[22:23], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220216
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mov_b32_e32 v0, v4                                        ; 7e000304
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v3                          ; 5e040702
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 0                           ; d52f0000 00010100
	exp mrt0 v2, v2, v0, v0 done compr vm                       ; f8001c0f 80800002
	s_endpgm                                                    ; bf810000
