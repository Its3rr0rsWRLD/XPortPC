# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x3                                                ; bfa10003
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_load_dwordx8 s[16:23], s[2:3], 0x80                       ; f40c0401 fa000080
	s_load_dwordx4 s[24:27], s[2:3], 0xd0                       ; f4080601 fa0000d0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v8, v0, attr1.w                         ; c8200700
	v_interp_p1_f32_e32 v9, v0, attr1.y                         ; c8240500
	v_interp_p1_f32_e32 v10, v0, attr1.x                        ; c8280400
	v_interp_p1_f32_e32 v4, v0, attr0.y                         ; c8100100
	v_interp_p1_f32_e32 v5, v0, attr0.z                         ; c8140200
	v_interp_p1_f32_e32 v6, v0, attr0.x                         ; c8180000
	v_interp_p1_f32_e32 v7, v0, attr1.z                         ; c81c0600
	v_interp_p1_f32_e32 v0, v0, attr0.w                         ; c8000300
	v_interp_p2_f32_e32 v10, v1, attr1.x                        ; c8290401
	v_interp_p2_f32_e32 v0, v1, attr0.w                         ; c8010301
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample_lz  v11, [v0, v10], s[8:15], s[4:7] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f09c010a 00220b00 0000000a
	v_mov_b32_e32 v14, 0                                        ; 7e1c0280
	v_mov_b32_e32 v15, 1.0                                      ; 7e1e02f2
	v_mov_b32_e32 v16, 2.0                                      ; 7e2002f4
	v_interp_p2_f32_e32 v8, v1, attr1.w                         ; c8210701
	v_interp_p2_f32_e32 v9, v1, attr1.y                         ; c8250501
	v_interp_p2_f32_e32 v4, v1, attr0.y                         ; c8110101
	v_interp_p2_f32_e32 v5, v1, attr0.z                         ; c8150201
	v_interp_p2_f32_e32 v6, v1, attr0.x                         ; c8190001
	v_interp_p2_f32_e32 v7, v1, attr1.z                         ; c81d0601
	v_mov_b32_e32 v17, 0x40400000                               ; 7e2202ff 40400000
	v_mov_b32_e32 v18, 4.0                                      ; 7e2402f6
	v_mov_b32_e32 v19, 0x40a00000                               ; 7e2602ff 40a00000
	v_mul_f32_e32 v13, 0x41800000, v10                          ; 101a14ff 41800000
	v_mul_f32_e32 v12, 0x41800000, v0                           ; 101800ff 41800000
	v_mov_b32_e32 v26, v2                                       ; 7e340302
	v_mov_b32_e32 v10, v19                                      ; 7e140313
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mov_b32_e32 v27, v11                                      ; 7e36030b
	image_sample v[20:22], v[12:14], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800728 00c4140c
	image_sample  v[23:25], [v12, v13, v15], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00c4170c 00000f0d
	image_sample  v[14:16], [v12, v13, v16], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00c40e0c 0000100d
	image_sample  v[0:2], [v12, v13, v17], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00c4000c 0000110d
	image_sample  v[17:19], [v12, v13, v18], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00c4110c 0000120d
	image_sample  v[10:12], [v12, v13, v10], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f080072a 00c40a0c 00000a0d
	v_mul_f32_e32 v13, v4, v4                                   ; 101a0904
	v_mac_f32_e32 v13, v5, v5                                   ; 3e1a0b05
	v_mac_f32_e32 v13, v6, v6                                   ; 3e1a0d06
	v_rsq_f32_e32 v13, v13                                      ; 7e1a5d0d
	v_mul_f32_e32 v26, v26, v3                                  ; 1034071a
	v_mul_f32_e32 v3, 0xbd13bb63, v26                           ; 100634ff bd13bb63
	v_mul_f32_e32 v26, 0x3ccccccd, v26                          ; 103434ff 3ccccccd
	v_mul_f32_e32 v5, v5, v13                                   ; 100a1b05
	v_mul_f32_e32 v4, v4, v13                                   ; 10081b04
	v_mul_f32_e32 v6, v6, v13                                   ; 100c1b06
	v_mul_f32_e32 v13, v7, v7                                   ; 101a0f07
	v_mul_f32_e32 v3, v3, v26                                   ; 10063503
	v_mac_f32_e32 v13, v8, v8                                   ; 3e1a1108
	v_exp_f32_e32 v3, v3                                        ; 7e064b03
	v_mac_f32_e32 v13, v9, v9                                   ; 3e1a1309
	v_rsq_f32_e32 v13, v13                                      ; 7e1a5d0d
	v_sub_f32_e64 v3, 1.0, v3 clamp                             ; d5048003 000206f2
	v_mul_f32_e32 v9, v9, v13                                   ; 10121b09
	v_mul_f32_e32 v7, v7, v13                                   ; 100e1b07
	v_mul_f32_e32 v8, v8, v13                                   ; 10101b08
	v_mul_f32_e32 v5, v5, v8                                    ; 100a1105
	v_mac_f32_e32 v5, v4, v7                                    ; 3e0a0f04
	v_fma_mix_f32 v4, 0x5bf8, v27, 0x5bf8 op_sel:[0,0,1] op_sel_hi:[1,0,1] ; cc206004 0bfe36ff c9005bf8
	v_fma_mix_f32 v7, 0x5bf8, v27, 0x5bf8 op_sel:[0,0,1] op_sel_hi:[1,0,1] ; cc206007 0bfe36ff d5005bf8
	v_fma_mix_f32 v8, 0x5bf8, v27, 0x5bf8 op_sel:[0,0,1] op_sel_hi:[1,0,1] ; cc206008 0bfe36ff d6405bf8
	v_mac_f32_e32 v5, v6, v9                                    ; 3e0a1306
	v_fma_mix_f32 v6, 0x5bf8, v27, 0x5bf8 op_sel:[0,0,1] op_sel_hi:[1,0,1] ; cc206006 0bfe36ff d1a05bf8
	v_sub_f32_e64 v4, 0x41a00000, |v4|                          ; d5040204 000208ff 41a00000
	v_fma_mix_f32 v9, 0x5bf8, v27, 0x5bf8 op_sel:[0,0,1] op_sel_hi:[1,0,1] ; cc206009 0bfe36ff d8b05bf8
	v_sub_f32_e64 v7, 0x420c0000, |v7|                          ; d5040207 00020eff 420c0000
	v_sub_f32_e64 v8, 0x41c80000, |v8|                          ; d5040208 000210ff 41c80000
	v_fma_mix_f32 v27, 0x5bf8, v27, 0x5bf8 op_sel:[0,0,1] op_sel_hi:[1,0,1] ; cc20601b 0bfe36ff dc885bf8
	v_max_f32_e32 v5, 0, v5                                     ; 200a0a80
	v_sub_f32_e64 v6, 0x42200000, |v6|                          ; d5040206 00020cff 42200000
	v_mul_f32_e32 v4, 0x3d4ccccd, v4                            ; 100808ff 3d4ccccd
	v_sub_f32_e64 v9, 0x425c0000, |v9|                          ; d5040209 000212ff 425c0000
	v_mul_f32_e32 v7, 0x3cea0ea1, v7                            ; 100e0eff 3cea0ea1
	v_mul_f32_e32 v8, 0x3d23d70a, v8                            ; 101010ff 3d23d70a
	v_sub_f32_e64 v27, 0x43160000, |v27|                        ; d504021b 000236ff 43160000
	v_add_f32_e32 v5, 0.5, v5                                   ; 060a0af0
	v_mul_f32_e32 v6, 0x3ccccccd, v6                            ; 100c0cff 3ccccccd
	v_max_f32_e32 v4, 0, v4                                     ; 20080880
	v_mul_f32_e32 v9, 0x3c94f209, v9                            ; 101212ff 3c94f209
	v_max_f32_e32 v7, 0, v7                                     ; 200e0e80
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_mul_f32_e32 v27, 0x3bda740e, v27                          ; 103636ff 3bda740e
	v_max_f32_e32 v6, 0, v6                                     ; 200c0c80
	v_max_f32_e32 v9, 0, v9                                     ; 20121280
	v_max_f32_e32 v27, 0, v27                                   ; 20363680
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mul_f32_e32 v21, v21, v4                                  ; 102a0915
	v_mul_f32_e32 v22, v22, v4                                  ; 102c0916
	v_mul_f32_e32 v20, v20, v4                                  ; 10280914
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v21, v24, v6                                  ; 3e2a0d18
	v_mac_f32_e32 v22, v25, v6                                  ; 3e2c0d19
	v_mac_f32_e32 v20, v23, v6                                  ; 3e280d17
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mac_f32_e32 v21, v15, v7                                  ; 3e2a0f0f
	v_mac_f32_e32 v22, v16, v7                                  ; 3e2c0f10
	v_mac_f32_e32 v20, v14, v7                                  ; 3e280f0e
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v21, v1, v8                                   ; 3e2a1101
	v_mac_f32_e32 v22, v2, v8                                   ; 3e2c1102
	v_mac_f32_e32 v20, v0, v8                                   ; 3e281100
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v21, v18, v9                                  ; 3e2a1312
	v_mac_f32_e32 v22, v19, v9                                  ; 3e2c1313
	v_mac_f32_e32 v20, v17, v9                                  ; 3e281311
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v21, v11, v27                                 ; 3e2a370b
	v_mac_f32_e32 v22, v12, v27                                 ; 3e2c370c
	v_mac_f32_e32 v20, v10, v27                                 ; 3e28370a
	v_mul_f32_e32 v21, v5, v21                                  ; 102a2b05
	v_mul_f32_e32 v20, v5, v20                                  ; 10282905
	v_mul_f32_e32 v5, v5, v22                                   ; 100a2d05
	v_sub_f32_e32 v12, 0.5, v21                                 ; 08182af0
	v_sub_f32_e32 v10, 0x3ef0a3d7, v20                          ; 081428ff 3ef0a3d7
	v_sub_f32_e32 v13, 0x3f2b851f, v5                           ; 081a0aff 3f2b851f
	v_fma_mixlo_f16 v11, v3, v10, v20                           ; cc21000b 04521503
	v_fma_mixhi_f16 v11, v3, v12, v21                           ; cc22000b 04561903
	v_fma_mixlo_f16 v14, v3, v13, v5                            ; cc21000e 04161b03
	v_fma_mixhi_f16 v14, 1.0, -v3, 1.0 op_sel_hi:[0,0,1]        ; cc22400e 43ca06f2
	exp mrt0 v11, v11, v14, v14 done compr vm                   ; f8001c0f 80800e0b
	s_endpgm                                                    ; bf810000
