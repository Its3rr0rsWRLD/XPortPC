# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_cmp_eq_i32 s6, 0                                          ; bf008006
	s_cbranch_scc0 BB3                                          ; bf840012
BB1:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[16:19], s[2:3], 0x70                       ; f4080401 fa000070
	s_mov_b32 m0, s7                                            ; befc0307
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v3, v0, attr0.x                         ; c80c0000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v3, v1, attr0.x                         ; c80d0001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:6], [v3, v2], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00820403 00000002
	s_mov_b32 s3, s0                                            ; be830300
	s_mov_b32 s7, m0                                            ; be87037c
BB3:
	s_cmp_eq_i32 s6, 1                                          ; bf008106
	s_cbranch_scc0 BB6                                          ; bf840048
BB4:
	s_mov_b32 m0, s7                                            ; befc0307
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_interp_p1_f32_e32 v2, v0, attr0.w                         ; c8080300
	v_interp_p1_f32_e32 v4, v0, attr1.x                         ; c8100400
	v_interp_p1_f32_e32 v5, v0, attr0.z                         ; c8140200
	v_interp_p1_f32_e32 v6, v0, attr2.y                         ; c8180900
	v_interp_p1_f32_e32 v8, v0, attr2.z                         ; c8200a00
	v_interp_p1_f32_e32 v9, v0, attr2.x                         ; c8240800
	v_interp_p2_f32_e32 v2, v1, attr0.w                         ; c8090301
	v_interp_p2_f32_e32 v4, v1, attr1.x                         ; c8110401
	v_interp_p2_f32_e32 v5, v1, attr0.z                         ; c8150201
	v_interp_p2_f32_e32 v6, v1, attr2.y                         ; c8190901
	v_interp_p2_f32_e32 v8, v1, attr2.z                         ; c8210a01
	v_interp_p2_f32_e32 v9, v1, attr2.x                         ; c8250801
	v_interp_p1_f32_e32 v10, v0, attr1.z                        ; c8280600
	v_interp_p2_f32_e32 v10, v1, attr1.z                        ; c8290601
	v_interp_p1_f32_e32 v12, v0, attr1.w                        ; c8300700
	v_interp_p2_f32_e32 v12, v1, attr1.w                        ; c8310701
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mul_f32_e32 v11, v10, v10                                 ; 1016150a
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v11, v12, v12                                 ; 3e16190c
	v_mac_f32_e32 v3, v5, v5                                    ; 3e060b05
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_mac_f32_e32 v11, v0, v0                                   ; 3e160100
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_mul_f32_e32 v5, v5, v3                                    ; 100a0705
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v0, v0, v11                                   ; 10001700
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_mul_f32_e32 v13, v8, v4                                   ; 101a0908
	v_mad_f32 v14, v6, -v2, -v13                                ; d541000e c4360506
	v_mac_f32_e32 v13, v6, v2                                   ; 3e1a0506
	v_mad_f32 v14, v9, -v5, v14 mul:2                           ; d541000e 4c3a0b09
	v_mac_f32_e32 v13, v9, v5                                   ; 3e1a0b09
	v_mad_f32 v4, v4, -v14, -v8                                 ; d5410004 c4221d04
	v_mad_f32 v15, v5, -v14, -v9                                ; d541000f c4261d05
	v_mad_f32 v16, v2, -v14, -v6                                ; d5410010 c41a1d02
	v_max_f32_e32 v13, 0, v13                                   ; 201a1a80
	v_mul_f32_e32 v4, v4, v12                                   ; 10081904
	v_mac_f32_e32 v4, v16, v10                                  ; 3e081510
	v_mac_f32_e32 v4, v15, v0                                   ; 3e08010f
	v_max_f32_e32 v4, 0, v4                                     ; 20080880
	v_mul_f32_e32 v4, v4, v4                                    ; 10080904
	(then repeated 2 times)
	v_mad_f32 v17, s3, 0.5, v4                                  ; d5410011 0411e003
	v_mad_f32 v5, s4, 0.5, v4                                   ; d5410005 0411e004
	v_mad_f32 v6, s5, 0.5, v4                                   ; d5410006 0411e005
	v_mac_f32_e32 v17, s3, v13                                  ; 3e221a03
	v_mac_f32_e32 v5, s4, v13                                   ; 3e0a1a04
	v_mac_f32_e32 v6, s5, v13                                   ; 3e0c1a05
	v_mov_b32_e32 v4, v17                                       ; 7e080311
BB6:
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e64 v6, v6, 1.0                         ; d52f0006 0001e506
	v_cvt_pkrtz_f16_f32_e32 v4, v4, v5                          ; 5e080b04
	exp mrt0 v4, v4, v6, v6 done compr vm                       ; f8001c0f 80800604
	s_endpgm                                                    ; bf810000
