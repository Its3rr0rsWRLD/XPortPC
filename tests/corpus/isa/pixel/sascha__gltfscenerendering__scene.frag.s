# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v3, v0, attr1.z                         ; c80c0600
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p2_f32_e32 v3, v1, attr1.z                         ; c80d0601
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v3, v2], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00220403 00000002
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x60                        ; f40c0201 fa000060
	s_load_dwordx4 s[0:3], s[2:3], 0xb0                         ; f4080001 fa0000b0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[8:10], [v3, v2], s[8:15], s[0:3] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00020803 00000002
	v_interp_p1_f32_e32 v14, v0, attr0.y                        ; c8380100
	v_interp_p1_f32_e32 v12, v0, attr1.x                        ; c8300400
	v_interp_p1_f32_e32 v13, v0, attr1.y                        ; c8340500
	v_interp_p1_f32_e32 v11, v0, attr0.w                        ; c82c0300
	v_interp_p1_f32_e32 v16, v0, attr0.z                        ; c8400200
	v_interp_p1_f32_e32 v17, v0, attr0.x                        ; c8440000
	v_interp_p1_f32_e32 v20, v0, attr3.w                        ; c8500f00
	v_interp_p2_f32_e32 v14, v1, attr0.y                        ; c8390101
	v_interp_p2_f32_e32 v12, v1, attr1.x                        ; c8310401
	v_interp_p1_f32_e32 v22, v0, attr4.x                        ; c8581000
	v_interp_p2_f32_e32 v13, v1, attr1.y                        ; c8350501
	v_interp_p2_f32_e32 v11, v1, attr0.w                        ; c82d0301
	v_interp_p2_f32_e32 v16, v1, attr0.z                        ; c8410201
	v_interp_p1_f32_e32 v23, v0, attr3.z                        ; c85c0e00
	v_interp_p2_f32_e32 v17, v1, attr0.x                        ; c8450001
	v_interp_p2_f32_e32 v20, v1, attr3.w                        ; c8510f01
	v_interp_p2_f32_e32 v22, v1, attr4.x                        ; c8591001
	v_interp_p2_f32_e32 v23, v1, attr3.z                        ; c85d0e01
	v_mul_f32_e32 v15, v14, v14                                 ; 101e1d0e
	v_mul_f32_e32 v26, v16, v20                                 ; 10342910
	v_mul_f32_e32 v21, v20, v20                                 ; 102a2914
	v_mul_f32_e32 v27, v17, v22                                 ; 10362d11
	v_mul_f32_e32 v2, v14, v23                                  ; 10042f0e
	v_interp_p1_f32_e32 v3, v0, attr4.y                         ; c80c1100
	v_interp_p2_f32_e32 v3, v1, attr4.y                         ; c80d1101
	v_mac_f32_e32 v15, v16, v16                                 ; 3e1e2110
	v_mac_f32_e32 v21, v22, v22                                 ; 3e2a2d16
	v_mac_f32_e32 v15, v17, v17                                 ; 3e1e2311
	v_mac_f32_e32 v21, v23, v23                                 ; 3e2a2f17
	v_rsq_f32_e32 v15, v15                                      ; 7e1e5d0f
	v_rsq_f32_e32 v21, v21                                      ; 7e2a5d15
	v_mul_f32_e32 v18, v17, v15                                 ; 10241f11
	v_mad_f32 v17, v17, v20, -v2                                ; d5410011 840a2911
	v_mul_f32_e32 v19, v14, v15                                 ; 10261f0e
	v_mad_f32 v14, v14, v22, -v26                               ; d541000e 846a2d0e
	v_mul_f32_e32 v15, v16, v15                                 ; 101e1f10
	v_mad_f32 v16, v16, v23, -v27                               ; d5410010 846e2f10
	v_interp_p1_f32_e32 v26, v0, attr2.w                        ; c8680b00
	v_interp_p2_f32_e32 v26, v1, attr2.w                        ; c8690b01
	v_mul_f32_e32 v25, v20, v21                                 ; 10322b14
	v_interp_p1_f32_e32 v20, v0, attr3.x                        ; c8500c00
	v_interp_p1_f32_e32 v27, v0, attr2.y                        ; c86c0900
	v_interp_p2_f32_e32 v20, v1, attr3.x                        ; c8510c01
	v_interp_p2_f32_e32 v27, v1, attr2.y                        ; c86d0901
	v_mul_f32_e32 v24, v23, v21                                 ; 10302b17
	v_interp_p1_f32_e32 v23, v0, attr3.y                        ; c85c0d00
	v_interp_p2_f32_e32 v23, v1, attr3.y                        ; c85d0d01
	v_mul_f32_e32 v21, v22, v21                                 ; 102a2b16
	v_mul_f32_e32 v17, v17, v3                                  ; 10220711
	v_mul_f32_e32 v14, v14, v3                                  ; 101c070e
	v_mul_f32_e32 v16, v16, v3                                  ; 10200710
	v_interp_p1_f32_e32 v3, v0, attr2.z                         ; c80c0a00
	v_interp_p1_f32_e32 v0, v0, attr2.x                         ; c8000800
	v_interp_p2_f32_e32 v3, v1, attr2.z                         ; c80d0a01
	v_interp_p2_f32_e32 v0, v1, attr2.x                         ; c8010801
	v_mul_f32_e32 v22, v20, v20                                 ; 102c2914
	v_mul_f32_e32 v2, v27, v27                                  ; 1004371b
	v_mac_f32_e32 v22, v23, v23                                 ; 3e2c2f17
	v_mac_f32_e32 v2, v3, v3                                    ; 3e040703
	v_mac_f32_e32 v22, v26, v26                                 ; 3e2c351a
	v_mac_f32_e32 v2, v0, v0                                    ; 3e040100
	v_rsq_f32_e32 v22, v22                                      ; 7e2c5d16
	v_rsq_f32_e32 v2, v2                                        ; 7e045d02
	v_mul_f32_e32 v26, v26, v22                                 ; 10342d1a
	v_mul_f32_e32 v20, v20, v22                                 ; 10282d14
	v_mul_f32_e32 v23, v23, v22                                 ; 102e2d17
	v_mul_f32_e32 v3, v3, v2                                    ; 10060503
	v_mul_f32_e32 v0, v0, v2                                    ; 10000500
	v_mul_f32_e32 v27, v27, v2                                  ; 1036051b
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v5, v5, v12                                   ; 100a1905
	v_mul_f32_e32 v6, v6, v13                                   ; 100c1b06
	v_mul_f32_e32 v4, v4, v11                                   ; 10081704
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v8, 2.0, v8, -1.0                                 ; d5410008 03ce10f4
	v_mad_f32 v10, 2.0, v10, -1.0                               ; d541000a 03ce14f4
	v_mad_f32 v9, 2.0, v9, -1.0                                 ; d5410009 03ce12f4
	v_mul_f32_e32 v11, v9, v9                                   ; 10161309
	v_mac_f32_e32 v11, v10, v10                                 ; 3e16150a
	v_mac_f32_e32 v11, v8, v8                                   ; 3e161108
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_mul_f32_e32 v8, v8, v11                                   ; 10101708
	v_mul_f32_e32 v9, v9, v11                                   ; 10121709
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v18, v18, v10                                 ; 10241512
	v_mul_f32_e32 v19, v19, v10                                 ; 10261513
	v_mul_f32_e32 v15, v15, v10                                 ; 101e150f
	v_mac_f32_e32 v18, v14, v9                                  ; 3e24130e
	v_mac_f32_e32 v19, v16, v9                                  ; 3e261310
	v_mac_f32_e32 v15, v17, v9                                  ; 3e1e1311
	v_mac_f32_e32 v18, v24, v8                                  ; 3e241118
	v_mac_f32_e32 v19, v25, v8                                  ; 3e261119
	v_mac_f32_e32 v15, v21, v8                                  ; 3e1e1115
	v_mul_f32_e32 v12, v23, v15                                 ; 10181f17
	v_mad_f32 v13, v20, -v19, -v12                              ; d541000d c4322714
	v_mac_f32_e32 v12, v20, v19                                 ; 3e182714
	v_mad_f32 v13, v26, -v18, v13 mul:2                         ; d541000d 4c36251a
	v_mac_f32_e32 v12, v26, v18                                 ; 3e18251a
	v_mad_f32 v16, v19, -v13, -v20                              ; d5410010 c4521b13
	v_mad_f32 v15, v15, -v13, -v23                              ; d541000f c45e1b0f
	v_mad_f32 v14, v18, -v13, -v26                              ; d541000e c46a1b12
	v_max_f32_e32 v12, 0x3dcccccd, v12                          ; 201818ff 3dcccccd
	v_mul_f32_e32 v15, v15, v3                                  ; 101e070f
	v_mac_f32_e32 v15, v16, v27                                 ; 3e1e3710
	v_mac_f32_e32 v15, v14, v0                                  ; 3e1e010e
	v_max_f32_e32 v15, 0, v15                                   ; 201e1e80
	v_log_f32_e32 v15, v15                                      ; 7e1e4f0f
	v_mul_f32_e32 v15, 0x42000000, v15                          ; 101e1eff 42000000
	v_exp_f32_e32 v15, v15                                      ; 7e1e4b0f
	v_fma_mixlo_f16 v17, v12, v4, v15                           ; cc210011 043e090c
	v_fma_mixhi_f16 v17, v12, v5, v15                           ; cc220011 043e0b0c
	v_mac_f32_e32 v15, v12, v6                                  ; 3e1e0d0c
	v_cvt_pkrtz_f16_f32_e32 v15, v15, v7                        ; 5e1e0f0f
	exp mrt0 v17, v17, v15, v15 done compr vm                   ; f8001c0f 80800f11
	s_endpgm                                                    ; bf810000
