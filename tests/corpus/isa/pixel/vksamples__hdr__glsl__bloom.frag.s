# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x60                        ; f40c0201 fa000060
	s_load_dwordx4 s[4:7], s[2:3], 0xb0                         ; f4080101 fa0000b0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_add_f32_e32 v9, 0xbc9374bc, v0                            ; 061200ff bc9374bc
	v_add_f32_e32 v10, 0xbc75c28e, v0                           ; 061400ff bc75c28e
	v_add_f32_e32 v3, 0xbd1374bc, v0                            ; 060600ff bd1374bc
	v_add_f32_e32 v4, 0xbd072b02, v0                            ; 060800ff bd072b02
	v_add_f32_e32 v5, 0xbcf5c28e, v0                            ; 060a00ff bcf5c28e
	v_add_f32_e32 v6, 0xbcdd2f1a, v0                            ; 060c00ff bcdd2f1a
	v_add_f32_e32 v7, 0xbcc49ba5, v0                            ; 060e00ff bcc49ba5
	v_add_f32_e32 v8, 0xbcac0830, v0                            ; 061000ff bcac0830
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[12:15], v[2:3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220c02
	image_sample  v[16:19], [v2, v4], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221002 00000004
	image_sample  v[20:23], [v2, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221402 00000005
	image_sample  v[24:27], [v2, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221802 00000006
	image_sample  v[4:7], [v2, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220402 00000007
	image_sample  v[28:31], [v2, v8], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221c02 00000008
	image_sample  v[32:35], [v2, v9], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00222002 00000009
	image_sample  v[8:11], [v2, v10], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220802 0000000a
	s_mov_b32 s1, 0x3b8eaab4                                    ; be8103ff 3b8eaab4
	s_mov_b32 s2, 0x3b208f01                                    ; be8203ff 3b208f01
	s_mov_b32 s3, 0x3bf12c20                                    ; be8303ff 3bf12c20
	s_mov_b32 s16, 0x3c41e780                                   ; be9003ff 3c41e780
	s_mov_b32 s17, 0x3c944c0d                                   ; be9103ff 3c944c0d
	s_mov_b32 s18, 0x3cd7c55e                                   ; be9203ff 3cd7c55e
	s_mov_b32 s19, 0x3d15511b                                   ; be9303ff 3d15511b
	s_mov_b32 s20, 0x3d449486                                   ; be9403ff 3d449486
	v_add_f32_e32 v3, 0xbc449ba4, v0                            ; 060600ff bc449ba4
	s_mov_b32 s21, 0x3d762e8b                                   ; be9503ff 3d762e8b
	s_mov_b32 s22, 0x3d92a1af                                   ; be9603ff 3d92a1af
	s_waitcnt vmcnt(7)                                          ; bf8c3f77
	v_mul_f32_e32 v15, s2, v15                                  ; 101e1e02
	v_mul_f32_e32 v13, s2, v13                                  ; 101a1a02
	v_mul_f32_e32 v14, s2, v14                                  ; 101c1c02
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mul_f32_e32 v16, s1, v16                                  ; 10202001
	v_mac_f32_e32 v15, s1, v19                                  ; 3e1e2601
	v_mac_f32_e32 v13, s1, v17                                  ; 3e1a2201
	v_add_f32_e32 v17, 0xbbc49ba0, v0                           ; 062200ff bbc49ba0
	v_mac_f32_e32 v14, s1, v18                                  ; 3e1c2401
	v_mac_f32_e32 v16, s2, v12                                  ; 3e201802
	v_add_f32_e32 v12, 0xbc1374ba, v0                           ; 061800ff bc1374ba
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mac_f32_e32 v15, s3, v23                                  ; 3e1e2e03
	v_mac_f32_e32 v13, s3, v21                                  ; 3e1a2a03
	v_mac_f32_e32 v14, s3, v22                                  ; 3e1c2c03
	v_mac_f32_e32 v16, s3, v20                                  ; 3e202803
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v15, s16, v27                                 ; 3e1e3610
	v_mac_f32_e32 v13, s16, v25                                 ; 3e1a3210
	v_mac_f32_e32 v14, s16, v26                                 ; 3e1c3410
	v_mac_f32_e32 v16, s16, v24                                 ; 3e203010
	v_mov_b32_e32 v1, v16                                       ; 7e020310
	image_sample v[20:23], v[2:3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00221402
	image_sample  v[24:27], [v2, v12], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221802 0000000c
	image_sample  v[16:19], [v2, v17], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221002 00000011
	s_mov_b32 s23, 0x3da627c5                                   ; be9703ff 3da627c5
	v_add_f32_e32 v3, 0xbb449ba0, v0                            ; 060600ff bb449ba0
	s_mov_b32 s24, 0x3db318a1                                   ; be9803ff 3db318a1
	s_mov_b32 s25, 0x3db7a14b                                   ; be9903ff 3db7a14b
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mac_f32_e32 v15, s17, v7                                  ; 3e1e0e11
	v_mac_f32_e32 v13, s17, v5                                  ; 3e1a0a11
	v_mac_f32_e32 v14, s17, v6                                  ; 3e1c0c11
	v_mac_f32_e32 v1, s17, v4                                   ; 3e020811
	v_add_f32_e32 v4, 0x3b449bb0, v0                            ; 060800ff 3b449bb0
	v_add_f32_e32 v5, 0x3bc49ba8, v0                            ; 060a00ff 3bc49ba8
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mac_f32_e32 v15, s18, v31                                 ; 3e1e3e12
	v_mac_f32_e32 v13, s18, v29                                 ; 3e1a3a12
	v_add_f32_e32 v6, 0x3c1374c0, v0                            ; 060c00ff 3c1374c0
	v_mac_f32_e32 v14, s18, v30                                 ; 3e1c3c12
	v_mac_f32_e32 v1, s18, v28                                  ; 3e023812
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v15, s19, v35                                 ; 3e1e4613
	v_mac_f32_e32 v13, s19, v33                                 ; 3e1a4213
	v_mac_f32_e32 v14, s19, v34                                 ; 3e1c4413
	v_mac_f32_e32 v1, s19, v32                                  ; 3e024013
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mac_f32_e32 v15, s20, v11                                 ; 3e1e1614
	v_mac_f32_e32 v13, s20, v9                                  ; 3e1a1214
	v_mac_f32_e32 v14, s20, v10                                 ; 3e1c1414
	v_mac_f32_e32 v1, s20, v8                                   ; 3e021014
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v14, s21, v22                                 ; 3e1c2c15
	v_mac_f32_e32 v15, s21, v23                                 ; 3e1e2e15
	v_mac_f32_e32 v13, s21, v21                                 ; 3e1a2a15
	v_mac_f32_e32 v1, s21, v20                                  ; 3e022815
	image_sample v[8:11], v[2:3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220802
	image_sample  v[20:23], [v2, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221402 00000000
	image_sample  v[28:31], [v2, v4], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221c02 00000004
	image_sample  v[32:35], [v2, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00222002 00000005
	image_sample  v[4:7], [v2, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220402 00000006
	v_add_f32_e32 v3, 0x3c449ba8, v0                            ; 060600ff 3c449ba8
	v_add_f32_e32 v12, 0x3c75c290, v0                           ; 061800ff 3c75c290
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mac_f32_e32 v14, s22, v26                                 ; 3e1c3416
	v_mac_f32_e32 v15, s22, v27                                 ; 3e1e3616
	v_mac_f32_e32 v13, s22, v25                                 ; 3e1a3216
	v_mac_f32_e32 v1, s22, v24                                  ; 3e023016
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mac_f32_e32 v14, s23, v18                                 ; 3e1c2417
	v_mac_f32_e32 v15, s23, v19                                 ; 3e1e2617
	v_mac_f32_e32 v13, s23, v17                                 ; 3e1a2217
	v_add_f32_e32 v17, 0x3cac0832, v0                           ; 062200ff 3cac0832
	v_mac_f32_e32 v1, s23, v16                                  ; 3e022017
	v_add_f32_e32 v16, 0x3c9374be, v0                           ; 062000ff 3c9374be
	v_add_f32_e32 v18, 0x3cc49ba8, v0                           ; 062400ff 3cc49ba8
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v13, s24, v9                                  ; 3e1a1218
	v_mac_f32_e32 v15, s24, v11                                 ; 3e1e1618
	v_mac_f32_e32 v1, s24, v8                                   ; 3e021018
	v_mac_f32_e32 v14, s24, v10                                 ; 3e1c1418
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mac_f32_e32 v13, s25, v21                                 ; 3e1a2a19
	v_mac_f32_e32 v15, s25, v23                                 ; 3e1e2e19
	v_mac_f32_e32 v1, s25, v20                                  ; 3e022819
	v_mac_f32_e32 v14, s25, v22                                 ; 3e1c2c19
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v13, s24, v29                                 ; 3e1a3a18
	v_mac_f32_e32 v15, s24, v31                                 ; 3e1e3e18
	v_mac_f32_e32 v1, s24, v28                                  ; 3e023818
	v_mac_f32_e32 v14, s24, v30                                 ; 3e1c3c18
	image_sample v[8:11], v[2:3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220802
	image_sample  v[20:23], [v2, v12], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221402 0000000c
	image_sample  v[24:27], [v2, v16], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221802 00000010
	image_sample  v[28:31], [v2, v17], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221c02 00000011
	image_sample  v[16:19], [v2, v18], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221002 00000012
	v_add_f32_e32 v3, 0x3cdd2f1c, v0                            ; 060600ff 3cdd2f1c
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mac_f32_e32 v13, s23, v33                                 ; 3e1a4217
	v_mac_f32_e32 v15, s23, v35                                 ; 3e1e4617
	v_mac_f32_e32 v1, s23, v32                                  ; 3e024017
	v_add_f32_e32 v32, 0x3cf5c290, v0                           ; 064000ff 3cf5c290
	v_add_f32_e32 v33, 0x3d072b02, v0                           ; 064200ff 3d072b02
	v_mac_f32_e32 v14, s23, v34                                 ; 3e1c4417
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mac_f32_e32 v13, s22, v5                                  ; 3e1a0a16
	v_mac_f32_e32 v15, s22, v7                                  ; 3e1e0e16
	v_mac_f32_e32 v1, s22, v4                                   ; 3e020816
	v_mac_f32_e32 v14, s22, v6                                  ; 3e1c0c16
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v14, s21, v10                                 ; 3e1c1415
	v_mac_f32_e32 v1, s21, v8                                   ; 3e021015
	v_mac_f32_e32 v15, s21, v11                                 ; 3e1e1615
	v_mac_f32_e32 v13, s21, v9                                  ; 3e1a1215
	image_sample v[4:7], v[2:3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220402
	image_sample  v[8:11], [v2, v32], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220802 00000020
	image_sample  v[32:35], [v2, v33], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00222002 00000021
	v_add_f32_e32 v3, 0x3d1374bc, v0                            ; 060600ff 3d1374bc
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mac_f32_e32 v1, s20, v20                                  ; 3e022814
	v_mov_b32_e32 v12, v1                                       ; 7e180301
	image_sample v[0:3], v[2:3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220002
	v_mac_f32_e32 v14, s20, v22                                 ; 3e1c2c14
	v_mac_f32_e32 v15, s20, v23                                 ; 3e1e2e14
	v_mac_f32_e32 v13, s20, v21                                 ; 3e1a2a14
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mac_f32_e32 v12, s19, v24                                 ; 3e183013
	v_mac_f32_e32 v14, s19, v26                                 ; 3e1c3413
	v_mac_f32_e32 v15, s19, v27                                 ; 3e1e3613
	v_mac_f32_e32 v13, s19, v25                                 ; 3e1a3213
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mac_f32_e32 v12, s18, v28                                 ; 3e183812
	v_mac_f32_e32 v14, s18, v30                                 ; 3e1c3c12
	v_mac_f32_e32 v15, s18, v31                                 ; 3e1e3e12
	v_mac_f32_e32 v13, s18, v29                                 ; 3e1a3a12
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v12, s17, v16                                 ; 3e182011
	v_mac_f32_e32 v14, s17, v18                                 ; 3e1c2411
	v_mac_f32_e32 v15, s17, v19                                 ; 3e1e2611
	v_mac_f32_e32 v13, s17, v17                                 ; 3e1a2211
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mac_f32_e32 v15, s16, v7                                  ; 3e1e0e10
	v_mac_f32_e32 v14, s16, v6                                  ; 3e1c0c10
	v_mac_f32_e32 v13, s16, v5                                  ; 3e1a0a10
	v_mac_f32_e32 v12, s16, v4                                  ; 3e180810
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v15, s3, v11                                  ; 3e1e1603
	v_mac_f32_e32 v14, s3, v10                                  ; 3e1c1403
	v_mac_f32_e32 v13, s3, v9                                   ; 3e1a1203
	v_mac_f32_e32 v12, s3, v8                                   ; 3e181003
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v15, s1, v35                                  ; 3e1e4601
	v_mac_f32_e32 v14, s1, v34                                  ; 3e1c4401
	v_mac_f32_e32 v13, s1, v33                                  ; 3e1a4201
	v_mac_f32_e32 v12, s1, v32                                  ; 3e184001
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v17, s2, v2, v14                            ; cc210011 043a0402
	v_fma_mixhi_f16 v17, s2, v3, v15                            ; cc220011 043e0602
	v_fma_mixlo_f16 v16, s2, v0, v12                            ; cc210010 04320002
	v_fma_mixhi_f16 v16, s2, v1, v13                            ; cc220010 04360202
	exp mrt0 v16, v16, v17, v17 done compr vm                   ; f8001c0f 80801110
	s_endpgm                                                    ; bf810000
