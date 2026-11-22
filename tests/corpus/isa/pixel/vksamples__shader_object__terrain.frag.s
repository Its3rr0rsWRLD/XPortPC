# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x80                        ; f40c0201 fa000080
	s_load_dwordx4 s[4:7], s[2:3], 0xd0                         ; f4080101 fa0000d0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_mov_b32_e32 v6, 0                                         ; 7e0c0280
	v_mov_b32_e32 v7, 1.0                                       ; 7e0e02f2
	v_mov_b32_e32 v8, 2.0                                       ; 7e1002f4
	v_mov_b32_e32 v9, 0x40400000                                ; 7e1202ff 40400000
	v_mov_b32_e32 v10, 4.0                                      ; 7e1402f6
	v_mov_b32_e32 v11, 0x40a00000                               ; 7e1602ff 40a00000
	v_interp_p1_f32_e32 v4, v0, attr0.x                         ; c8100000
	v_interp_p1_f32_e32 v5, v0, attr0.y                         ; c8140100
	v_interp_p2_f32_e32 v4, v1, attr0.x                         ; c8110001
	v_interp_p2_f32_e32 v5, v1, attr0.y                         ; c8150101
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[12:14], v[4:6], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800728 00220c04
	image_sample  v[15:17], [v4, v5, v7], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00220f04 00000705
	image_sample  v[18:20], [v4, v5, v8], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00221204 00000805
	image_sample  v[21:23], [v4, v5, v9], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00221504 00000905
	image_sample  v[24:26], [v4, v5, v10], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00221804 00000a05
	image_sample  v[4:6], [v4, v5, v11], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00220404 00000b05
	v_interp_p1_f32_e32 v7, v0, attr1.x                         ; c81c0400
	v_interp_p1_f32_e32 v9, v0, attr1.y                         ; c8240500
	v_interp_p1_f32_e32 v10, v0, attr0.w                        ; c8280300
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v7, v1, attr1.x                         ; c81d0401
	v_interp_p2_f32_e32 v9, v1, attr1.y                         ; c8250501
	v_interp_p2_f32_e32 v10, v1, attr0.w                        ; c8290301
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mul_f32_e32 v8, v7, v7                                    ; 10100f07
	v_mul_f32_e32 v7, 0xbf3504f3, v7                            ; 100e0eff bf3504f3
	v_add_f32_e32 v1, 0x432f0000, v0                            ; 060200ff 432f0000
	v_add_f32_e32 v27, 0x43520000, v0                           ; 063600ff 43520000
	v_add_f32_e32 v11, 0x43750000, v0                           ; 061600ff 43750000
	v_mac_f32_e32 v8, v9, v9                                    ; 3e101309
	v_madmk_f32 v9, v9, 0x3f3504f3, v7                          ; 40120f09 3f3504f3
	v_add_f32_e32 v7, 0x431b0000, v0                            ; 060e00ff 431b0000
	v_sub_f32_e64 v1, 0x420c0000, |v1|                          ; d5040201 000202ff 420c0000
	v_sub_f32_e64 v27, 0x42200000, |v27|                        ; d504021b 000236ff 42200000
	v_sub_f32_e64 v11, 0x41a00000, |v11|                        ; d504020b 000216ff 41a00000
	v_mac_f32_e32 v8, v10, v10                                  ; 3e10150a
	v_sub_f32_e64 v7, 0x41c80000, |v7|                          ; d5040207 00020eff 41c80000
	v_mul_f32_e32 v1, 0x3cea0ea1, v1                            ; 100202ff 3cea0ea1
	v_mul_f32_e32 v27, 0x3ccccccd, v27                          ; 103636ff 3ccccccd
	v_mul_f32_e32 v11, 0x3d4ccccd, v11                          ; 101616ff 3d4ccccd
	v_rsq_f32_e32 v8, v8                                        ; 7e105d08
	v_mul_f32_e32 v7, 0x3d23d70a, v7                            ; 100e0eff 3d23d70a
	v_max_f32_e32 v1, 0, v1                                     ; 20020280
	v_max_f32_e32 v27, 0, v27                                   ; 20363680
	v_max_f32_e32 v11, 0, v11                                   ; 20161680
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_max_f32_e32 v7, 0, v7                                     ; 200e0e80
	v_mul_f32_e32 v10, 0xbd13bb63, v2                           ; 101404ff bd13bb63
	v_mul_f32_e32 v8, v8, v9                                    ; 10101308
	v_add_f32_e32 v9, 0x42d20000, v0                            ; 061200ff 42d20000
	v_add_f32_e32 v0, 0xc20c0000, v0                            ; 060000ff c20c0000
	v_mul_f32_e32 v2, 0x3ccccccd, v2                            ; 100404ff 3ccccccd
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_sub_f32_e64 v9, 0x425c0000, |v9|                          ; d5040209 000212ff 425c0000
	v_sub_f32_e64 v0, 0x43160000, |v0|                          ; d5040200 000200ff 43160000
	v_mul_f32_e32 v10, v10, v2                                  ; 1014050a
	v_add_f32_e32 v8, 0.5, v8                                   ; 061010f0
	v_mul_f32_e32 v9, 0x3c94f209, v9                            ; 101212ff 3c94f209
	v_mul_f32_e32 v0, 0x3bda740e, v0                            ; 100000ff 3bda740e
	v_exp_f32_e32 v10, v10                                      ; 7e144b0a
	v_max_f32_e32 v9, 0, v9                                     ; 20121280
	v_max_f32_e32 v0, 0, v0                                     ; 20000080
	v_sub_f32_e64 v10, 1.0, v10 clamp                           ; d504800a 000214f2
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_mul_f32_e32 v13, v13, v11                                 ; 101a170d
	v_mul_f32_e32 v14, v14, v11                                 ; 101c170e
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v12, v15, v27                                 ; 3e18370f
	v_mac_f32_e32 v13, v16, v27                                 ; 3e1a3710
	v_mac_f32_e32 v14, v17, v27                                 ; 3e1c3711
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mac_f32_e32 v12, v18, v1                                  ; 3e180312
	v_mac_f32_e32 v13, v19, v1                                  ; 3e1a0313
	v_mac_f32_e32 v14, v20, v1                                  ; 3e1c0314
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v12, v21, v7                                  ; 3e180f15
	v_mac_f32_e32 v13, v22, v7                                  ; 3e1a0f16
	v_mac_f32_e32 v14, v23, v7                                  ; 3e1c0f17
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v12, v24, v9                                  ; 3e181318
	v_mac_f32_e32 v13, v25, v9                                  ; 3e1a1319
	v_mac_f32_e32 v14, v26, v9                                  ; 3e1c131a
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v12, v4, v0                                   ; 3e180104
	v_mac_f32_e32 v13, v5, v0                                   ; 3e1a0105
	v_mac_f32_e32 v14, v6, v0                                   ; 3e1c0106
	v_mul_f32_e32 v12, v8, v12                                  ; 10181908
	v_mul_f32_e32 v13, v8, v13                                  ; 101a1b08
	v_mul_f32_e32 v8, v8, v14                                   ; 10101d08
	v_sub_f32_e32 v11, 0x3ef0a3d7, v12                          ; 081618ff 3ef0a3d7
	v_sub_f32_e32 v14, 0.5, v13                                 ; 081c1af0
	v_sub_f32_e32 v15, 0x3f2b851f, v8                           ; 081e10ff 3f2b851f
	v_fma_mixlo_f16 v12, v10, v11, v12                          ; cc21000c 0432170a
	v_fma_mixhi_f16 v12, v10, v14, v13                          ; cc22000c 04361d0a
	v_fma_mixlo_f16 v16, v10, v15, v8                           ; cc210010 04221f0a
	v_fma_mixhi_f16 v16, 1.0, -v10, 1.0 op_sel_hi:[0,0,1]       ; cc224010 43ca14f2
	exp mrt0 v12, v12, v16, v16 done compr vm                   ; f8001c0f 8080100c
	s_endpgm                                                    ; bf810000
