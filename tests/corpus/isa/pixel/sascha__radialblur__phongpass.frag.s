# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s3                                            ; befc0303
	v_mov_b32_e32 v23, 0                                        ; 7e2e0280
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_interp_p1_f32_e32 v2, v0, attr0.w                         ; c8080300
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_p1_f32_e32 v4, v0, attr1.y                         ; c8100500
	v_interp_mov_f32_e32 v6, p0, attr3.x                        ; c81a0c02
	v_interp_p2_f32_e32 v2, v1, attr0.w                         ; c8090301
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	v_interp_p2_f32_e32 v4, v1, attr1.y                         ; c8110501
	v_mov_b32_e32 v22, v6                                       ; 7e2c0306
	v_max3_f32 v5, v2, v3, v4                                   ; d5540005 04120702
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_le_f32_e32 0x3f666666, v5                            ; 7c260aff 3f666666
	s_cbranch_execz BB3                                         ; bf880009
BB1:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[0:2], v[22:23], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220016
BB3:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	s_cbranch_execz BB6                                         ; bf880044
BB4:
	v_interp_p1_f32_e32 v5, v0, attr1.w                         ; c8140700
	v_interp_p1_f32_e32 v7, v0, attr2.x                         ; c81c0800
	v_interp_p1_f32_e32 v8, v0, attr1.z                         ; c8200600
	v_interp_p1_f32_e32 v9, v0, attr0.z                         ; c8240200
	v_interp_p1_f32_e32 v10, v0, attr2.w                        ; c8280b00
	v_interp_p1_f32_e32 v12, v0, attr0.y                        ; c8300100
	v_interp_p1_f32_e32 v13, v0, attr2.z                        ; c8340a00
	v_interp_p2_f32_e32 v5, v1, attr1.w                         ; c8150701
	v_interp_p2_f32_e32 v7, v1, attr2.x                         ; c81d0801
	v_interp_p1_f32_e32 v15, v0, attr0.x                        ; c83c0000
	v_interp_p2_f32_e32 v8, v1, attr1.z                         ; c8210601
	v_interp_p2_f32_e32 v9, v1, attr0.z                         ; c8250201
	v_interp_p2_f32_e32 v10, v1, attr2.w                        ; c8290b01
	v_interp_p1_f32_e32 v0, v0, attr2.y                         ; c8000900
	v_interp_p2_f32_e32 v12, v1, attr0.y                        ; c8310101
	v_interp_p2_f32_e32 v13, v1, attr2.z                        ; c8350a01
	v_interp_p2_f32_e32 v15, v1, attr0.x                        ; c83d0001
	v_interp_p2_f32_e32 v0, v1, attr2.y                         ; c8010901
	v_mul_f32_e32 v6, v5, v5                                    ; 100c0b05
	v_mul_f32_e32 v11, v10, v9                                  ; 1016130a
	v_mac_f32_e32 v6, v7, v7                                    ; 3e0c0f07
	v_mad_f32 v14, v13, -v12, -v11                              ; d541000e c42e190d
	v_mac_f32_e32 v6, v8, v8                                    ; 3e0c1108
	v_mac_f32_e32 v11, v13, v12                                 ; 3e16190d
	v_mad_f32 v14, v0, -v15, v14 mul:2                          ; d541000e 4c3a1f00
	v_rsq_f32_e32 v6, v6                                        ; 7e0c5d06
	v_mac_f32_e32 v11, v0, v15                                  ; 3e161f00
	v_mad_f32 v16, v15, -v14, -v0                               ; d5410010 c4021d0f
	v_mad_f32 v17, v12, -v14, -v13                              ; d5410011 c4361d0c
	v_mad_f32 v9, v9, -v14, -v10                                ; d5410009 c42a1d09
	v_max_f32_e64 v11, 0, v11 div:2                             ; d510000b 18021680
	v_mul_f32_e32 v18, v17, v17                                 ; 10242311
	v_mul_f32_e32 v8, v8, v6                                    ; 10100d08
	v_mul_f32_e32 v5, v5, v6                                    ; 100a0d05
	v_mul_f32_e32 v7, v7, v6                                    ; 100e0d07
	v_add_f32_e32 v19, 0x3e4ccccd, v11                          ; 062616ff 3e4ccccd
	v_mac_f32_e32 v18, v9, v9                                   ; 3e241309
	v_add_f32_e32 v11, 1.0, v11                                 ; 061616f2
	v_mac_f32_e32 v18, v16, v16                                 ; 3e242110
	v_rsq_f32_e32 v18, v18                                      ; 7e245d12
	v_mul_f32_e32 v16, v16, v18                                 ; 10202510
	v_mul_f32_e32 v17, v17, v18                                 ; 10222511
	v_mul_f32_e32 v9, v9, v18                                   ; 10122509
	v_mul_f32_e32 v7, v7, v9                                    ; 100e1307
	v_mad_f32 v5, v5, -v17, -v7                                 ; d5410005 c41e2305
	v_mad_f32 v8, v8, -v16, v5                                  ; d5410008 44162108
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_mul_f32_e32 v8, v8, v8                                    ; 10101108
	(then repeated 1 times)
	v_mul_f32_e32 v20, 0x3e000000, v8                           ; 102810ff 3e000000
	v_madmk_f32 v8, v8, 0x3e800000, v11                         ; 40101708 3e800000
	v_mad_f32 v0, v19, v2, v20                                  ; d5410000 04520513
	v_mad_f32 v2, v19, v4, v20                                  ; d5410002 04520913
	v_mad_f32 v1, v19, v3, v20                                  ; d5410001 04520713
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v8                          ; 5e041102
	v_cvt_pkrtz_f16_f32_e32 v0, v0, v1                          ; 5e000300
	exp mrt0 v0, v0, v2, v2 done compr vm                       ; f8001c0f 80800200
	s_endpgm                                                    ; bf810000
