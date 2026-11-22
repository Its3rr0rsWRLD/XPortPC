# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_load v3, v3, s[8:15] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm a16 ; f0001108 40020303
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmpx_nge_f32_e32 v2, v3                                   ; 7c320702
	s_cbranch_execz BB1                                         ; bf88000b
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_mov_f32_e32 v3, p0, attr0.z                        ; c80e0202
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_cvt_pkrtz_f16_f32_e32 v3, 0, v3                           ; 5e060680
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v2                          ; 5e000500
	exp mrt0 v0, v0, v3, v3 done compr vm                       ; f8001c0f 80800300
	s_endpgm                                                    ; bf810000
BB1:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
