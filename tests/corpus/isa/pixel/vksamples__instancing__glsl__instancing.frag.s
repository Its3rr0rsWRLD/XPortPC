# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.w                         ; c8080300
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_p1_f32_e32 v4, v0, attr1.y                         ; c8100500
	v_interp_p2_f32_e32 v2, v1, attr0.w                         ; c8090301
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	v_interp_p2_f32_e32 v4, v1, attr1.y                         ; c8110501
	v_rndne_f32_e32 v4, v4                                      ; 7e084704
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[5:7], v[2:4], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800728 00220502
	v_interp_p1_f32_e32 v11, v0, attr0.x                        ; c82c0000
	v_interp_p1_f32_e32 v10, v0, attr0.z                        ; c8280200
	v_interp_p1_f32_e32 v8, v0, attr0.y                         ; c8200100
	v_interp_p1_f32_e32 v12, v0, attr2.z                        ; c8300a00
	v_interp_p1_f32_e32 v14, v0, attr2.w                        ; c8380b00
	v_interp_p1_f32_e32 v15, v0, attr2.y                        ; c83c0900
	v_interp_p2_f32_e32 v11, v1, attr0.x                        ; c82d0001
	v_interp_p2_f32_e32 v10, v1, attr0.z                        ; c8290201
	v_interp_p2_f32_e32 v8, v1, attr0.y                         ; c8210101
	v_interp_p2_f32_e32 v12, v1, attr2.z                        ; c8310a01
	v_interp_p2_f32_e32 v14, v1, attr2.w                        ; c8390b01
	v_interp_p2_f32_e32 v15, v1, attr2.y                        ; c83d0901
	v_interp_p1_f32_e32 v16, v0, attr1.w                        ; c8400700
	v_interp_p2_f32_e32 v16, v1, attr1.w                        ; c8410701
	v_interp_p1_f32_e32 v18, v0, attr2.x                        ; c8480800
	v_interp_p2_f32_e32 v18, v1, attr2.x                        ; c8490801
	v_mul_f32_e32 v9, v8, v8                                    ; 10121108
	v_mul_f32_e32 v13, v12, v12                                 ; 101a190c
	v_mul_f32_e32 v17, v16, v16                                 ; 10222110
	v_interp_p1_f32_e32 v0, v0, attr1.z                         ; c8000600
	v_interp_p2_f32_e32 v0, v1, attr1.z                         ; c8010601
	v_mac_f32_e32 v9, v10, v10                                  ; 3e12150a
	v_mac_f32_e32 v13, v14, v14                                 ; 3e1a1d0e
	v_mac_f32_e32 v17, v18, v18                                 ; 3e222512
	v_mac_f32_e32 v9, v11, v11                                  ; 3e12170b
	v_mac_f32_e32 v13, v15, v15                                 ; 3e1a1f0f
	v_mac_f32_e32 v17, v0, v0                                   ; 3e220100
	v_rsq_f32_e32 v9, v9                                        ; 7e125d09
	v_rsq_f32_e32 v13, v13                                      ; 7e1a5d0d
	v_rsq_f32_e32 v17, v17                                      ; 7e225d11
	v_mul_f32_e32 v8, v8, v9                                    ; 10101308
	v_mul_f32_e32 v10, v10, v9                                  ; 1014130a
	v_mul_f32_e32 v11, v11, v9                                  ; 1016130b
	v_mul_f32_e32 v15, v15, v13                                 ; 101e1b0f
	v_mul_f32_e32 v14, v14, v13                                 ; 101c1b0e
	v_mul_f32_e32 v12, v12, v13                                 ; 10181b0c
	v_mul_f32_e32 v16, v16, v17                                 ; 10202310
	v_mul_f32_e32 v0, v0, v17                                   ; 10002300
	v_mul_f32_e32 v18, v18, v17                                 ; 10242312
	v_mul_f32_e32 v19, v14, v10                                 ; 1026150e
	v_mad_f32 v20, v12, -v8, -v19                               ; d5410014 c44e110c
	v_mac_f32_e32 v19, v12, v8                                  ; 3e26110c
	v_mad_f32 v20, v15, -v11, v20 mul:2                         ; d5410014 4c52170f
	v_mac_f32_e32 v19, v15, v11                                 ; 3e26170f
	v_mad_f32 v21, v11, -v20, -v15                              ; d5410015 c43e290b
	v_mad_f32 v10, v10, -v20, -v14                              ; d541000a c43a290a
	v_mad_f32 v22, v8, -v20, -v12                               ; d5410016 c4322908
	v_cmp_lt_f32_e32 vcc, 0, v19                                ; 7c022680
	s_and_saveexec_b64 s[0:1], vcc                              ; be80246a
BB1:
	v_mul_f32_e32 v10, v10, v18                                 ; 1014250a
	v_mac_f32_e32 v10, v22, v16                                 ; 3e142116
	v_mac_f32_e32 v10, v21, v0                                  ; 3e140115
	v_max_f32_e32 v10, 0, v10                                   ; 20141480
	v_log_f32_e32 v10, v10                                      ; 7e144f0a
	v_mul_f32_e32 v10, 0x41800000, v10                          ; 101414ff 41800000
	v_exp_f32_e32 v10, v10                                      ; 7e144b0a
	v_mul_f32_e32 v10, 0x3f400000, v10                          ; 101414ff 3f400000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v10, v10, v5                                  ; 10140b0a
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
BB4:
	v_mov_b32_e32 v10, 0                                        ; 7e140280
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_max_f32_e32 v19, 0x3dcccccd, v19                          ; 202626ff 3dcccccd
	v_fma_mixlo_f16 v0, v19, v5, v10                            ; cc210000 042a0b13
	v_fma_mixhi_f16 v0, v19, v6, v10                            ; cc220000 042a0d13
	v_mac_f32_e32 v10, v19, v7                                  ; 3e140f13
	v_cvt_pkrtz_f16_f32_e64 v10, v10, 1.0                       ; d52f000a 0001e50a
	exp mrt0 v0, v0, v10, v10 done compr vm                     ; f8001c0f 80800a00
	s_endpgm                                                    ; bf810000
