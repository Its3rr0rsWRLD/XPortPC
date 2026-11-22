# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_mov_b32 m0, s0                                            ; befc0300
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx2 s[0:1], s[4:7], 0xc0                  ; f4240002 fa0000c0
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_fma_mixlo_f16 v4, s0, v2, s1                              ; cc210004 00060400
	v_fma_mixhi_f16 v4, s0, v3, s1                              ; cc220004 00060600
	v_mad_f32 v0, s0, v0, s1                                    ; d5410000 00060000
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 1.0                         ; d52f0000 0001e500
	exp mrt0 v4, v4, v0, v0 done compr vm                       ; f8001c0f 80800004
	s_endpgm                                                    ; bf810000
