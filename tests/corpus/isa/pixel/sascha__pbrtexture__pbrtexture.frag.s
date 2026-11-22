# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x1a0                       ; f40c0201 fa0001a0
	s_load_dwordx4 s[4:7], s[2:3], 0x1f0                        ; f4080101 fa0001f0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr1.w                         ; c8080700
	v_interp_p1_f32_e32 v3, v0, attr1.z                         ; c80c0600
	v_interp_p2_f32_e32 v2, v1, attr1.w                         ; c8090701
	v_interp_p2_f32_e32 v3, v1, attr1.z                         ; c80d0601
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:6], [v3, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220403 00000002
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x260                       ; f40c0201 fa000260
	s_load_dwordx4 s[4:7], s[2:3], 0x2b0                        ; f4080101 fa0002b0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v7, [v3, v2], s[8:15], s[4:7] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00220703 00000002
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x2c0                       ; f40c0201 fa0002c0
	s_load_dwordx4 s[4:7], s[2:3], 0x310                        ; f4080101 fa000310
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v9, [v3, v2], s[8:15], s[4:7] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00220903 00000002
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x140                       ; f40c0201 fa000140
	s_load_dwordx4 s[4:7], s[2:3], 0x190                        ; f4080101 fa000190
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[10:12], [v3, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220a03 00000002
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx4 s[4:7], s[8:11], 0xc0                 ; f4280104 fa0000c0
	s_buffer_load_dwordx4 s[8:11], s[12:15], null               ; f4280206 fa000000
	v_interp_p1_f32_e32 v13, v0, attr1.x                        ; c8340400
	v_interp_p1_f32_e32 v15, v0, attr1.y                        ; c83c0500
	v_interp_p1_f32_e32 v16, v0, attr0.w                        ; c8400300
	v_interp_p1_f32_e32 v17, v0, attr2.y                        ; c8440900
	v_interp_p1_f32_e32 v19, v0, attr2.z                        ; c84c0a00
	v_interp_p1_f32_e32 v20, v0, attr2.x                        ; c8500800
	v_interp_p2_f32_e32 v13, v1, attr1.x                        ; c8350401
	v_interp_p2_f32_e32 v15, v1, attr1.y                        ; c83d0501
	v_interp_p2_f32_e32 v16, v1, attr0.w                        ; c8410301
	v_interp_p2_f32_e32 v17, v1, attr2.y                        ; c8450901
	v_interp_p2_f32_e32 v19, v1, attr2.z                        ; c84d0a01
	v_interp_p2_f32_e32 v20, v1, attr2.x                        ; c8510801
	v_mul_f32_e32 v14, v13, v13                                 ; 101c1b0d
	v_mul_f32_e32 v18, v17, v17                                 ; 10242311
	v_mac_f32_e32 v14, v15, v15                                 ; 3e1c1f0f
	v_mac_f32_e32 v18, v19, v19                                 ; 3e242713
	v_mac_f32_e32 v14, v16, v16                                 ; 3e1c2110
	v_mac_f32_e32 v18, v20, v20                                 ; 3e242914
	v_rsq_f32_e32 v14, v14                                      ; 7e1c5d0e
	v_rsq_f32_e32 v18, v18                                      ; 7e245d12
	v_mul_f32_e32 v16, v16, v14                                 ; 10201d10
	v_mul_f32_e32 v13, v13, v14                                 ; 101a1d0d
	v_mul_f32_e32 v15, v15, v14                                 ; 101e1d0f
	v_mul_f32_e32 v19, v19, v18                                 ; 10262513
	v_mul_f32_e32 v20, v20, v18                                 ; 10282514
	v_mul_f32_e32 v17, v17, v18                                 ; 10222511
	v_interp_p1_f32_e32 v25, v0, attr0.x                        ; c8640000
	v_interp_p1_f32_e32 v26, v0, attr0.y                        ; c8680100
	v_interp_p1_f32_e32 v0, v0, attr0.z                         ; c8000200
	v_interp_p2_f32_e32 v25, v1, attr0.x                        ; c8650001
	v_interp_p2_f32_e32 v26, v1, attr0.y                        ; c8690101
	v_interp_p2_f32_e32 v0, v1, attr0.z                         ; c8010201
	v_mul_f32_e32 v22, v16, v19                                 ; 102c2710
	v_mul_f32_e32 v23, v13, v20                                 ; 102e290d
	v_mul_f32_e32 v21, v15, v17                                 ; 102a230f
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v27, s4, v25                                  ; 06363204
	v_add_f32_e32 v28, s5, v26                                  ; 06383405
	v_add_f32_e32 v29, s6, v0                                   ; 063a0006
	v_mad_f32 v22, v15, v20, -v22                               ; d5410016 845a290f
	v_mad_f32 v23, v16, v17, -v23                               ; d5410017 845e2310
	v_mad_f32 v21, v13, v19, -v21                               ; d5410015 8456270d
	v_add_f32_e32 v31, s8, v25                                  ; 063e3208
	v_add_f32_e32 v32, s9, v26                                  ; 06403409
	v_mul_f32_e32 v30, v28, v28                                 ; 103c391c
	v_add_f32_e32 v33, s10, v0                                  ; 0642000a
	v_mul_f32_e32 v24, v22, v22                                 ; 10302d16
	v_mul_f32_e32 v34, v32, v32                                 ; 10444120
	v_mac_f32_e32 v30, v29, v29                                 ; 3e3c3b1d
	v_mac_f32_e32 v24, v23, v23                                 ; 3e302f17
	v_mac_f32_e32 v34, v33, v33                                 ; 3e444321
	v_mac_f32_e32 v30, v27, v27                                 ; 3e3c371b
	v_mac_f32_e32 v24, v21, v21                                 ; 3e302b15
	v_mac_f32_e32 v34, v31, v31                                 ; 3e443f1f
	v_rsq_f32_e32 v30, v30                                      ; 7e3c5d1e
	v_rsq_f32_e32 v24, v24                                      ; 7e305d18
	v_rsq_f32_e32 v34, v34                                      ; 7e445d22
	v_mul_f32_e32 v28, v28, v30                                 ; 10383d1c
	v_mul_f32_e32 v27, v27, v30                                 ; 10363d1b
	v_mul_f32_e32 v29, v29, v30                                 ; 103a3d1d
	v_mul_f32_e32 v21, v21, v24                                 ; 102a3115
	v_mul_f32_e32 v22, v22, v24                                 ; 102c3116
	v_mul_f32_e32 v23, v23, v24                                 ; 102e3117
	v_mul_f32_e32 v33, v33, v34                                 ; 10424521
	v_mul_f32_e32 v31, v31, v34                                 ; 103e451f
	v_mul_f32_e32 v32, v32, v34                                 ; 10404520
	v_add_f32_e32 v8, v29, v33                                  ; 0610431d
	v_add_f32_e32 v35, v27, v31                                 ; 06463f1b
	v_add_f32_e32 v1, v28, v32                                  ; 0602411c
	v_mul_f32_e32 v14, v1, v1                                   ; 101c0301
	v_mac_f32_e32 v14, v8, v8                                   ; 3e1c1108
	v_mac_f32_e32 v14, v35, v35                                 ; 3e1c4723
	v_rsq_f32_e32 v14, v14                                      ; 7e1c5d0e
	v_mul_f32_e32 v35, v35, v14                                 ; 10461d23
	v_mul_f32_e32 v1, v1, v14                                   ; 10021d01
	v_mul_f32_e32 v8, v8, v14                                   ; 10101d08
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mad_f32 v6, 2.0, v6, -1.0                                 ; d5410006 03ce0cf4
	v_mad_f32 v5, 2.0, v5, -1.0                                 ; d5410005 03ce0af4
	v_mad_f32 v4, 2.0, v4, -1.0                                 ; d5410004 03ce08f4
	v_mul_f32_e32 v15, v15, v6                                  ; 101e0d0f
	v_mul_f32_e32 v16, v16, v6                                  ; 10200d10
	v_mul_f32_e32 v13, v13, v6                                  ; 101a0d0d
	v_mac_f32_e32 v15, v23, v5                                  ; 3e1e0b17
	v_mac_f32_e32 v16, v21, v5                                  ; 3e200b15
	v_mac_f32_e32 v13, v22, v5                                  ; 3e1a0b16
	v_mac_f32_e32 v15, v19, v4                                  ; 3e1e0913
	v_mac_f32_e32 v16, v20, v4                                  ; 3e200914
	v_mac_f32_e32 v13, v17, v4                                  ; 3e1a0911
	v_mul_f32_e32 v17, v13, v13                                 ; 10221b0d
	v_mac_f32_e32 v17, v15, v15                                 ; 3e221f0f
	v_mac_f32_e32 v17, v16, v16                                 ; 3e222110
	v_rsq_f32_e32 v17, v17                                      ; 7e225d11
	v_mul_f32_e32 v16, v16, v17                                 ; 10202310
	v_mul_f32_e32 v13, v13, v17                                 ; 101a230d
	v_mul_f32_e32 v15, v15, v17                                 ; 101e230f
	v_mul_f32_e32 v18, v29, v15                                 ; 10241f1d
	v_mul_f32_e32 v8, v15, v8                                   ; 1010110f
	v_mul_f32_e32 v33, v15, v33                                 ; 1042430f
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_sub_f32_e32 v23, 1.0, v7                                  ; 082e0ef2
	v_mad_f32 v19, v28, -v13, -v18                              ; d5410013 c44a1b1c
	v_mac_f32_e32 v18, v28, v13                                 ; 3e241b1c
	v_mac_f32_e32 v8, v13, v1                                   ; 3e10030d
	v_mac_f32_e32 v33, v13, v32                                 ; 3e42410d
	v_mul_f32_e32 v24, 0x3d23d70a, v23                          ; 10302eff 3d23d70a
	v_mad_f32 v19, v27, -v16, v19 mul:2                         ; d5410013 4c4e211b
	v_mac_f32_e32 v18, v27, v16                                 ; 3e24211b
	v_mad_f32 v35, v16, v35, v8 clamp                           ; d5418023 04224710
	v_mad_f32 v31, v16, v31, v33 clamp                          ; d541801f 04863f10
	v_mad_f32 v20, v16, -v19, -v27                              ; d5410014 c46e2710
	v_mad_f32 v21, v13, -v19, -v28                              ; d5410015 c472270d
	v_mad_f32 v19, v15, -v19, -v29                              ; d5410013 c476270f
	v_add_f32_e64 v22, v18, 0 clamp                             ; d5038016 00010112
	v_cmp_lt_f32_e32 vcc, 0, v31                                ; 7c023e80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_log_f32_e32 v12, v12                                      ; 7e184f0c
	v_log_f32_e32 v10, v10                                      ; 7e144f0a
	v_log_f32_e32 v11, v11                                      ; 7e164f0b
	v_mul_f32_e32 v12, 0x400ccccd, v12                          ; 101818ff 400ccccd
	v_mul_f32_e32 v10, 0x400ccccd, v10                          ; 101414ff 400ccccd
	v_exp_f32_e32 v12, v12                                      ; 7e184b0c
	v_mul_f32_e32 v11, 0x400ccccd, v11                          ; 101616ff 400ccccd
	v_exp_f32_e32 v10, v10                                      ; 7e144b0a
	v_exp_f32_e32 v11, v11                                      ; 7e164b0b
	v_mad_f32 v30, v10, v7, v24                                 ; d541001e 04620f0a
	v_mad_f32 v32, v11, v7, v24                                 ; d5410020 04620f0b
	v_mac_f32_e32 v24, v12, v7                                  ; 3e300f0c
	s_and_saveexec_b64 s[0:1], vcc                              ; be80246a
	s_cbranch_execz BB4                                         ; bf880043
BB1:
	v_mul_f32_e32 v35, v35, v35                                 ; 10464723
	v_mul_f32_e32 v1, v9, v9                                    ; 10021309
	v_add_f32_e32 v6, 1.0, v9                                   ; 060c12f2
	v_sub_f32_e32 v4, 1.0, v35                                  ; 080846f2
	v_mul_f32_e32 v1, v1, v1                                    ; 10020301
	v_sub_f32_e32 v14, 1.0, v22                                 ; 081c2cf2
	v_mul_f32_e32 v6, v6, v6                                    ; 100c0d06
	v_mac_f32_e32 v4, v1, v35                                   ; 3e084701
	v_mul_f32_e32 v17, v14, v14                                 ; 10221d0e
	v_sub_f32_e32 v33, 1.0, v30                                 ; 08423cf2
	v_mul_f32_e32 v6, 0x3e000000, v6                            ; 100c0cff 3e000000
	v_sub_f32_e32 v34, 1.0, v32                                 ; 084440f2
	v_sub_f32_e32 v35, 1.0, v24                                 ; 084630f2
	v_mul_f32_e32 v5, 0x40490fdb, v4                            ; 100a08ff 40490fdb
	v_mul_f32_e32 v17, v17, v17                                 ; 10222311
	v_sub_f32_e32 v7, 1.0, v6                                   ; 080e0cf2
	v_mul_f32_e32 v5, v5, v4                                    ; 100a0905
	v_mul_f32_e32 v17, v17, v14                                 ; 10221d11
	v_mad_f32 v8, v31, v7, v6                                   ; d5410008 041a0f1f
	v_mac_f32_e32 v6, v22, v7                                   ; 3e0c0f16
	v_rcp_f32_e32 v5, v5                                        ; 7e0a5505
	v_mad_f32 v33, v33, v17, v30                                ; d5410021 047a2321
	v_mad_f32 v35, v35, v17, v24                                ; d5410023 04622323
	v_mad_f32 v34, v34, v17, v32                                ; d5410022 04822322
	v_rcp_f32_e32 v8, v8                                        ; 7e105508
	v_rcp_f32_e32 v6, v6                                        ; 7e0c5506
	v_mul_f32_e32 v1, v1, v5                                    ; 10020b01
	v_mul_f32_e32 v4, v33, v1                                   ; 10080321
	v_sub_f32_e32 v33, 1.0, v33                                 ; 084242f2
	v_mul_f32_e32 v5, v34, v1                                   ; 100a0322
	v_mul_f32_e32 v1, v35, v1                                   ; 10020323
	v_mul_f32_e32 v8, v31, v8                                   ; 1010111f
	v_sub_f32_e32 v34, 1.0, v34                                 ; 084444f2
	v_mul_f32_e32 v6, v22, v6                                   ; 100c0d16
	v_sub_f32_e32 v35, 1.0, v35                                 ; 084646f2
	v_mul_f32_e32 v33, 0x3ea2f983, v33                          ; 104242ff 3ea2f983
	v_mul_f32_e32 v34, 0x3ea2f983, v34                          ; 104444ff 3ea2f983
	v_mul_f32_e32 v8, v8, v6                                    ; 10100d08
	v_mul_f32_e32 v6, 4.0, v31                                  ; 100c3ef6
	v_mul_f32_e32 v35, 0x3ea2f983, v35                          ; 104646ff 3ea2f983
	v_mul_f32_e32 v33, v33, v23                                 ; 10422f21
	v_mul_f32_e32 v34, v34, v23                                 ; 10442f22
	v_mul_f32_e32 v1, v1, v8                                    ; 10021101
	v_mul_f32_e32 v4, v4, v8                                    ; 10081104
	v_mul_f32_e32 v5, v5, v8                                    ; 100a1105
	v_madak_f32 v6, v6, v22, 0x3a83126f                         ; 420c2d06 3a83126f
	v_mul_f32_e32 v35, v35, v23                                 ; 10462f23
	v_rcp_f32_e32 v6, v6                                        ; 7e0c5506
	v_mul_f32_e32 v1, v1, v6                                    ; 10020d01
	v_mul_f32_e32 v4, v4, v6                                    ; 10080d04
	v_mul_f32_e32 v5, v5, v6                                    ; 100a0d05
	v_mac_f32_e32 v1, v35, v12                                  ; 3e021923
	v_mac_f32_e32 v4, v33, v10                                  ; 3e081521
	v_mac_f32_e32 v5, v34, v11                                  ; 3e0a1722
	v_mul_f32_e32 v1, v1, v31                                   ; 10023f01
	v_mul_f32_e32 v4, v4, v31                                   ; 10083f04
	v_mul_f32_e32 v5, v5, v31                                   ; 100a3f05
BB4:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	v_lshrrev_b64 v[4:5], 0, 0                                  ; d7000004 00010080
BB6:
	s_buffer_load_dwordx4 s[4:7], s[12:15], 0x10                ; f4280106 fa000010
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v6, s4, v25                                   ; 060c3204
	v_add_f32_e32 v7, s5, v26                                   ; 060e3405
	v_add_f32_e32 v8, s6, v0                                    ; 06100006
	v_mul_f32_e32 v14, v7, v7                                   ; 101c0f07
	v_mac_f32_e32 v14, v8, v8                                   ; 3e1c1108
	v_mac_f32_e32 v14, v6, v6                                   ; 3e1c0d06
	v_rsq_f32_e32 v14, v14                                      ; 7e1c5d0e
	v_mul_f32_e32 v6, v6, v14                                   ; 100c1d06
	v_mul_f32_e32 v7, v7, v14                                   ; 100e1d07
	v_mul_f32_e32 v8, v8, v14                                   ; 10101d08
	v_add_f32_e32 v17, v27, v6                                  ; 06220d1b
	v_add_f32_e32 v31, v28, v7                                  ; 063e0f1c
	v_add_f32_e32 v33, v29, v8                                  ; 0642111d
	v_mul_f32_e32 v8, v15, v8                                   ; 1010110f
	v_mul_f32_e32 v34, v31, v31                                 ; 10443f1f
	v_mac_f32_e32 v8, v13, v7                                   ; 3e100f0d
	v_mac_f32_e32 v34, v33, v33                                 ; 3e444321
	v_mad_f32 v6, v16, v6, v8 clamp                             ; d5418006 04220d10
	v_mac_f32_e32 v34, v17, v17                                 ; 3e442311
	v_rsq_f32_e32 v34, v34                                      ; 7e445d22
	v_mul_f32_e32 v17, v17, v34                                 ; 10224511
	v_mul_f32_e32 v31, v31, v34                                 ; 103e451f
	v_mul_f32_e32 v33, v33, v34                                 ; 10424521
	v_mul_f32_e32 v33, v15, v33                                 ; 1042430f
	v_mac_f32_e32 v33, v13, v31                                 ; 3e423f0d
	v_mad_f32 v17, v16, v17, v33 clamp                          ; d5418011 04862310
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v6                                     ; 7c220c80
	s_cbranch_execz BB10                                        ; bf880043
BB7:
	v_mul_f32_e32 v17, v17, v17                                 ; 10222311
	v_mul_f32_e32 v7, v9, v9                                    ; 100e1309
	v_sub_f32_e32 v8, 1.0, v17                                  ; 081022f2
	v_mul_f32_e32 v7, v7, v7                                    ; 100e0f07
	v_mac_f32_e32 v8, v7, v17                                   ; 3e102307
	v_add_f32_e32 v17, 1.0, v9                                  ; 062212f2
	v_sub_f32_e32 v34, 1.0, v22                                 ; 08442cf2
	v_mul_f32_e32 v14, 0x40490fdb, v8                           ; 101c10ff 40490fdb
	v_mul_f32_e32 v17, v17, v17                                 ; 10222311
	v_mul_f32_e32 v35, v34, v34                                 ; 10464522
	v_mul_f32_e32 v14, v14, v8                                  ; 101c110e
	v_sub_f32_e32 v8, 1.0, v30                                  ; 08103cf2
	v_mul_f32_e32 v17, 0x3e000000, v17                          ; 102222ff 3e000000
	v_mul_f32_e32 v35, v35, v35                                 ; 10464723
	v_rcp_f32_e32 v14, v14                                      ; 7e1c550e
	v_sub_f32_e32 v31, 1.0, v17                                 ; 083e22f2
	v_mul_f32_e32 v35, v35, v34                                 ; 10464523
	v_mad_f32 v33, v6, v31, v17                                 ; d5410021 04463f06
	v_mac_f32_e32 v17, v22, v31                                 ; 3e223f16
	v_mad_f32 v8, v8, v35, v30                                  ; d5410008 047a4708
	v_mul_f32_e32 v7, v7, v14                                   ; 100e1d07
	v_sub_f32_e32 v14, 1.0, v32                                 ; 081c40f2
	v_rcp_f32_e32 v33, v33                                      ; 7e425521
	v_rcp_f32_e32 v17, v17                                      ; 7e225511
	v_mul_f32_e32 v31, v8, v7                                   ; 103e0f08
	v_mad_f32 v14, v14, v35, v32                                ; d541000e 0482470e
	v_mul_f32_e32 v33, v6, v33                                  ; 10424306
	v_mul_f32_e32 v34, v14, v7                                  ; 10440f0e
	v_sub_f32_e32 v8, 1.0, v8                                   ; 081010f2
	v_mul_f32_e32 v17, v22, v17                                 ; 10222316
	v_sub_f32_e32 v14, 1.0, v14                                 ; 081c1cf2
	v_mul_f32_e32 v8, 0x3ea2f983, v8                            ; 101010ff 3ea2f983
	v_mul_f32_e32 v33, v33, v17                                 ; 10422321
	v_sub_f32_e32 v17, 1.0, v24                                 ; 082230f2
	v_mul_f32_e32 v14, 0x3ea2f983, v14                          ; 101c1cff 3ea2f983
	v_mul_f32_e32 v8, v8, v23                                   ; 10102f08
	v_mul_f32_e32 v34, v34, v33                                 ; 10444322
	v_mul_f32_e32 v31, v31, v33                                 ; 103e431f
	v_mad_f32 v17, v17, v35, v24                                ; d5410011 04624711
	v_mul_f32_e32 v35, 4.0, v6                                  ; 10460cf6
	v_mul_f32_e32 v14, v14, v23                                 ; 101c2f0e
	v_mul_f32_e32 v7, v17, v7                                   ; 100e0f11
	v_sub_f32_e32 v17, 1.0, v17                                 ; 082222f2
	v_madak_f32 v35, v35, v22, 0x3a83126f                       ; 42462d23 3a83126f
	v_mul_f32_e32 v7, v7, v33                                   ; 100e4307
	v_mul_f32_e32 v17, 0x3ea2f983, v17                          ; 102222ff 3ea2f983
	v_rcp_f32_e32 v35, v35                                      ; 7e465523
	v_mul_f32_e32 v17, v17, v23                                 ; 10222f11
	v_mul_f32_e32 v31, v31, v35                                 ; 103e471f
	v_mul_f32_e32 v34, v34, v35                                 ; 10444722
	v_mul_f32_e32 v7, v7, v35                                   ; 100e4707
	v_mac_f32_e32 v31, v8, v10                                  ; 3e3e1508
	v_mac_f32_e32 v34, v14, v11                                 ; 3e44170e
	v_mac_f32_e32 v7, v17, v12                                  ; 3e0e1911
	v_mul_f32_e32 v31, v31, v6                                  ; 103e0d1f
	v_mul_f32_e32 v34, v34, v6                                  ; 10440d22
	v_mul_f32_e32 v7, v7, v6                                    ; 100e0d07
BB10:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_mov_b32_e32 v7, 0                                         ; 7e0e0280
	v_mov_b32_e32 v31, 0                                        ; 7e3e0280
	v_mov_b32_e32 v34, 0                                        ; 7e440280
BB12:
	s_buffer_load_dwordx4 s[4:7], s[12:15], 0x20                ; f4280106 fa000020
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_add_f32_e32 v4, v4, v31                                   ; 06083f04
	v_add_f32_e32 v1, v1, v7                                    ; 06020f01
	v_add_f32_e32 v5, v5, v34                                   ; 060a4505
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v6, s4, v25                                   ; 060c3204
	v_add_f32_e32 v7, s5, v26                                   ; 060e3405
	v_add_f32_e32 v8, s6, v0                                    ; 06100006
	v_mul_f32_e32 v14, v7, v7                                   ; 101c0f07
	v_mac_f32_e32 v14, v8, v8                                   ; 3e1c1108
	v_mac_f32_e32 v14, v6, v6                                   ; 3e1c0d06
	v_rsq_f32_e32 v14, v14                                      ; 7e1c5d0e
	v_mul_f32_e32 v6, v6, v14                                   ; 100c1d06
	v_mul_f32_e32 v7, v7, v14                                   ; 100e1d07
	v_mul_f32_e32 v8, v8, v14                                   ; 10101d08
	v_add_f32_e32 v17, v27, v6                                  ; 06220d1b
	v_add_f32_e32 v31, v28, v7                                  ; 063e0f1c
	v_add_f32_e32 v33, v29, v8                                  ; 0642111d
	v_mul_f32_e32 v8, v15, v8                                   ; 1010110f
	v_mul_f32_e32 v34, v31, v31                                 ; 10443f1f
	v_mac_f32_e32 v8, v13, v7                                   ; 3e100f0d
	v_mac_f32_e32 v34, v33, v33                                 ; 3e444321
	v_mad_f32 v6, v16, v6, v8 clamp                             ; d5418006 04220d10
	v_mac_f32_e32 v34, v17, v17                                 ; 3e442311
	v_rsq_f32_e32 v34, v34                                      ; 7e445d22
	v_mul_f32_e32 v17, v17, v34                                 ; 10224511
	v_mul_f32_e32 v31, v31, v34                                 ; 103e451f
	v_mul_f32_e32 v33, v33, v34                                 ; 10424521
	v_mul_f32_e32 v33, v15, v33                                 ; 1042430f
	v_mac_f32_e32 v33, v13, v31                                 ; 3e423f0d
	v_mad_f32 v17, v16, v17, v33 clamp                          ; d5418011 04862310
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v6                                     ; 7c220c80
	s_cbranch_execz BB16                                        ; bf880043
BB13:
	v_mul_f32_e32 v17, v17, v17                                 ; 10222311
	v_mul_f32_e32 v7, v9, v9                                    ; 100e1309
	v_sub_f32_e32 v8, 1.0, v17                                  ; 081022f2
	v_mul_f32_e32 v7, v7, v7                                    ; 100e0f07
	v_mac_f32_e32 v8, v7, v17                                   ; 3e102307
	v_add_f32_e32 v17, 1.0, v9                                  ; 062212f2
	v_sub_f32_e32 v34, 1.0, v22                                 ; 08442cf2
	v_mul_f32_e32 v14, 0x40490fdb, v8                           ; 101c10ff 40490fdb
	v_mul_f32_e32 v17, v17, v17                                 ; 10222311
	v_mul_f32_e32 v35, v34, v34                                 ; 10464522
	v_mul_f32_e32 v14, v14, v8                                  ; 101c110e
	v_sub_f32_e32 v8, 1.0, v30                                  ; 08103cf2
	v_mul_f32_e32 v17, 0x3e000000, v17                          ; 102222ff 3e000000
	v_mul_f32_e32 v35, v35, v35                                 ; 10464723
	v_rcp_f32_e32 v14, v14                                      ; 7e1c550e
	v_sub_f32_e32 v31, 1.0, v17                                 ; 083e22f2
	v_mul_f32_e32 v35, v35, v34                                 ; 10464523
	v_mad_f32 v33, v6, v31, v17                                 ; d5410021 04463f06
	v_mac_f32_e32 v17, v22, v31                                 ; 3e223f16
	v_mad_f32 v8, v8, v35, v30                                  ; d5410008 047a4708
	v_mul_f32_e32 v7, v7, v14                                   ; 100e1d07
	v_sub_f32_e32 v14, 1.0, v32                                 ; 081c40f2
	v_rcp_f32_e32 v33, v33                                      ; 7e425521
	v_rcp_f32_e32 v17, v17                                      ; 7e225511
	v_mul_f32_e32 v31, v8, v7                                   ; 103e0f08
	v_mad_f32 v14, v14, v35, v32                                ; d541000e 0482470e
	v_mul_f32_e32 v33, v6, v33                                  ; 10424306
	v_mul_f32_e32 v34, v14, v7                                  ; 10440f0e
	v_sub_f32_e32 v8, 1.0, v8                                   ; 081010f2
	v_mul_f32_e32 v17, v22, v17                                 ; 10222316
	v_sub_f32_e32 v14, 1.0, v14                                 ; 081c1cf2
	v_mul_f32_e32 v8, 0x3ea2f983, v8                            ; 101010ff 3ea2f983
	v_mul_f32_e32 v33, v33, v17                                 ; 10422321
	v_sub_f32_e32 v17, 1.0, v24                                 ; 082230f2
	v_mul_f32_e32 v14, 0x3ea2f983, v14                          ; 101c1cff 3ea2f983
	v_mul_f32_e32 v8, v8, v23                                   ; 10102f08
	v_mul_f32_e32 v34, v34, v33                                 ; 10444322
	v_mul_f32_e32 v31, v31, v33                                 ; 103e431f
	v_mad_f32 v17, v17, v35, v24                                ; d5410011 04624711
	v_mul_f32_e32 v35, 4.0, v6                                  ; 10460cf6
	v_mul_f32_e32 v14, v14, v23                                 ; 101c2f0e
	v_mul_f32_e32 v7, v17, v7                                   ; 100e0f11
	v_sub_f32_e32 v17, 1.0, v17                                 ; 082222f2
	v_madak_f32 v35, v35, v22, 0x3a83126f                       ; 42462d23 3a83126f
	v_mul_f32_e32 v7, v7, v33                                   ; 100e4307
	v_mul_f32_e32 v17, 0x3ea2f983, v17                          ; 102222ff 3ea2f983
	v_rcp_f32_e32 v35, v35                                      ; 7e465523
	v_mul_f32_e32 v17, v17, v23                                 ; 10222f11
	v_mul_f32_e32 v31, v31, v35                                 ; 103e471f
	v_mul_f32_e32 v34, v34, v35                                 ; 10444722
	v_mul_f32_e32 v7, v7, v35                                   ; 100e4707
	v_mac_f32_e32 v31, v8, v10                                  ; 3e3e1508
	v_mac_f32_e32 v34, v14, v11                                 ; 3e44170e
	v_mac_f32_e32 v7, v17, v12                                  ; 3e0e1911
	v_mul_f32_e32 v31, v31, v6                                  ; 103e0d1f
	v_mul_f32_e32 v34, v34, v6                                  ; 10440d22
	v_mul_f32_e32 v7, v7, v6                                    ; 100e0d07
BB16:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_mov_b32_e32 v7, 0                                         ; 7e0e0280
	v_mov_b32_e32 v31, 0                                        ; 7e3e0280
	v_mov_b32_e32 v34, 0                                        ; 7e440280
BB18:
	s_buffer_load_dwordx4 s[4:7], s[12:15], 0x30                ; f4280106 fa000030
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_add_f32_e32 v4, v4, v31                                   ; 06083f04
	v_add_f32_e32 v1, v1, v7                                    ; 06020f01
	v_add_f32_e32 v5, v5, v34                                   ; 060a4505
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_add_f32_e32 v25, s4, v25                                  ; 06323204
	v_add_f32_e32 v26, s5, v26                                  ; 06343405
	v_add_f32_e32 v0, s6, v0                                    ; 06000006
	v_mul_f32_e32 v6, v26, v26                                  ; 100c351a
	v_mac_f32_e32 v6, v0, v0                                    ; 3e0c0100
	v_mac_f32_e32 v6, v25, v25                                  ; 3e0c3319
	v_rsq_f32_e32 v6, v6                                        ; 7e0c5d06
	v_mul_f32_e32 v25, v25, v6                                  ; 10320d19
	v_mul_f32_e32 v26, v26, v6                                  ; 10340d1a
	v_mul_f32_e32 v0, v0, v6                                    ; 10000d00
	v_add_f32_e32 v27, v27, v25                                 ; 0636331b
	v_add_f32_e32 v28, v28, v26                                 ; 0638351c
	v_add_f32_e32 v29, v29, v0                                  ; 063a011d
	v_mul_f32_e32 v0, v15, v0                                   ; 1000010f
	v_mul_f32_e32 v7, v28, v28                                  ; 100e391c
	v_mac_f32_e32 v0, v13, v26                                  ; 3e00350d
	v_mac_f32_e32 v7, v29, v29                                  ; 3e0e3b1d
	v_mad_f32 v25, v16, v25, v0 clamp                           ; d5418019 04023310
	v_mac_f32_e32 v7, v27, v27                                  ; 3e0e371b
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_mul_f32_e32 v27, v27, v7                                  ; 10360f1b
	v_mul_f32_e32 v28, v28, v7                                  ; 10380f1c
	v_mul_f32_e32 v29, v29, v7                                  ; 103a0f1d
	v_mul_f32_e32 v29, v15, v29                                 ; 103a3b0f
	v_mac_f32_e32 v29, v13, v28                                 ; 3e3a390d
	v_mad_f32 v27, v16, v27, v29 clamp                          ; d541801b 04763710
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_lt_f32_e32 0, v25                                    ; 7c223280
	s_cbranch_execz BB22                                        ; bf880043
BB19:
	v_mul_f32_e32 v27, v27, v27                                 ; 1036371b
	v_mul_f32_e32 v0, v9, v9                                    ; 10001309
	v_add_f32_e32 v8, 1.0, v9                                   ; 061012f2
	v_sub_f32_e32 v6, 1.0, v27                                  ; 080c36f2
	v_mul_f32_e32 v0, v0, v0                                    ; 10000100
	v_sub_f32_e32 v26, 1.0, v22                                 ; 08342cf2
	v_mul_f32_e32 v8, v8, v8                                    ; 10101108
	v_mac_f32_e32 v6, v0, v27                                   ; 3e0c3700
	v_mul_f32_e32 v27, v26, v26                                 ; 1036351a
	v_sub_f32_e32 v28, 1.0, v30                                 ; 08383cf2
	v_mul_f32_e32 v8, 0x3e000000, v8                            ; 101010ff 3e000000
	v_sub_f32_e32 v29, 1.0, v32                                 ; 083a40f2
	v_sub_f32_e32 v31, 1.0, v24                                 ; 083e30f2
	v_mul_f32_e32 v7, 0x40490fdb, v6                            ; 100e0cff 40490fdb
	v_mul_f32_e32 v27, v27, v27                                 ; 1036371b
	v_sub_f32_e32 v14, 1.0, v8                                  ; 081c10f2
	v_mul_f32_e32 v7, v7, v6                                    ; 100e0d07
	v_mul_f32_e32 v27, v27, v26                                 ; 1036351b
	v_mad_f32 v17, v25, v14, v8                                 ; d5410011 04221d19
	v_mac_f32_e32 v8, v22, v14                                  ; 3e101d16
	v_rcp_f32_e32 v7, v7                                        ; 7e0e5507
	v_mad_f32 v28, v28, v27, v30                                ; d541001c 047a371c
	v_mad_f32 v31, v31, v27, v24                                ; d541001f 0462371f
	v_mad_f32 v29, v29, v27, v32                                ; d541001d 0482371d
	v_rcp_f32_e32 v17, v17                                      ; 7e225511
	v_rcp_f32_e32 v8, v8                                        ; 7e105508
	v_mul_f32_e32 v35, 4.0, v25                                 ; 104632f6
	v_mul_f32_e32 v0, v0, v7                                    ; 10000f00
	v_madak_f32 v35, v35, v22, 0x3a83126f                       ; 42462d23 3a83126f
	v_mul_f32_e32 v17, v25, v17                                 ; 10222319
	v_mul_f32_e32 v33, v28, v0                                  ; 1042011c
	v_sub_f32_e32 v28, 1.0, v28                                 ; 083838f2
	v_mul_f32_e32 v34, v29, v0                                  ; 1044011d
	v_mul_f32_e32 v0, v31, v0                                   ; 1000011f
	v_sub_f32_e32 v29, 1.0, v29                                 ; 083a3af2
	v_mul_f32_e32 v8, v22, v8                                   ; 10101116
	v_sub_f32_e32 v31, 1.0, v31                                 ; 083e3ef2
	v_rcp_f32_e32 v35, v35                                      ; 7e465523
	v_mul_f32_e32 v28, 0x3ea2f983, v28                          ; 103838ff 3ea2f983
	v_mul_f32_e32 v29, 0x3ea2f983, v29                          ; 103a3aff 3ea2f983
	v_mul_f32_e32 v17, v17, v8                                  ; 10221111
	v_mul_f32_e32 v31, 0x3ea2f983, v31                          ; 103e3eff 3ea2f983
	v_mul_f32_e32 v28, v28, v23                                 ; 10382f1c
	v_mul_f32_e32 v29, v29, v23                                 ; 103a2f1d
	v_mul_f32_e32 v0, v0, v17                                   ; 10002300
	v_mul_f32_e32 v33, v33, v17                                 ; 10422321
	v_mul_f32_e32 v34, v34, v17                                 ; 10442322
	v_mul_f32_e32 v31, v31, v23                                 ; 103e2f1f
	v_mul_f32_e32 v0, v0, v35                                   ; 10004700
	v_mul_f32_e32 v33, v33, v35                                 ; 10424721
	v_mul_f32_e32 v34, v34, v35                                 ; 10444722
	v_mac_f32_e32 v0, v31, v12                                  ; 3e00191f
	v_mac_f32_e32 v33, v28, v10                                 ; 3e42151c
	v_mac_f32_e32 v34, v29, v11                                 ; 3e44171d
	v_mul_f32_e32 v0, v0, v25                                   ; 10003300
	v_mul_f32_e32 v33, v33, v25                                 ; 10423321
	v_mul_f32_e32 v34, v34, v25                                 ; 10443322
BB22:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_mov_b32_e32 v0, 0                                         ; 7e000280
	v_lshrrev_b64 v[33:34], 0, 0                                ; d7000021 00010080
BB24:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_clause 0x7                                                ; bfa10007
	s_load_dwordx8 s[16:23], s[2:3], 0x80                       ; f40c0401 fa000080
	s_load_dwordx4 s[4:7], s[2:3], 0xd0                         ; f4080101 fa0000d0
	s_load_dwordx8 s[24:31], s[2:3], 0xe0                       ; f40c0601 fa0000e0
	s_load_dwordx4 s[8:11], s[2:3], 0x130                       ; f4080201 fa000130
	s_load_dwordx8 s[32:39], s[2:3], 0x20                       ; f40c0801 fa000020
	s_load_dwordx4 s[40:43], s[2:3], 0x70                       ; f4080a01 fa000070
	s_load_dwordx8 s[48:55], s[2:3], 0x200                      ; f40c0c01 fa000200
	s_load_dwordx4 s[0:3], s[2:3], 0x250                        ; f4080001 fa000250
	v_max_f32_e32 v8, 0, v18                                    ; 20102480
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[6:7], v[8:9], s[16:23], s[4:7] dmask:0x3 dim:SQ_RSRC_IMG_2D ; f0800308 00240608
	v_cubema_f32 v14, v20, v21, v19                             ; d547000e 044e2b14
	v_cubesc_f32 v17, v20, v21, v19                             ; d5450011 044e2b14
	v_cubetc_f32 v18, v20, v21, v19                             ; d5460012 044e2b14
	v_cubeid_f32 v28, v20, v21, v19                             ; d544001c 044e2b14
	v_mul_f32_e32 v19, 0x41100000, v9                           ; 102612ff 41100000
	v_rcp_f32_e64 v14, |v14|                                    ; d5aa010e 0000010e
	v_floor_f32_e32 v29, v19                                    ; 7e3a4913
	v_ceil_f32_e32 v20, v19                                     ; 7e284513
	v_madak_f32 v26, v17, v14, 0x3fc00000                       ; 42341d11 3fc00000
	v_madak_f32 v27, v18, v14, 0x3fc00000                       ; 42361d12 3fc00000
	v_mov_b32_e32 v14, v16                                      ; 7e1c0310
	image_sample_l v[16:18], v[26:29], s[24:31], s[8:11] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0900718 0046101a
	image_sample_l  v[20:22], [v26, v27, v28, v20], s[24:31], s[8:11] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f090071a 0046141a 00141c1b
	v_cubema_f32 v25, v14, v13, v15                             ; d5470019 043e1b0e
	v_cubesc_f32 v26, v14, v13, v15                             ; d545001a 043e1b0e
	v_cubetc_f32 v27, v14, v13, v15                             ; d546001b 043e1b0e
	v_cubeid_f32 v15, v14, v13, v15                             ; d544000f 043e1b0e
	v_rcp_f32_e64 v25, |v25|                                    ; d5aa0119 00000119
	v_madak_f32 v13, v26, v25, 0x3fc00000                       ; 421a331a 3fc00000
	v_madak_f32 v14, v27, v25, 0x3fc00000                       ; 421c331b 3fc00000
	image_sample v[25:27], v[13:15], s[32:39], s[40:43] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0800718 0148190d
	image_sample  v3, [v3, v2], s[48:55], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 000c0303 00000002
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_buffer_load_dwordx2 s[0:1], s[12:15], 0x40                ; f4240006 fa000040
	v_add_f32_e32 v4, v4, v33                                   ; 06084304
	v_add_f32_e32 v5, v5, v34                                   ; 060a4505
	v_add_f32_e32 v1, v1, v0                                    ; 06020101
	v_sub_f32_e32 v19, v19, v29                                 ; 08263b13
	v_sub_f32_e32 v9, 1.0, v9                                   ; 081212f2
	v_sub_f32_e32 v8, 1.0, v8                                   ; 081010f2
	s_mov_b32 s2, 0x3e19999a                                    ; be8203ff 3e19999a
	v_max_f32_e32 v28, v9, v30                                  ; 20383d09
	v_max_f32_e32 v29, v9, v32                                  ; 203a4109
	v_max_f32_e32 v9, v9, v24                                   ; 20123109
	v_mul_f32_e32 v31, v8, v8                                   ; 103e1108
	v_sub_f32_e32 v28, v28, v30                                 ; 08383d1c
	v_sub_f32_e32 v29, v29, v32                                 ; 083a411d
	v_sub_f32_e32 v9, v9, v24                                   ; 08123109
	v_mul_f32_e32 v31, v31, v31                                 ; 103e3f1f
	v_mul_f32_e32 v31, v31, v8                                  ; 103e111f
	v_mac_f32_e32 v24, v9, v31                                  ; 3e303f09
	v_mac_f32_e32 v30, v28, v31                                 ; 3e3c3f1c
	v_mac_f32_e32 v32, v29, v31                                 ; 3e403f1d
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mad_f32 v33, v30, v6, v7                                  ; d5410021 041e0d1e
	v_sub_f32_e32 v30, 1.0, v30                                 ; 083c3cf2
	v_mad_f32 v34, v32, v6, v7                                  ; d5410022 041e0d20
	v_sub_f32_e32 v32, 1.0, v32                                 ; 084040f2
	v_mac_f32_e32 v7, v24, v6                                   ; 3e0e0d18
	v_sub_f32_e32 v24, 1.0, v24                                 ; 083030f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_rcp_f32_e32 v35, s1                                       ; 7e465401
	v_mul_f32_e32 v30, v30, v23                                 ; 103c2f1e
	v_mul_f32_e32 v32, v32, v23                                 ; 10402f20
	v_mul_f32_e32 v24, v24, v23                                 ; 10302f18
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_sub_f32_e32 v22, v22, v18                                 ; 082c2516
	v_sub_f32_e32 v21, v21, v17                                 ; 082a2315
	v_sub_f32_e32 v20, v20, v16                                 ; 08282114
	v_mac_f32_e32 v18, v19, v22                                 ; 3e242d13
	v_mac_f32_e32 v17, v19, v21                                 ; 3e222b13
	v_mac_f32_e32 v16, v19, v20                                 ; 3e202913
	v_mul_f32_e32 v18, v18, v7                                  ; 10240f12
	v_mul_f32_e32 v17, v17, v34                                 ; 10224511
	v_mul_f32_e32 v16, v16, v33                                 ; 10204310
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v25, v25, v10                                 ; 10321519
	v_mul_f32_e32 v26, v26, v11                                 ; 1034171a
	v_mul_f32_e32 v27, v27, v12                                 ; 1036191b
	v_mac_f32_e32 v16, v30, v25                                 ; 3e20331e
	v_mac_f32_e32 v17, v32, v26                                 ; 3e223520
	v_mac_f32_e32 v18, v24, v27                                 ; 3e243718
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v4, v16, v3                                   ; 3e080710
	v_mac_f32_e32 v5, v17, v3                                   ; 3e0a0711
	v_mac_f32_e32 v1, v18, v3                                   ; 3e020712
	v_mul_f32_e32 v4, s0, v4                                    ; 10080800
	v_mul_f32_e32 v5, s0, v5                                    ; 100a0a00
	v_mul_f32_e32 v1, s0, v1                                    ; 10020200
	v_mad_f32 v6, s2, v4, 0.5                                   ; d5410006 03c20802
	v_madak_f32 v0, s2, v4, 0x3d4ccccd                          ; 42000802 3d4ccccd
	v_madak_f32 v2, s2, v5, 0x3d4ccccd                          ; 42040a02 3d4ccccd
	v_mad_f32 v7, s2, v5, 0.5                                   ; d5410007 03c20a02
	v_madak_f32 v3, s2, v1, 0x3d4ccccd                          ; 42060202 3d4ccccd
	v_mad_f32 v8, s2, v1, 0.5                                   ; d5410008 03c20202
	v_madak_f32 v6, v4, v6, 0x3d75c290                          ; 420c0d04 3d75c290
	v_madak_f32 v4, v4, v0, 0x3b83126f                          ; 42080104 3b83126f
	v_madak_f32 v7, v5, v7, 0x3d75c290                          ; 420e0f05 3d75c290
	v_madak_f32 v5, v5, v2, 0x3b83126f                          ; 420a0505 3b83126f
	v_madak_f32 v8, v1, v8, 0x3d75c290                          ; 42101101 3d75c290
	v_madak_f32 v1, v1, v3, 0x3b83126f                          ; 42020701 3b83126f
	v_rcp_f32_e32 v6, v6                                        ; 7e0c5506
	v_rcp_f32_e32 v7, v7                                        ; 7e0e5507
	v_rcp_f32_e32 v8, v8                                        ; 7e105508
	v_madak_f32 v4, v4, v6, 0xbd888888                          ; 42080d04 bd888888
	v_madak_f32 v5, v5, v7, 0xbd888888                          ; 420a0f05 bd888888
	v_mul_f32_e32 v4, 0x3fb0852e, v4                            ; 100808ff 3fb0852e
	v_madak_f32 v1, v1, v8, 0xbd888888                          ; 42021101 bd888888
	v_mul_f32_e32 v5, 0x3fb0852e, v5                            ; 100a0aff 3fb0852e
	v_log_f32_e32 v4, v4                                        ; 7e084f04
	v_mul_f32_e32 v1, 0x3fb0852e, v1                            ; 100202ff 3fb0852e
	v_log_f32_e32 v5, v5                                        ; 7e0a4f05
	v_log_f32_e32 v1, v1                                        ; 7e024f01
	v_mul_legacy_f32_e32 v4, v4, v35                            ; 0e084704
	v_mul_legacy_f32_e32 v5, v5, v35                            ; 0e0a4705
	v_exp_f32_e32 v4, v4                                        ; 7e084b04
	v_mul_legacy_f32_e32 v1, v1, v35                            ; 0e024701
	v_exp_f32_e32 v5, v5                                        ; 7e0a4b05
	v_exp_f32_e32 v1, v1                                        ; 7e024b01
	v_cvt_pkrtz_f16_f32_e32 v4, v4, v5                          ; 5e080b04
	v_cvt_pkrtz_f16_f32_e64 v1, v1, 1.0                         ; d52f0001 0001e501
	exp mrt0 v4, v4, v1, v1 done compr vm                       ; f8001c0f 80800104
	s_endpgm                                                    ; bf810000
