# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x2                                                ; bfa10002
	s_load_dwordx4 s[4:7], s[2:3], null                         ; f4080101 fa000000
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[16:19], s[2:3], 0x70                       ; f4080401 fa000070
	s_mov_b32 m0, s0                                            ; befc0300
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x2                                                ; bfa10002
	s_buffer_load_dwordx4 s[0:3], s[4:7], 0xa0                  ; f4280002 fa0000a0
	s_buffer_load_dwordx8 s[24:31], s[4:7], 0x80                ; f42c0602 fa000080
	s_buffer_load_dword s4, s[4:7], 0xc0                        ; f4200102 fa0000c0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	v_interp_p1_f32_e32 v5, v0, attr0.x                         ; c8140000
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v6, v0, attr1.x                         ; c8180400
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v8, v0, attr1.y                         ; c8200500
	v_interp_p1_f32_e32 v9, v0, attr0.w                         ; c8240300
	v_interp_p2_f32_e32 v5, v1, attr0.x                         ; c8150001
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v6, v1, attr1.x                         ; c8190401
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
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
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mov_b32_e32 v16, s4                                       ; 7e200204
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v10, v4, v8                                   ; 10141104
	v_mac_f32_e32 v10, v2, v6                                   ; 3e140d02
	v_mad_f32 v10, v5, v9, v10 mul:2                            ; d541000a 0c2a1305
	v_mad_f32 v5, v9, -v10, v5                                  ; d5410005 44161509
	v_mad_f32 v2, v6, -v10, v2                                  ; d5410002 440a1506
	v_mad_f32 v10, v8, -v10, v4                                 ; d541000a 44121508
	v_mul_f32_e32 v11, s0, v10                                  ; 10161400
	v_mul_f32_e32 v12, s1, v10                                  ; 10181401
	v_mul_f32_e32 v10, s2, v10                                  ; 10141402
	v_mac_f32_e32 v11, s28, v2                                  ; 3e16041c
	v_mac_f32_e32 v12, s29, v2                                  ; 3e18041d
	v_mac_f32_e32 v10, s30, v2                                  ; 3e14041e
	v_mac_f32_e32 v11, s24, v5                                  ; 3e160a18
	v_mac_f32_e32 v12, s25, v5                                  ; 3e180a19
	v_mac_f32_e32 v10, s26, v5                                  ; 3e140a1a
	v_cubetc_f32 v15, -v11, -v12, v10                           ; d546000f 642a190b
	v_cubesc_f32 v14, -v11, -v12, v10                           ; d545000e 642a190b
	v_cubeid_f32 v19, -v11, -v12, v10                           ; d5440013 642a190b
	v_cubema_f32 v13, -v11, -v12, v10                           ; d547000d 642a190b
	v_rcp_f32_e64 v13, |v13|                                    ; d5aa010d 0000010d
	v_madak_f32 v18, v15, v13, 0x3fc00000                       ; 42241b0f 3fc00000
	v_madak_f32 v17, v14, v13, 0x3fc00000                       ; 42221b0e 3fc00000
	image_sample_b v[16:18], v[16:19], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0940718 00821010
	v_interp_p1_f32_e32 v19, v0, attr2.y                        ; c84c0900
	v_interp_p1_f32_e32 v21, v0, attr2.z                        ; c8540a00
	v_interp_p1_f32_e32 v22, v0, attr1.z                        ; c8580600
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v0, v0, attr2.x                         ; c8000800
	v_interp_p2_f32_e32 v19, v1, attr2.y                        ; c84d0901
	v_interp_p2_f32_e32 v21, v1, attr2.z                        ; c8550a01
	v_interp_p2_f32_e32 v22, v1, attr1.z                        ; c8590601
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p2_f32_e32 v0, v1, attr2.x                         ; c8010801
	v_mul_f32_e32 v20, v19, v19                                 ; 10282713
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mac_f32_e32 v20, v21, v21                                 ; 3e282b15
	v_mac_f32_e32 v3, v0, v0                                    ; 3e060100
	v_mac_f32_e32 v20, v22, v22                                 ; 3e282d16
	v_mac_f32_e32 v3, v22, v22                                  ; 3e062d16
	v_rsq_f32_e32 v20, v20                                      ; 7e285d14
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v21, v21, v20                                 ; 102a2915
	v_mul_f32_e32 v23, v22, v20                                 ; 102e2916
	v_mul_f32_e32 v19, v19, v20                                 ; 10262913
	v_mul_f32_e32 v22, v22, v3                                  ; 102c0716
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v0, v0, v3                                    ; 10000700
	v_mul_f32_e32 v4, v21, v8                                   ; 10081115
	v_mad_f32 v5, v19, -v6, -v4                                 ; d5410005 c4120d13
	v_mac_f32_e32 v4, v19, v6                                   ; 3e080d13
	v_mad_f32 v5, v23, -v9, v5 mul:2                            ; d5410005 4c161317
	v_mac_f32_e32 v4, v23, v9                                   ; 3e081317
	v_mad_f32 v7, v9, -v5, -v23                                 ; d5410007 c45e0b09
	v_mad_f32 v10, v6, -v5, -v19                                ; d541000a c44e0b06
	v_mad_f32 v8, v8, -v5, -v21                                 ; d5410008 c4560b08
	v_max_f32_e32 v4, 0, v4                                     ; 20080880
	v_mul_f32_e32 v8, v8, v0                                    ; 10100108
	v_add_f32_e32 v4, 0.5, v4                                   ; 060808f0
	v_mac_f32_e32 v8, v10, v2                                   ; 3e10050a
	v_mac_f32_e32 v8, v7, v22                                   ; 3e102d07
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_log_f32_e32 v8, v8                                        ; 7e104f08
	v_mul_f32_e32 v8, 0x41800000, v8                            ; 101010ff 41800000
	v_exp_f32_e64 v8, v8 div:2                                  ; d5a50008 18000108
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_fma_mixlo_f16 v11, v16, v4, v8                            ; cc21000b 04220910
	v_fma_mixhi_f16 v11, v17, v4, v8                            ; cc22000b 04220911
	v_mac_f32_e32 v8, v18, v4                                   ; 3e100912
	v_cvt_pkrtz_f16_f32_e64 v8, v8, 1.0                         ; d52f0008 0001e508
	exp mrt0 v11, v11, v8, v8 done compr vm                     ; f8001c0f 8080080b
	s_endpgm                                                    ; bf810000
