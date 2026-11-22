# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s3                                            ; befc0303
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_interp_p1_f32_e32 v2, v0, attr0.w                         ; c8080300
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_mov_f32_e32 v4, p0, attr3.y                        ; c8120d02
	v_interp_p2_f32_e32 v2, v1, attr0.w                         ; c8090301
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	v_lshrrev_b64 v[22:23], 0, v[2:3]                           ; d7000016 00020480
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_ne_i32_e32 -1, v4                                    ; 7d2a08c1
	s_cbranch_execz BB4                                         ; bf880019
BB1:
	s_mov_b32 s4, s2                                            ; be840302
	s_movk_i32 s5, 0x8000                                       ; b0058000
	v_mul_lo_u32 v4, 0x60, v4                                   ; d5690004 000208ff 00000060
	v_add_nc_u32_e32 v2, 32, v4                                 ; 4a0408a0
	v_add_nc_u32_e32 v4, 0x70, v4                               ; 4a0808ff 00000070
	v_readfirstlane_b32 s3, v2                                  ; 7e060502
	v_readfirstlane_b32 s6, v4                                  ; 7e0c0504
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[4:5], s3                          ; f40c0202 06000000
	s_load_dwordx4 s[4:7], s[4:5], s6                           ; f4080102 0c000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[3:5], v[22:23], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220316
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v5, 2.0, v5, -1.0                                 ; d5410005 03ce0af4
	v_mad_f32 v3, 2.0, v3, -1.0                                 ; d5410003 03ce06f4
	v_mad_f32 v4, 2.0, v4, -1.0                                 ; d5410004 03ce08f4
BB4:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_interp_p1_f32_e32 v4, v0, attr0.y                         ; c8100100
	v_interp_p1_f32_e32 v5, v0, attr0.z                         ; c8140200
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p2_f32_e32 v4, v1, attr0.y                         ; c8110101
	v_interp_p2_f32_e32 v5, v1, attr0.z                         ; c8150201
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_mul_f32_e32 v2, v4, v4                                    ; 10040904
	v_interp_p1_f32_e32 v6, v0, attr1.z                         ; c8180600
	v_interp_p1_f32_e32 v8, v0, attr1.w                         ; c8200700
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v6, v1, attr1.z                         ; c8190601
	v_interp_p2_f32_e32 v8, v1, attr1.w                         ; c8210701
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mac_f32_e32 v2, v5, v5                                    ; 3e040b05
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mac_f32_e32 v2, v3, v3                                    ; 3e040703
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_rsq_f32_e32 v2, v2                                        ; 7e045d02
	v_mac_f32_e32 v7, v0, v0                                    ; 3e0e0100
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_interp_mov_f32_e32 v10, p0, attr3.x                       ; c82a0c02
	v_mul_f32_e32 v3, v3, v2                                    ; 10060503
	v_mul_f32_e32 v4, v4, v2                                    ; 10080504
	v_mul_f32_e32 v5, v5, v2                                    ; 100a0505
	v_mul_f32_e32 v9, 0xbf13cd39, v4                            ; 101208ff bf13cd39
	v_mul_f32_e32 v0, v0, v7                                    ; 10000f00
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mad_f32 v9, 0x3f13cd39, -v5, -v9                          ; d5410009 c4260aff 3f13cd39
	v_mad_f32 v9, 0x3f13cd39, -v3, v9 mul:2                     ; d5410009 4c2606ff 3f13cd39
	v_mad_f32 v5, v5, -v9, 0xbf13cd39                           ; d5410005 43fe1305 bf13cd39
	v_mad_f32 v4, v4, -v9, 0x3f13cd39                           ; d5410004 43fe1304 3f13cd39
	v_mad_f32 v3, v3, -v9, 0xbf13cd39                           ; d5410003 43fe1303 bf13cd39
	v_mul_f32_e32 v5, v5, v8                                    ; 100a1105
	v_mac_f32_e32 v5, v4, v6                                    ; 3e0a0d04
	v_mac_f32_e32 v5, v3, v0                                    ; 3e0a0103
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_ne_i32_e32 -1, v10                                   ; 7d2a14c1
	s_cbranch_execz BB10                                        ; bf880011
BB7:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	v_mul_lo_u32 v10, 0x60, v10                                 ; d569000a 000214ff 00000060
	v_add_nc_u32_e32 v0, 32, v10                                ; 4a0014a0
	v_add_nc_u32_e32 v10, 0x70, v10                             ; 4a1414ff 00000070
	v_readfirstlane_b32 s4, v0                                  ; 7e080500
	v_readfirstlane_b32 s5, v10                                 ; 7e0a050a
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], s4                          ; f40c0201 08000000
	s_load_dwordx4 s[4:7], s[2:3], s5                           ; f4080101 0a000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[0:3], v[22:23], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220016
BB10:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_interp_mov_f32_e32 v2, p0, attr2.z                        ; c80a0a02
	v_interp_mov_f32_e32 v3, p0, attr2.w                        ; c80e0b02
	v_interp_mov_f32_e32 v0, p0, attr2.x                        ; c8020802
	v_interp_mov_f32_e32 v1, p0, attr2.y                        ; c8060902
BB12:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_max_f32_e32 v5, 0, v5                                     ; 200a0a80
	v_log_f32_e32 v5, v5                                        ; 7e0a4f05
	v_mul_f32_e32 v5, 0x41800000, v5                            ; 100a0aff 41800000
	v_exp_f32_e32 v5, v5                                        ; 7e0a4b05
	v_mul_f32_e32 v5, 0x3f400000, v5                            ; 100a0aff 3f400000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v0, 0, v0, v5                               ; cc210000 041600ff 3e800000
	v_fma_mixhi_f16 v0, 0, v1, v5                               ; cc220000 041602ff 3e800000
	v_madmk_f32 v2, v2, 0x3e800000, v5                          ; 40040b02 3e800000
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v3                          ; 5e040702
	exp mrt0 v0, v0, v2, v2 done compr vm                       ; f8001c0f 80800200
	s_endpgm                                                    ; bf810000
