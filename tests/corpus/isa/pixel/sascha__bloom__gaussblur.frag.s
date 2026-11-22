# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x70                       ; f4080401 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[3:5], [v0, v2], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00820300 00000002
	s_buffer_load_dwordx2 s[0:1], s[4:7], null                  ; f4240002 fa000000
	s_bfe_u32 s27, s11, 0x4000c                                 ; 939bff0b 0004000c
	s_bfe_u32 s26, s10, 0x10000e                                ; 939aff0a 0010000e
	s_add_u32 s26, s26, 1                                       ; 801a811a
	s_lshr_b32 s26, s26, s27                                    ; 901a1b1a
	s_max_u32 s26, s26, 1                                       ; 849a811a
	s_cmp_eq_i32 s9, 0                                          ; bf008009
	s_cselect_b32 s26, 0, s26                                   ; 851a1a80
	v_cvt_f32_i32_e32 v6, s26                                   ; 7e0c0a1a
	v_rcp_f32_e32 v6, v6                                        ; 7e0c5506
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e32 v6, s0, v6                                    ; 100c0c00
	v_add_f32_e32 v1, v2, v6                                    ; 06020d02
	v_mad_f32 v8, 2.0, v6, v2                                   ; d5410008 040a0cf4
	v_sub_f32_e32 v7, v2, v6                                    ; 080e0d02
	v_mad_f32 v9, 2.0, -v6, v2                                  ; d5410009 440a0cf4
	v_madmk_f32 v10, v6, 0x40400000, v2                         ; 40140506 40400000
	v_mad_f32 v11, 0x40400000, -v6, v2                          ; d541000b 440a0cff 40400000
	v_mad_f32 v12, 4.0, v6, v2                                  ; d541000c 040a0cf6
	v_mad_f32 v6, 4.0, -v6, v2                                  ; d5410006 440a0cf6
	image_sample v[13:15], v[0:1], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00820d00
	image_sample  v[16:18], [v0, v7], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00821000 00000007
	image_sample  v[19:21], [v0, v8], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00821300 00000008
	image_sample  v[22:24], [v0, v9], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00821600 00000009
	image_sample  v[25:27], [v0, v10], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00821900 0000000a
	image_sample  v[7:9], [v0, v11], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00820700 0000000b
	image_sample  v[10:12], [v0, v12], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00820a00 0000000c
	image_sample  v[0:2], [v0, v6], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00820000 00000006
	s_mov_b32 s2, 0x3e4743cf                                    ; be8203ff 3e4743cf
	s_mov_b32 s3, 0x3df914bf                                    ; be8303ff 3df914bf
	s_mov_b32 s4, 0x3d5d67ba                                    ; be8403ff 3d5d67ba
	s_mov_b32 s5, 0x3c84d76b                                    ; be8503ff 3c84d76b
	s_waitcnt vmcnt(7)                                          ; bf8c3f77
	v_mul_f32_e32 v13, s2, v13                                  ; 101a1a02
	v_mul_f32_e32 v14, s2, v14                                  ; 101c1c02
	v_mul_f32_e32 v15, s2, v15                                  ; 101e1e02
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mul_f32_e32 v17, s2, v17                                  ; 10222202
	v_mul_f32_e32 v16, s2, v16                                  ; 10202002
	v_mul_f32_e32 v18, s2, v18                                  ; 10242402
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mul_f32_e32 v19, s3, v19                                  ; 10262603
	v_mul_f32_e32 v20, s3, v20                                  ; 10282803
	v_mul_f32_e32 v21, s3, v21                                  ; 102a2a03
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mul_f32_e32 v22, s3, v22                                  ; 102c2c03
	v_mul_f32_e32 v13, s1, v13                                  ; 101a1a01
	v_mul_f32_e32 v23, s3, v23                                  ; 102e2e03
	v_mul_f32_e32 v14, s1, v14                                  ; 101c1c01
	v_mul_f32_e32 v15, s1, v15                                  ; 101e1e01
	v_mul_f32_e32 v24, s3, v24                                  ; 10303003
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mul_f32_e32 v25, s4, v25                                  ; 10323204
	v_mul_f32_e32 v26, s4, v26                                  ; 10343404
	v_mul_f32_e32 v27, s4, v27                                  ; 10363604
	v_madmk_f32 v3, v3, 0x3e6879c4, v13                         ; 40061b03 3e6879c4
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mul_f32_e32 v7, s4, v7                                    ; 100e0e04
	v_madmk_f32 v4, v4, 0x3e6879c4, v14                         ; 40081d04 3e6879c4
	v_mul_f32_e32 v8, s4, v8                                    ; 10101004
	v_madmk_f32 v5, v5, 0x3e6879c4, v15                         ; 400a1f05 3e6879c4
	v_mul_f32_e32 v9, s4, v9                                    ; 10121204
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v10, s5, v10                                  ; 10141405
	v_mac_f32_e32 v3, s1, v16                                   ; 3e062001
	v_mul_f32_e32 v11, s5, v11                                  ; 10161605
	v_mul_f32_e32 v12, s5, v12                                  ; 10181805
	v_mac_f32_e32 v4, s1, v17                                   ; 3e082201
	v_mac_f32_e32 v5, s1, v18                                   ; 3e0a2401
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v0, s5, v0                                    ; 10000005
	v_mul_f32_e32 v1, s5, v1                                    ; 10020205
	v_mac_f32_e32 v3, s1, v19                                   ; 3e062601
	v_mul_f32_e32 v2, s5, v2                                    ; 10040405
	v_mac_f32_e32 v4, s1, v20                                   ; 3e082801
	v_mac_f32_e32 v5, s1, v21                                   ; 3e0a2a01
	v_mac_f32_e32 v3, s1, v22                                   ; 3e062c01
	v_mac_f32_e32 v4, s1, v23                                   ; 3e082e01
	v_mac_f32_e32 v5, s1, v24                                   ; 3e0a3001
	v_mac_f32_e32 v3, s1, v25                                   ; 3e063201
	v_mac_f32_e32 v4, s1, v26                                   ; 3e083401
	v_mac_f32_e32 v5, s1, v27                                   ; 3e0a3601
	v_mac_f32_e32 v3, s1, v7                                    ; 3e060e01
	v_mac_f32_e32 v4, s1, v8                                    ; 3e081001
	v_mac_f32_e32 v5, s1, v9                                    ; 3e0a1201
	v_mac_f32_e32 v3, s1, v10                                   ; 3e061401
	v_mac_f32_e32 v4, s1, v11                                   ; 3e081601
	v_mac_f32_e32 v5, s1, v12                                   ; 3e0a1801
	v_fma_mixlo_f16 v3, s1, v0, v3                              ; cc210003 040e0001
	v_fma_mixhi_f16 v3, s1, v1, v4                              ; cc220003 04120201
	v_mac_f32_e32 v5, s1, v2                                    ; 3e0a0401
	v_cvt_pkrtz_f16_f32_e64 v5, v5, 1.0                         ; d52f0005 0001e505
	exp mrt0 v3, v3, v5, v5 done compr vm                       ; f8001c0f 80800503
	s_endpgm                                                    ; bf810000
