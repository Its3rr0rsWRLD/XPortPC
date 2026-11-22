# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_mov_b32 m0, s0                                            ; befc0300
	s_clause 0x3                                                ; bfa10003
	s_load_dwordx8 s[8:15], s[2:3], 0x80                        ; f40c0201 fa000080
	s_load_dwordx4 s[4:7], s[2:3], 0xd0                         ; f4080101 fa0000d0
	s_load_dwordx8 s[16:23], s[2:3], 0x20                       ; f40c0401 fa000020
	s_load_dwordx4 s[0:3], s[2:3], 0x70                         ; f4080001 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v3, v0, attr0.w                         ; c80c0300
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v3, v1, attr0.w                         ; c80d0301
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:6], [v3, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220403 00000002
	image_sample  v[8:11], [v3, v2], s[16:23], s[0:3] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00040803 00000002
	v_interp_p1_f32_e32 v13, v0, attr0.z                        ; c8340200
	v_interp_p1_f32_e32 v14, v0, attr0.x                        ; c8380000
	v_interp_p1_f32_e32 v7, v0, attr0.y                         ; c81c0100
	v_interp_p1_f32_e32 v15, v0, attr2.y                        ; c83c0900
	v_interp_p1_f32_e32 v17, v0, attr2.z                        ; c8440a00
	v_interp_p1_f32_e32 v18, v0, attr2.x                        ; c8480800
	v_interp_p2_f32_e32 v13, v1, attr0.z                        ; c8350201
	v_interp_p2_f32_e32 v14, v1, attr0.x                        ; c8390001
	v_interp_p2_f32_e32 v7, v1, attr0.y                         ; c81d0101
	v_interp_p2_f32_e32 v15, v1, attr2.y                        ; c83d0901
	v_interp_p2_f32_e32 v17, v1, attr2.z                        ; c8450a01
	v_interp_p2_f32_e32 v18, v1, attr2.x                        ; c8490801
	v_mul_f32_e32 v12, v7, v7                                   ; 10180f07
	v_mul_f32_e32 v16, v15, v15                                 ; 10201f0f
	v_mac_f32_e32 v12, v13, v13                                 ; 3e181b0d
	v_mac_f32_e32 v16, v17, v17                                 ; 3e202311
	v_mac_f32_e32 v12, v14, v14                                 ; 3e181d0e
	v_interp_p1_f32_e32 v22, v0, attr1.z                        ; c8580600
	v_interp_p2_f32_e32 v22, v1, attr1.z                        ; c8590601
	v_interp_p1_f32_e32 v23, v0, attr1.y                        ; c85c0500
	v_interp_p2_f32_e32 v23, v1, attr1.y                        ; c85d0501
	v_mac_f32_e32 v16, v18, v18                                 ; 3e202512
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_interp_p1_f32_e32 v0, v0, attr1.w                         ; c8000700
	v_interp_p2_f32_e32 v0, v1, attr1.w                         ; c8010701
	v_cvt_pkrtz_f16_f32_e32 v23, v23, v22                       ; 5e2e2d17
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_mul_f32_e32 v14, v14, v12                                 ; 101c190e
	v_mul_f32_e32 v13, v13, v12                                 ; 101a190d
	v_mul_f32_e32 v7, v7, v12                                   ; 100e1907
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 1.0                         ; d52f0000 0001e500
	v_mul_f32_e32 v18, v18, v16                                 ; 10242112
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v15, v15, v16                                 ; 101e210f
	v_mul_f32_e32 v21, v7, v18                                  ; 102a2507
	v_mul_f32_e32 v20, v14, v17                                 ; 1028230e
	v_mul_f32_e32 v19, v13, v15                                 ; 10261f0d
	v_mad_f32 v21, v14, v15, -v21                               ; d5410015 84561f0e
	v_mad_f32 v20, v13, v18, -v20                               ; d5410014 8452250d
	v_mad_f32 v19, v7, v17, -v19                                ; d5410013 844e2307
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mad_f32 v5, 2.0, v5, -1.0                                 ; d5410005 03ce0af4
	v_mad_f32 v6, 2.0, v6, -1.0                                 ; d5410006 03ce0cf4
	v_mad_f32 v4, 2.0, v4, -1.0                                 ; d5410004 03ce08f4
	v_mul_f32_e32 v1, v5, v5                                    ; 10020b05
	v_mac_f32_e32 v1, v6, v6                                    ; 3e020d06
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e32 v8, v8, v9                          ; 5e101308
	v_cvt_pkrtz_f16_f32_e32 v10, v10, v11                       ; 5e14170a
	v_mac_f32_e32 v1, v4, v4                                    ; 3e020904
	v_rsq_f32_e32 v1, v1                                        ; 7e025d01
	v_mul_f32_e32 v4, v4, v1                                    ; 10080304
	v_mul_f32_e32 v5, v5, v1                                    ; 100a0305
	v_mul_f32_e32 v6, v6, v1                                    ; 100c0306
	v_mul_f32_e32 v14, v14, v6                                  ; 101c0d0e
	v_mul_f32_e32 v7, v7, v6                                    ; 100e0d07
	v_mul_f32_e32 v13, v13, v6                                  ; 101a0d0d
	v_mac_f32_e32 v14, v19, v5                                  ; 3e1c0b13
	v_mac_f32_e32 v7, v20, v5                                   ; 3e0e0b14
	v_mac_f32_e32 v13, v21, v5                                  ; 3e1a0b15
	v_fma_mixlo_f16 v2, v18, v4, v14                            ; cc210002 043a0912
	v_fma_mixhi_f16 v2, v15, v4, v7                             ; cc220002 041e090f
	v_mac_f32_e32 v13, v17, v4                                  ; 3e1a0911
	v_cvt_pkrtz_f16_f32_e64 v13, v13, 1.0                       ; d52f000d 0001e50d
	exp mrt0 v23, v23, v0, v0 compr                             ; f800040f 80800017
	exp mrt1 v2, v2, v13, v13 compr                             ; f800041f 80800d02
	exp mrt2 v8, v8, v10, v10 done compr vm                     ; f8001c2f 80800a08
	s_endpgm                                                    ; bf810000
