# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s3                                            ; befc0303
	s_mov_b64 s[0:1], exec                                      ; be80047e
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v0, v0, attr0.y                         ; c8000100
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v0, v1, attr0.y                         ; c8010101
	v_rcp_f32_e32 v4, v4                                        ; 7e085504
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v2                                     ; 7c220480
	s_cbranch_execz BB4                                         ; bf8801b2
BB1:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	v_mad_f32 v2, v3, v4, 1.0 div:2                             ; d5410002 1bca0903
	v_mad_f32 v1, v0, v4, 1.0 div:2                             ; d5410001 1bca0900
	v_add_f32_e32 v4, 0xbbc00000, v2                            ; 060804ff bbc00000
	v_add_f32_e32 v5, 0xbbc00000, v1                            ; 060a02ff bbc00000
	v_add_f32_e32 v0, 0xbb800000, v1                            ; 060002ff bb800000
	v_add_f32_e32 v3, 0xbb000000, v1                            ; 060602ff bb000000
	v_add_f32_e32 v6, 0x3b000000, v1                            ; 060c02ff 3b000000
	v_add_f32_e32 v7, 0x3b800000, v1                            ; 060e02ff 3b800000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[8:11], v[4:5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00220804
	image_sample  v[12:15], [v4, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c04 00000000
	image_sample  v[16:19], [v4, v3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221004 00000003
	image_sample  v[20:23], [v4, v1], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221404 00000001
	image_sample  v[24:27], [v4, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221804 00000006
	image_sample  v[28:31], [v4, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221c04 00000007
	v_add_f32_e32 v32, 0x3bc00000, v1                           ; 064002ff 3bc00000
	v_add_f32_e32 v33, 0xbb800000, v2                           ; 064204ff bb800000
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v8, v8, v12                                   ; 06101908
	v_add_f32_e32 v9, v9, v13                                   ; 06121b09
	v_add_f32_e32 v10, v10, v14                                 ; 06141d0a
	v_add_f32_e32 v11, v11, v15                                 ; 06161f0b
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v16, v16, v8                                  ; 06201110
	v_add_f32_e32 v17, v17, v9                                  ; 06221311
	v_add_f32_e32 v18, v18, v10                                 ; 06241512
	v_add_f32_e32 v19, v19, v11                                 ; 06261713
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v24, v24, v20                                 ; 06302918
	v_add_f32_e32 v25, v25, v21                                 ; 06322b19
	v_add_f32_e32 v26, v26, v22                                 ; 06342d1a
	v_add_f32_e32 v27, v27, v23                                 ; 06362f1b
	image_sample  v[8:11], [v4, v32], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220804 00000020
	image_sample  v[12:15], [v33, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c21 00000005
	image_sample  v[16:19], [v33, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221021 00000000
	image_sample  v[20:23], [v33, v3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221421 00000003
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v28, v28, v24                                 ; 0638311c
	v_add_f32_e32 v29, v29, v25                                 ; 063a331d
	v_add_f32_e32 v30, v30, v26                                 ; 063c351e
	v_mov_b32_e32 v4, v27                                       ; 7e08031b
	image_sample  v[24:27], [v33, v1], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221821 00000001
	v_add_f32_e32 v31, v31, v4                                  ; 063e091f
	v_add_f32_e32 v4, 0xbb000000, v2                            ; 060804ff bb000000
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v11, v11, v31                                 ; 06163f0b
	v_add_f32_e32 v8, v8, v28                                   ; 06103908
	v_add_f32_e32 v9, v9, v29                                   ; 06123b09
	v_add_f32_e32 v10, v10, v30                                 ; 06143d0a
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v15, v15, v11                                 ; 061e170f
	v_add_f32_e32 v12, v12, v8                                  ; 0618110c
	v_add_f32_e32 v13, v13, v9                                  ; 061a130d
	v_add_f32_e32 v14, v14, v10                                 ; 061c150e
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v19, v19, v15                                 ; 06261f13
	v_add_f32_e32 v16, v16, v12                                 ; 06201910
	v_add_f32_e32 v17, v17, v13                                 ; 06221b11
	v_add_f32_e32 v18, v18, v14                                 ; 06241d12
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v24, v24, v20                                 ; 06302918
	v_mov_b32_e32 v20, v32                                      ; 7e280320
	image_sample  v[8:11], [v33, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220821 00000006
	image_sample  v[12:15], [v33, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c21 00000007
	image_sample  v[16:19], [v33, v32], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221021 00000020
	image_sample v[28:31], v[4:5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00221c04
	image_sample  v[32:35], [v4, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00222004 00000000
	v_add_f32_e32 v27, v27, v23                                 ; 06362f1b
	v_add_f32_e32 v25, v25, v21                                 ; 06322b19
	v_add_f32_e32 v26, v26, v22                                 ; 06342d1a
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v9, v9, v25                                   ; 06123309
	v_add_f32_e32 v10, v10, v26                                 ; 0614350a
	v_add_f32_e32 v8, v8, v24                                   ; 06103108
	v_add_f32_e32 v11, v11, v27                                 ; 0616370b
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v13, v13, v9                                  ; 061a130d
	v_add_f32_e32 v14, v14, v10                                 ; 061c150e
	v_add_f32_e32 v12, v12, v8                                  ; 0618110c
	v_add_f32_e32 v15, v15, v11                                 ; 061e170f
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v17, v17, v13                                 ; 06221b11
	v_add_f32_e32 v18, v18, v14                                 ; 06241d12
	v_add_f32_e32 v16, v16, v12                                 ; 06201910
	v_add_f32_e32 v19, v19, v15                                 ; 06261f13
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v29, v29, v17                                 ; 063a231d
	v_add_f32_e32 v30, v30, v18                                 ; 063c251e
	v_add_f32_e32 v28, v28, v16                                 ; 0638211c
	v_add_f32_e32 v31, v31, v19                                 ; 063e271f
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v32, v32, v28                                 ; 06403920
	v_mov_b32_e32 v28, v20                                      ; 7e380314
	image_sample  v[8:11], [v4, v3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220804 00000003
	image_sample  v[12:15], [v4, v1], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c04 00000001
	image_sample  v[16:19], [v4, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221004 00000006
	image_sample  v[24:27], [v4, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221804 00000007
	image_sample  v[20:23], [v4, v20], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221404 00000014
	v_add_f32_e32 v33, v33, v29                                 ; 06423b21
	v_add_f32_e32 v34, v34, v30                                 ; 06443d22
	v_add_f32_e32 v35, v35, v31                                 ; 06463f23
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v9, v9, v33                                   ; 06124309
	v_add_f32_e32 v10, v10, v34                                 ; 0614450a
	v_add_f32_e32 v11, v11, v35                                 ; 0616470b
	v_add_f32_e32 v8, v8, v32                                   ; 06104108
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v13, v13, v9                                  ; 061a130d
	v_add_f32_e32 v14, v14, v10                                 ; 061c150e
	v_add_f32_e32 v15, v15, v11                                 ; 061e170f
	v_add_f32_e32 v12, v12, v8                                  ; 0618110c
	v_mov_b32_e32 v4, v28                                       ; 7e08031c
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v17, v17, v13                                 ; 06221b11
	v_add_f32_e32 v18, v18, v14                                 ; 06241d12
	v_add_f32_e32 v19, v19, v15                                 ; 06261f13
	v_add_f32_e32 v16, v16, v12                                 ; 06201910
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v25, v25, v17                                 ; 06322319
	v_add_f32_e32 v26, v26, v18                                 ; 0634251a
	v_add_f32_e32 v27, v27, v19                                 ; 0636271b
	v_add_f32_e32 v24, v24, v16                                 ; 06302118
	image_sample  v[8:11], [v2, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220802 00000005
	image_sample  v[12:15], [v2, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c02 00000000
	image_sample v[16:19], v[2:3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00221002
	image_sample  v[32:35], [v2, v1], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00222002 00000001
	image_sample  v[28:31], [v2, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221c02 00000006
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v21, v21, v25                                 ; 062a3315
	v_add_f32_e32 v22, v22, v26                                 ; 062c3516
	v_add_f32_e32 v23, v23, v27                                 ; 062e3717
	v_add_f32_e32 v20, v20, v24                                 ; 06283114
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v9, v9, v21                                   ; 06122b09
	v_add_f32_e32 v11, v11, v23                                 ; 06162f0b
	v_add_f32_e32 v10, v10, v22                                 ; 06142d0a
	v_add_f32_e32 v8, v8, v20                                   ; 06102908
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v13, v13, v9                                  ; 061a130d
	v_add_f32_e32 v15, v15, v11                                 ; 061e170f
	v_add_f32_e32 v14, v14, v10                                 ; 061c150e
	v_add_f32_e32 v12, v12, v8                                  ; 0618110c
	v_add_f32_e32 v8, 0x3b000000, v2                            ; 061004ff 3b000000
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v17, v17, v13                                 ; 06221b11
	v_add_f32_e32 v19, v19, v15                                 ; 06261f13
	v_add_f32_e32 v18, v18, v14                                 ; 06241d12
	v_add_f32_e32 v16, v16, v12                                 ; 06201910
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v33, v33, v17                                 ; 06422321
	v_add_f32_e32 v35, v35, v19                                 ; 06462723
	v_add_f32_e32 v34, v34, v18                                 ; 06442522
	v_add_f32_e32 v32, v32, v16                                 ; 06402120
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v29, v29, v33                                 ; 063a431d
	v_mov_b32_e32 v9, v35                                       ; 7e120323
	v_add_f32_e32 v30, v30, v34                                 ; 063c451e
	v_add_f32_e32 v28, v28, v32                                 ; 0638411c
	image_sample  v[12:15], [v2, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c02 00000007
	image_sample  v[16:19], [v2, v4], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221002 00000004
	image_sample  v[20:23], [v8, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221408 00000005
	image_sample  v[24:27], [v8, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221808 00000000
	image_sample  v[32:35], [v8, v3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00222008 00000003
	v_add_f32_e32 v31, v31, v9                                  ; 063e131f
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v15, v15, v31                                 ; 061e3f0f
	v_add_f32_e32 v12, v12, v28                                 ; 0618390c
	v_add_f32_e32 v14, v14, v30                                 ; 061c3d0e
	v_add_f32_e32 v13, v13, v29                                 ; 061a3b0d
	v_add_f32_e32 v10, 0x3b800000, v2                           ; 061404ff 3b800000
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v19, v19, v15                                 ; 06261f13
	v_add_f32_e32 v16, v16, v12                                 ; 06201910
	v_add_f32_e32 v18, v18, v14                                 ; 06241d12
	v_add_f32_e32 v17, v17, v13                                 ; 06221b11
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v27, v27, v23                                 ; 06362f1b
	v_add_f32_e32 v24, v24, v20                                 ; 06302918
	v_add_f32_e32 v26, v26, v22                                 ; 06342d1a
	v_add_f32_e32 v25, v25, v21                                 ; 06322b19
	v_mov_b32_e32 v11, v27                                      ; 7e16031b
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v32, v32, v24                                 ; 06403120
	v_add_f32_e32 v34, v34, v26                                 ; 06443522
	v_add_f32_e32 v33, v33, v25                                 ; 06423321
	image_sample  v[12:15], [v8, v1], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c08 00000001
	image_sample  v[16:19], [v8, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221008 00000006
	image_sample  v[20:23], [v8, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221408 00000007
	image_sample  v[28:31], [v8, v4], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221c08 00000004
	image_sample  v[24:27], [v10, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 0022180a 00000005
	v_add_f32_e32 v35, v35, v11                                 ; 06461723
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v12, v12, v32                                 ; 0618410c
	v_add_f32_e32 v13, v13, v33                                 ; 061a430d
	v_add_f32_e32 v15, v15, v35                                 ; 061e470f
	v_add_f32_e32 v14, v14, v34                                 ; 061c450e
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v16, v16, v12                                 ; 06201910
	v_add_f32_e32 v17, v17, v13                                 ; 06221b11
	v_add_f32_e32 v19, v19, v15                                 ; 06261f13
	v_add_f32_e32 v18, v18, v14                                 ; 06241d12
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v28, v28, v20                                 ; 0638291c
	v_add_f32_e32 v29, v29, v21                                 ; 063a2b1d
	v_add_f32_e32 v31, v31, v23                                 ; 063e2f1f
	v_add_f32_e32 v30, v30, v22                                 ; 063c2d1e
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v24, v24, v28                                 ; 06303918
	v_add_f32_e32 v25, v25, v29                                 ; 06323b19
	v_mov_b32_e32 v8, v31                                       ; 7e10031f
	v_add_f32_e32 v26, v26, v30                                 ; 06343d1a
	image_sample  v[12:15], [v10, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c0a 00000000
	image_sample  v[16:19], [v10, v3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 0022100a 00000003
	image_sample  v[20:23], [v10, v1], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 0022140a 00000001
	image_sample  v[32:35], [v10, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 0022200a 00000006
	image_sample  v[28:31], [v10, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221c0a 00000007
	v_add_f32_e32 v2, 0x3bc00000, v2                            ; 060404ff 3bc00000
	v_add_f32_e32 v27, v27, v8                                  ; 0636111b
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v13, v13, v25                                 ; 061a330d
	v_add_f32_e32 v14, v14, v26                                 ; 061c350e
	v_add_f32_e32 v15, v15, v27                                 ; 061e370f
	v_add_f32_e32 v12, v12, v24                                 ; 0618310c
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v17, v17, v13                                 ; 06221b11
	v_add_f32_e32 v18, v18, v14                                 ; 06241d12
	v_add_f32_e32 v19, v19, v15                                 ; 06261f13
	v_add_f32_e32 v16, v16, v12                                 ; 06201910
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v21, v21, v17                                 ; 062a2315
	v_add_f32_e32 v22, v22, v18                                 ; 062c2516
	v_add_f32_e32 v23, v23, v19                                 ; 062e2717
	v_add_f32_e32 v20, v20, v16                                 ; 06282114
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v32, v32, v20                                 ; 06402920
	v_mov_b32_e32 v20, v2                                       ; 7e280302
	v_add_f32_e32 v33, v33, v21                                 ; 06422b21
	v_add_f32_e32 v34, v34, v22                                 ; 06442d22
	v_add_f32_e32 v35, v35, v23                                 ; 06462f23
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v28, v28, v32                                 ; 0638411c
	v_add_f32_e32 v29, v29, v33                                 ; 063a431d
	v_add_f32_e32 v30, v30, v34                                 ; 063c451e
	v_add_f32_e32 v31, v31, v35                                 ; 063e471f
	image_sample  v[8:11], [v10, v4], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 0022080a 00000004
	image_sample  v[12:15], [v2, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220c02 00000005
	image_sample  v[16:19], [v2, v0], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221002 00000000
	image_sample v[24:27], v[2:3], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f08 00221802
	image_sample  v[0:3], [v2, v1], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220002 00000001
	image_sample  v[32:35], [v20, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00222014 00000006
	v_mov_b32_e32 v5, v20                                       ; 7e0a0314
	image_sample  v[20:23], [v20, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00221414 00000007
	image_sample  v[4:7], [v5, v4], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220405 00000004
	s_mov_b32 s2, 0x3ca72f05                                    ; be8203ff 3ca72f05
	s_waitcnt vmcnt(7)                                          ; bf8c3f77
	v_add_f32_e32 v10, v10, v30                                 ; 06143d0a
	v_add_f32_e32 v9, v9, v29                                   ; 06123b09
	v_add_f32_e32 v8, v8, v28                                   ; 06103908
	v_add_f32_e32 v11, v11, v31                                 ; 06163f0b
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_add_f32_e32 v14, v14, v10                                 ; 061c150e
	v_add_f32_e32 v13, v13, v9                                  ; 061a130d
	v_add_f32_e32 v12, v12, v8                                  ; 0618110c
	v_add_f32_e32 v15, v15, v11                                 ; 061e170f
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_add_f32_e32 v18, v18, v14                                 ; 06241d12
	v_add_f32_e32 v17, v17, v13                                 ; 06221b11
	v_add_f32_e32 v16, v16, v12                                 ; 06201910
	v_add_f32_e32 v19, v19, v15                                 ; 06261f13
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_add_f32_e32 v26, v26, v18                                 ; 0634251a
	v_add_f32_e32 v25, v25, v17                                 ; 06322319
	v_add_f32_e32 v24, v24, v16                                 ; 06302118
	v_add_f32_e32 v27, v27, v19                                 ; 0636271b
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e32 v2, v2, v26                                   ; 06043502
	v_add_f32_e32 v1, v1, v25                                   ; 06023301
	v_add_f32_e32 v0, v0, v24                                   ; 06003100
	v_add_f32_e32 v3, v3, v27                                   ; 06063703
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e32 v34, v34, v2                                  ; 06440522
	v_add_f32_e32 v33, v33, v1                                  ; 06420321
	v_add_f32_e32 v32, v32, v0                                  ; 06400120
	v_add_f32_e32 v35, v35, v3                                  ; 06460723
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e32 v22, v22, v34                                 ; 062c4516
	v_add_f32_e32 v21, v21, v33                                 ; 062a4315
	v_add_f32_e32 v20, v20, v32                                 ; 06284114
	v_add_f32_e32 v23, v23, v35                                 ; 062e4717
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v6, v6, v22                                   ; 060c2d06
	v_add_f32_e32 v5, v5, v21                                   ; 060a2b05
	v_add_f32_e32 v4, v4, v20                                   ; 06082904
	v_mad_f32 v23, s2, v23, 1.0                                 ; d5410017 03ca2e02
	v_mul_f32_e32 v6, s2, v6                                    ; 100c0c02
	v_mul_f32_e32 v5, s2, v5                                    ; 100a0a02
	v_mul_f32_e32 v4, s2, v4                                    ; 10080802
	v_mac_f32_e32 v23, s2, v7                                   ; 3e2e0e02
BB4:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_lshrrev_b64 v[4:5], 0, 0                                  ; d7000004 00010080
	v_mov_b32_e32 v6, 0                                         ; 7e0c0280
	v_mov_b32_e32 v23, 1.0                                      ; 7e2e02f2
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cvt_pkrtz_f16_f32_e32 v4, v4, v5                          ; 5e080b04
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v23                         ; 5e0c2f06
	exp mrt0 v4, v4, v6, v6 done compr vm                       ; f8001c0f 80800604
	s_endpgm                                                    ; bf810000
