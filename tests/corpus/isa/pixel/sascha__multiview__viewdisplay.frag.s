# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s1, s[4:7], 0x110                       ; f4200042 fa000110
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.x                         ; c8080000
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v2, v1, attr0.x                         ; c8090001
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mac_f32_e32 v3, v0, v0                                    ; 3e060100
	v_sqrt_f32_e32 v3, v3                                       ; 7e066703
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mad_f32 v3, s1, -v3, 1.0                                  ; d5410003 43ca0601
	v_rcp_f32_e32 v3, v3                                        ; 7e065503
	v_mad_f32 v4, v2, v3, 1.0 div:2                             ; d5410004 1bca0702
	v_mad_f32 v5, v0, v3, 1.0 div:2                             ; d5410005 1bca0700
	v_add_f32_e64 v7, v4, 0 clamp                               ; d5038007 00010104
	v_cmp_le_f32_e64 s[0:1], 0, v5                              ; d4030000 00020a80
	v_cmp_eq_f32_e32 vcc, v4, v7                                ; 7c040f04
	s_and_b64 s[0:1], vcc, s[0:1]                               ; 8780006a
	v_cmp_ge_f32_e32 vcc, 1.0, v5                               ; 7c0c0af2
	s_and_b64 s[0:1], s[0:1], vcc                               ; 87806a00
	s_and_saveexec_b64 s[0:1], s[0:1]                           ; be802400
	s_cbranch_execz BB4                                         ; bf880009
BB1:
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	v_mov_b32_e32 v6, 0                                         ; 7e0c0280
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[0:3], v[4:6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D_ARRAY ; f0800f28 00220004
BB4:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_lshrrev_b64 v[0:1], 0, 0                                  ; d7000000 00010080
	v_lshrrev_b64 v[2:3], 0, 0                                  ; d7000002 00010080
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v1                          ; 5e000300
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v3                          ; 5e040702
	exp mrt0 v0, v0, v2, v2 done compr vm                       ; f8001c0f 80800200
	s_endpgm                                                    ; bf810000
