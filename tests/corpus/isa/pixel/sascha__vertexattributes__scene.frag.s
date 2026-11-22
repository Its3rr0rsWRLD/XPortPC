# Pixel Shader
BB0:
	s_mov_b32 s6, s3                                            ; be860303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[16:19], s[2:3], 0x50                       ; f4080401 fa000050
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s5                                            ; befc0305
	v_interp_p1_f32_e32 v2, v0, attr1.x                         ; c8080400
	v_interp_p1_f32_e32 v3, v0, attr0.w                         ; c80c0300
	v_interp_p2_f32_e32 v2, v1, attr1.x                         ; c8090401
	v_interp_p2_f32_e32 v3, v1, attr0.w                         ; c80d0301
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v3, v2], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00820403 00000002
	s_cmp_eq_i32 s6, 1                                          ; bf008106
	v_mov_b32_e32 v23, v2                                       ; 7e2e0302
	v_mov_b32_e32 v22, v3                                       ; 7e2c0303
	s_cselect_b64 s[6:7], -1, 0                                 ; 858680c1
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_gt_f32_e32 vcc, s4, v7                                ; 7c080e04
	s_and_b64 s[4:5], vcc, s[6:7]                               ; 8784066a
	s_andn2_b64 exec, exec, s[4:5]                              ; 8afe047e
	s_andn2_b64 s[0:1], s[0:1], s[4:5]                          ; 8a800400
	s_cbranch_scc0 BB1                                          ; bf840082
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x60                        ; f40c0201 fa000060
	s_load_dwordx4 s[4:7], s[2:3], 0xb0                         ; f4080101 fa0000b0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[8:10], v[22:23], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220816
	v_interp_p1_f32_e32 v11, v0, attr0.y                        ; c82c0100
	v_interp_p1_f32_e32 v13, v0, attr0.z                        ; c8340200
	v_interp_p1_f32_e32 v14, v0, attr0.x                        ; c8380000
	v_interp_p1_f32_e32 v17, v0, attr3.x                        ; c8440c00
	v_interp_p1_f32_e32 v19, v0, attr3.y                        ; c84c0d00
	v_interp_p1_f32_e32 v20, v0, attr2.w                        ; c8500b00
	v_interp_p2_f32_e32 v11, v1, attr0.y                        ; c82d0101
	v_interp_p2_f32_e32 v13, v1, attr0.z                        ; c8350201
	v_interp_p2_f32_e32 v14, v1, attr0.x                        ; c8390001
	v_interp_p2_f32_e32 v17, v1, attr3.x                        ; c8450c01
	v_interp_p2_f32_e32 v19, v1, attr3.y                        ; c84d0d01
	v_interp_p2_f32_e32 v20, v1, attr2.w                        ; c8510b01
	v_mul_f32_e32 v12, v11, v11                                 ; 1018170b
	v_mul_f32_e32 v18, v17, v17                                 ; 10242311
	v_mul_f32_e32 v3, v13, v17                                  ; 1006230d
	v_mul_f32_e32 v22, v14, v19                                 ; 102c270e
	v_mul_f32_e32 v23, v11, v20                                 ; 102e290b
	v_mac_f32_e32 v12, v13, v13                                 ; 3e181b0d
	v_mac_f32_e32 v18, v19, v19                                 ; 3e242713
	v_mac_f32_e32 v12, v14, v14                                 ; 3e181d0e
	v_mac_f32_e32 v18, v20, v20                                 ; 3e242914
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_rsq_f32_e32 v18, v18                                      ; 7e245d12
	v_mul_f32_e32 v15, v14, v12                                 ; 101e190e
	v_mad_f32 v14, v14, v17, -v23                               ; d541000e 845e230e
	v_interp_p1_f32_e32 v23, v0, attr3.z                        ; c85c0e00
	v_interp_p2_f32_e32 v23, v1, attr3.z                        ; c85d0e01
	v_mul_f32_e32 v16, v11, v12                                 ; 1020190b
	v_mad_f32 v11, v11, v19, -v3                                ; d541000b 840e270b
	v_mul_f32_e32 v12, v13, v12                                 ; 1018190d
	v_mad_f32 v13, v13, v20, -v22                               ; d541000d 845a290d
	v_mul_f32_e32 v21, v20, v18                                 ; 102a2514
	v_mul_f32_e32 v2, v17, v18                                  ; 10042511
	v_interp_p1_f32_e32 v17, v0, attr2.z                        ; c8440a00
	v_interp_p2_f32_e32 v17, v1, attr2.z                        ; c8450a01
	v_interp_p1_f32_e32 v20, v0, attr1.z                        ; c8500600
	v_interp_p2_f32_e32 v20, v1, attr1.z                        ; c8510601
	v_mul_f32_e32 v18, v19, v18                                 ; 10242513
	v_interp_p1_f32_e32 v19, v0, attr2.x                        ; c84c0800
	v_interp_p2_f32_e32 v19, v1, attr2.x                        ; c84d0801
	v_mul_f32_e32 v14, v14, v23                                 ; 101c2f0e
	v_mul_f32_e32 v11, v11, v23                                 ; 10162f0b
	v_mul_f32_e32 v13, v13, v23                                 ; 101a2f0d
	v_interp_p1_f32_e32 v23, v0, attr2.y                        ; c85c0900
	v_interp_p2_f32_e32 v23, v1, attr2.y                        ; c85d0901
	v_mul_f32_e32 v22, v20, v20                                 ; 102c2914
	v_mul_f32_e32 v3, v23, v23                                  ; 10062f17
	v_mac_f32_e32 v3, v17, v17                                  ; 3e062311
	v_mac_f32_e32 v3, v19, v19                                  ; 3e062713
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v17, v17, v3                                  ; 10220711
	v_mul_f32_e32 v19, v19, v3                                  ; 10260713
	v_mul_f32_e32 v23, v23, v3                                  ; 102e0717
	v_interp_p1_f32_e32 v3, v0, attr1.w                         ; c80c0700
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v3, v1, attr1.w                         ; c80d0701
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mac_f32_e32 v22, v3, v3                                   ; 3e2c0703
	v_mac_f32_e32 v22, v0, v0                                   ; 3e2c0100
	v_rsq_f32_e32 v22, v22                                      ; 7e2c5d16
	v_mul_f32_e32 v3, v3, v22                                   ; 10062d03
	v_mul_f32_e32 v0, v0, v22                                   ; 10002d00
	v_mul_f32_e32 v20, v20, v22                                 ; 10282d14
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v10, 2.0, v10, -1.0                               ; d541000a 03ce14f4
	v_mad_f32 v9, 2.0, v9, -1.0                                 ; d5410009 03ce12f4
	v_mad_f32 v8, 2.0, v8, -1.0                                 ; d5410008 03ce10f4
	v_mul_f32_e32 v22, v9, v9                                   ; 102c1309
	v_mac_f32_e32 v22, v10, v10                                 ; 3e2c150a
	v_mac_f32_e32 v22, v8, v8                                   ; 3e2c1108
	v_rsq_f32_e32 v22, v22                                      ; 7e2c5d16
	v_mul_f32_e32 v8, v8, v22                                   ; 10102d08
	v_mul_f32_e32 v9, v9, v22                                   ; 10122d09
	v_mul_f32_e32 v10, v10, v22                                 ; 10142d0a
	v_mul_f32_e32 v16, v16, v10                                 ; 10201510
	v_mul_f32_e32 v12, v12, v10                                 ; 1018150c
	v_mul_f32_e32 v15, v15, v10                                 ; 101e150f
	v_mac_f32_e32 v16, v13, v9                                  ; 3e20130d
	v_mac_f32_e32 v12, v14, v9                                  ; 3e18130e
	v_mac_f32_e32 v15, v11, v9                                  ; 3e1e130b
	v_mac_f32_e32 v16, v2, v8                                   ; 3e201102
	v_mac_f32_e32 v12, v18, v8                                  ; 3e181112
	v_mac_f32_e32 v15, v21, v8                                  ; 3e1e1115
	v_mul_f32_e32 v1, v17, v12                                  ; 10021911
	v_mad_f32 v2, v23, -v16, -v1                                ; d5410002 c4062117
	v_mac_f32_e32 v1, v23, v16                                  ; 3e022117
	v_mad_f32 v2, v19, -v15, v2 mul:2                           ; d5410002 4c0a1f13
	v_mac_f32_e32 v1, v19, v15                                  ; 3e021f13
	v_mad_f32 v9, v16, -v2, -v23                                ; d5410009 c45e0510
	v_mad_f32 v12, v12, -v2, -v17                               ; d541000c c446050c
	v_mad_f32 v8, v15, -v2, -v19                                ; d5410008 c44e050f
	v_max_f32_e32 v1, 0x3dcccccd, v1                            ; 200202ff 3dcccccd
	v_mul_f32_e32 v12, v12, v3                                  ; 1018070c
	v_mac_f32_e32 v12, v9, v20                                  ; 3e182909
	v_mac_f32_e32 v12, v8, v0                                   ; 3e180108
	v_max_f32_e32 v12, 0, v12                                   ; 20181880
	v_log_f32_e32 v12, v12                                      ; 7e184f0c
	v_mul_f32_e32 v12, 0x42000000, v12                          ; 101818ff 42000000
	v_exp_f32_e32 v12, v12                                      ; 7e184b0c
	v_fma_mixlo_f16 v10, v1, v4, v12                            ; cc21000a 04320901
	v_fma_mixhi_f16 v10, v1, v5, v12                            ; cc22000a 04320b01
	v_mac_f32_e32 v12, v1, v6                                   ; 3e180d01
	v_cvt_pkrtz_f16_f32_e32 v12, v12, v7                        ; 5e180f0c
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	exp mrt0 v10, v10, v12, v12 done compr vm                   ; f8001c0f 80800c0a
	s_endpgm                                                    ; bf810000
BB1:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
