# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v3, v0, attr1.z                         ; c80c0600
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p2_f32_e32 v3, v1, attr1.z                         ; c80d0601
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:6], [v3, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220403 00000002
	v_interp_p1_f32_e32 v12, v0, attr0.z                        ; c8300200
	v_interp_p1_f32_e32 v10, v0, attr0.y                        ; c8280100
	v_interp_p1_f32_e32 v7, v0, attr0.w                         ; c81c0300
	v_interp_p1_f32_e32 v8, v0, attr1.x                         ; c8200400
	v_interp_p1_f32_e32 v9, v0, attr1.y                         ; c8240500
	v_interp_p1_f32_e32 v13, v0, attr0.x                        ; c8340000
	v_interp_p1_f32_e32 v14, v0, attr3.x                        ; c8380c00
	v_interp_p2_f32_e32 v12, v1, attr0.z                        ; c8310201
	v_interp_p2_f32_e32 v10, v1, attr0.y                        ; c8290101
	v_interp_p1_f32_e32 v16, v0, attr3.y                        ; c8400d00
	v_interp_p2_f32_e32 v7, v1, attr0.w                         ; c81d0301
	v_interp_p2_f32_e32 v8, v1, attr1.x                         ; c8210401
	v_interp_p2_f32_e32 v9, v1, attr1.y                         ; c8250501
	v_interp_p1_f32_e32 v17, v0, attr2.w                        ; c8440b00
	v_interp_p2_f32_e32 v13, v1, attr0.x                        ; c8350001
	v_interp_p2_f32_e32 v14, v1, attr3.x                        ; c8390c01
	v_interp_p2_f32_e32 v16, v1, attr3.y                        ; c8410d01
	v_interp_p1_f32_e32 v18, v0, attr2.y                        ; c8480900
	v_interp_p2_f32_e32 v17, v1, attr2.w                        ; c8450b01
	v_interp_p2_f32_e32 v18, v1, attr2.y                        ; c8490901
	v_interp_p1_f32_e32 v20, v0, attr2.z                        ; c8500a00
	v_interp_p2_f32_e32 v20, v1, attr2.z                        ; c8510a01
	v_mul_f32_e32 v11, v10, v10                                 ; 1016150a
	v_mul_f32_e32 v15, v14, v14                                 ; 101e1d0e
	v_mul_f32_e32 v19, v18, v18                                 ; 10262512
	v_interp_p1_f32_e32 v0, v0, attr2.x                         ; c8000800
	v_interp_p2_f32_e32 v0, v1, attr2.x                         ; c8010801
	v_mac_f32_e32 v11, v12, v12                                 ; 3e16190c
	v_mac_f32_e32 v15, v16, v16                                 ; 3e1e2110
	v_mac_f32_e32 v19, v20, v20                                 ; 3e262914
	v_mac_f32_e32 v11, v13, v13                                 ; 3e161b0d
	v_mac_f32_e32 v15, v17, v17                                 ; 3e1e2311
	v_mac_f32_e32 v19, v0, v0                                   ; 3e260100
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_rsq_f32_e32 v15, v15                                      ; 7e1e5d0f
	v_rsq_f32_e32 v19, v19                                      ; 7e265d13
	v_mul_f32_e32 v13, v13, v11                                 ; 101a170d
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_mul_f32_e32 v14, v14, v15                                 ; 101c1f0e
	v_mul_f32_e32 v17, v17, v15                                 ; 10221f11
	v_mul_f32_e32 v16, v16, v15                                 ; 10201f10
	v_mul_f32_e32 v20, v20, v19                                 ; 10282714
	v_mul_f32_e32 v18, v18, v19                                 ; 10242712
	v_mul_f32_e32 v0, v0, v19                                   ; 10002700
	v_mul_f32_e32 v21, v16, v12                                 ; 102a1910
	v_mad_f32 v22, v14, -v10, -v21                              ; d5410016 c456150e
	v_mac_f32_e32 v21, v14, v10                                 ; 3e2a150e
	v_mad_f32 v22, v17, -v13, v22 mul:2                         ; d5410016 4c5a1b11
	v_mac_f32_e32 v21, v17, v13                                 ; 3e2a1b11
	v_mad_f32 v12, v12, -v22, -v16                              ; d541000c c4422d0c
	v_mad_f32 v1, v10, -v22, -v14                               ; d5410001 c43a2d0a
	v_mad_f32 v23, v13, -v22, -v17                              ; d5410017 c4462d0d
	v_max_f32_e32 v21, 0, v21                                   ; 202a2a80
	v_mul_f32_e32 v12, v12, v20                                 ; 1018290c
	v_mac_f32_e32 v12, v1, v18                                  ; 3e182501
	v_mac_f32_e32 v12, v23, v0                                  ; 3e180117
	v_max_f32_e32 v12, 0, v12                                   ; 20181880
	v_mul_f32_e32 v12, v12, v12                                 ; 1018190c
	v_mul_f32_e64 v12, v12, v12 div:2                           ; d508000c 1802190c
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v6, 0x3fc00000, v6                            ; 100c0cff 3fc00000
	v_mul_f32_e32 v5, 0x3fc00000, v5                            ; 100a0aff 3fc00000
	v_mul_f32_e32 v4, v4, v7                                    ; 10080f04
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v9, v9, v21                                   ; 10122b09
	v_mul_f32_e32 v5, v5, v8                                    ; 100a1105
	v_mul_f32_e32 v8, v8, v21                                   ; 10102b08
	v_mul_f32_e32 v4, 0x3fc00000, v4                            ; 100808ff 3fc00000
	v_mul_f32_e32 v2, v12, v4                                   ; 1004090c
	v_mac_f32_e32 v12, v7, v21                                  ; 3e182b07
	v_fma_mixlo_f16 v3, v4, v12, neg(0) op_sel_hi:[0,0,1]       ; cc214003 82021904
	v_fma_mixhi_f16 v3, v8, v5, v2                              ; cc220003 040a0b08
	v_mac_f32_e32 v2, v9, v6                                    ; 3e040d09
	v_cvt_pkrtz_f16_f32_e64 v2, v2, 1.0                         ; d52f0002 0001e502
	exp mrt0 v3, v3, v2, v2 done compr vm                       ; f8001c0f 80800203
	s_endpgm                                                    ; bf810000
