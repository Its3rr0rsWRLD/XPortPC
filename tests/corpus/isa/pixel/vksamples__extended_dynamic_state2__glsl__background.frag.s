# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mac_f32_e32 v3, v0, v0                                    ; 3e060100
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v0, v0, v3                                    ; 10000700
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_cubesc_f32 v6, v0, v2, v4                                 ; d5450006 04120500
	v_cubema_f32 v5, v0, v2, v4                                 ; d5470005 04120500
	v_cubetc_f32 v7, v0, v2, v4                                 ; d5460007 04120500
	v_cubeid_f32 v10, v0, v2, v4                                ; d544000a 04120500
	v_rcp_f32_e64 v5, |v5|                                      ; d5aa0105 00000105
	v_madak_f32 v9, v7, v5, 0x3fc00000                          ; 42120b07 3fc00000
	v_madak_f32 v8, v6, v5, 0x3fc00000                          ; 42100b06 3fc00000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[11:13], v[8:10], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0800718 00220b08
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e64 v13, v13, 1.0                       ; d52f000d 0001e50d
	v_cvt_pkrtz_f16_f32_e32 v11, v11, v12                       ; 5e16190b
	exp mrt0 v11, v11, v13, v13 done compr vm                   ; f8001c0f 80800d0b
	s_endpgm                                                    ; bf810000
