# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_mov_b32 m0, s0                                            ; befc0300
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x2                                                ; bfa10002
	s_buffer_load_dwordx4 s[16:19], s[4:7], 0xa0                ; f4280402 fa0000a0
	s_buffer_load_dwordx8 s[24:31], s[4:7], 0x80                ; f42c0602 fa000080
	s_buffer_load_dwordx2 s[0:1], s[4:7], 0xc0                  ; f4240002 fa0000c0
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v5, v0, attr0.x                         ; c8140000
	v_interp_p1_f32_e32 v6, v0, attr1.x                         ; c8180400
	v_interp_p1_f32_e32 v8, v0, attr1.y                         ; c8200500
	v_interp_p1_f32_e32 v9, v0, attr0.w                         ; c8240300
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v5, v1, attr0.x                         ; c8150001
	v_interp_p2_f32_e32 v6, v1, attr1.x                         ; c8190401
	v_interp_p2_f32_e32 v8, v1, attr1.y                         ; c8210501
	v_interp_p2_f32_e32 v9, v1, attr0.w                         ; c8250301
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cvt_f32_i32_e32 v13, s1                                   ; 7e1a0a01
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v10, v4, v8                                   ; 10141104
	v_mac_f32_e32 v10, v2, v6                                   ; 3e140d02
	v_mad_f32 v10, v5, v9, v10 mul:2                            ; d541000a 0c2a1305
	v_mad_f32 v5, v9, -v10, v5                                  ; d5410005 44161509
	v_mad_f32 v2, v6, -v10, v2                                  ; d5410002 440a1506
	v_mad_f32 v10, v8, -v10, v4                                 ; d541000a 44121508
	v_mul_f32_e32 v11, s16, v10                                 ; 10161410
	v_mul_f32_e32 v12, s17, v10                                 ; 10181411
	v_mul_f32_e32 v10, s18, v10                                 ; 10141412
	v_mov_b32_e32 v23, s0                                       ; 7e2e0200
	v_mac_f32_e32 v11, s28, v2                                  ; 3e16041c
	v_mac_f32_e32 v12, s29, v2                                  ; 3e18041d
	v_mac_f32_e32 v10, s30, v2                                  ; 3e14041e
	v_mac_f32_e32 v11, s24, v5                                  ; 3e160a18
	v_mac_f32_e32 v12, s25, v5                                  ; 3e180a19
	v_mac_f32_e32 v10, s26, v5                                  ; 3e140a1a
	v_cubetc_f32 v16, v11, -v12, -v10                           ; d5460010 c42a190b
	v_cubesc_f32 v15, v11, -v12, -v10                           ; d545000f c42a190b
	v_cubema_f32 v14, v11, -v12, -v10                           ; d547000e c42a190b
	v_cubeid_f32 v11, v11, -v12, -v10                           ; d544000b c42a190b
	v_rcp_f32_e64 v14, |v14|                                    ; d5aa010e 0000010e
	v_madmk_f32 v22, v13, 0x41000000, v11                       ; 402c170d 41000000
	v_madak_f32 v21, v16, v14, 0x3fc00000                       ; 422a1d10 3fc00000
	v_madak_f32 v20, v15, v14, 0x3fc00000                       ; 42281d0f 3fc00000
	image_sample_l v[17:19], v[20:23], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0900718 00221114
	v_interp_p1_f32_e32 v20, v0, attr2.y                        ; c8500900
	v_interp_p1_f32_e32 v22, v0, attr2.z                        ; c8580a00
	v_interp_p1_f32_e32 v23, v0, attr1.z                        ; c85c0600
	v_interp_p1_f32_e32 v3, v0, attr1.w                         ; c80c0700
	v_interp_p1_f32_e32 v0, v0, attr2.x                         ; c8000800
	v_interp_p2_f32_e32 v20, v1, attr2.y                        ; c8510901
	v_interp_p2_f32_e32 v22, v1, attr2.z                        ; c8590a01
	v_interp_p2_f32_e32 v23, v1, attr1.z                        ; c85d0601
	v_interp_p2_f32_e32 v3, v1, attr1.w                         ; c80d0701
	v_interp_p2_f32_e32 v0, v1, attr2.x                         ; c8010801
	v_mul_f32_e32 v21, v20, v20                                 ; 102a2914
	v_mul_f32_e32 v4, v3, v3                                    ; 10080703
	v_mac_f32_e32 v21, v22, v22                                 ; 3e2a2d16
	v_mac_f32_e32 v4, v0, v0                                    ; 3e080100
	v_mac_f32_e32 v21, v23, v23                                 ; 3e2a2f17
	v_mac_f32_e32 v4, v23, v23                                  ; 3e082f17
	v_rsq_f32_e32 v21, v21                                      ; 7e2a5d15
	v_rsq_f32_e32 v4, v4                                        ; 7e085d04
	v_mul_f32_e32 v20, v20, v21                                 ; 10282b14
	v_mul_f32_e32 v2, v23, v21                                  ; 10042b17
	v_mul_f32_e32 v22, v22, v21                                 ; 102c2b16
	v_mul_f32_e32 v23, v23, v4                                  ; 102e0917
	v_mul_f32_e32 v3, v3, v4                                    ; 10060903
	v_mul_f32_e32 v0, v0, v4                                    ; 10000900
	v_mul_f32_e32 v5, v22, v8                                   ; 100a1116
	v_mad_f32 v7, v20, -v6, -v5                                 ; d5410007 c4160d14
	v_mac_f32_e32 v5, v20, v6                                   ; 3e0a0d14
	v_mad_f32 v7, v2, -v9, v7 mul:2                             ; d5410007 4c1e1302
	v_mac_f32_e32 v5, v2, v9                                    ; 3e0a1302
	v_mad_f32 v10, v9, -v7, -v2                                 ; d541000a c40a0f09
	v_mad_f32 v11, v6, -v7, -v20                                ; d541000b c4520f06
	v_mad_f32 v8, v8, -v7, -v22                                 ; d5410008 c45a0f08
	v_max_f32_e32 v5, 0, v5                                     ; 200a0a80
	v_mul_f32_e32 v8, v8, v0                                    ; 10100108
	v_add_f32_e32 v5, 0.5, v5                                   ; 060a0af0
	v_mac_f32_e32 v8, v11, v3                                   ; 3e10070b
	v_mac_f32_e32 v8, v10, v23                                  ; 3e102f0a
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_log_f32_e32 v8, v8                                        ; 7e104f08
	v_mul_f32_e32 v8, 0x41800000, v8                            ; 101010ff 41800000
	v_exp_f32_e64 v8, v8 div:2                                  ; d5a50008 18000108
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v12, v17, v5, v8                            ; cc21000c 04220b11
	v_fma_mixhi_f16 v12, v18, v5, v8                            ; cc22000c 04220b12
	v_mac_f32_e32 v8, v19, v5                                   ; 3e100b13
	v_cvt_pkrtz_f16_f32_e64 v8, v8, 1.0                         ; d52f0008 0001e508
	exp mrt0 v12, v12, v8, v8 done compr vm                     ; f8001c0f 8080080c
	s_endpgm                                                    ; bf810000
