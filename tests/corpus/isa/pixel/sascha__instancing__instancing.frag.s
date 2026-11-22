# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr1.z                         ; c8080600
	v_interp_p1_f32_e32 v3, v0, attr1.w                         ; c80c0700
	v_interp_p1_f32_e32 v4, v0, attr2.x                         ; c8100800
	v_interp_p2_f32_e32 v2, v1, attr1.z                         ; c8090601
	v_interp_p2_f32_e32 v3, v1, attr1.w                         ; c80d0701
	v_interp_p2_f32_e32 v4, v1, attr2.x                         ; c8110801
	v_rndne_f32_e32 v4, v4                                      ; 7e084704
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[5:7], v[2:4], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800728 00220502
	v_interp_p1_f32_e32 v11, v0, attr0.y                        ; c82c0100
	v_interp_p1_f32_e32 v9, v0, attr1.x                         ; c8240400
	v_interp_p1_f32_e32 v10, v0, attr1.y                        ; c8280500
	v_interp_p1_f32_e32 v8, v0, attr0.w                         ; c8200300
	v_interp_p1_f32_e32 v13, v0, attr0.z                        ; c8340200
	v_interp_p1_f32_e32 v14, v0, attr0.x                        ; c8380000
	v_interp_p1_f32_e32 v15, v0, attr3.y                        ; c83c0d00
	v_interp_p2_f32_e32 v11, v1, attr0.y                        ; c82d0101
	v_interp_p2_f32_e32 v9, v1, attr1.x                         ; c8250401
	v_interp_p1_f32_e32 v17, v0, attr3.z                        ; c8440e00
	v_interp_p2_f32_e32 v10, v1, attr1.y                        ; c8290501
	v_interp_p2_f32_e32 v8, v1, attr0.w                         ; c8210301
	v_interp_p2_f32_e32 v13, v1, attr0.z                        ; c8350201
	v_interp_p1_f32_e32 v18, v0, attr3.x                        ; c8480c00
	v_interp_p2_f32_e32 v14, v1, attr0.x                        ; c8390001
	v_interp_p2_f32_e32 v15, v1, attr3.y                        ; c83d0d01
	v_interp_p2_f32_e32 v17, v1, attr3.z                        ; c8450e01
	v_interp_p1_f32_e32 v19, v0, attr2.z                        ; c84c0a00
	v_interp_p2_f32_e32 v18, v1, attr3.x                        ; c8490c01
	v_interp_p2_f32_e32 v19, v1, attr2.z                        ; c84d0a01
	v_interp_p1_f32_e32 v21, v0, attr2.w                        ; c8540b00
	v_interp_p2_f32_e32 v21, v1, attr2.w                        ; c8550b01
	v_mul_f32_e32 v12, v11, v11                                 ; 1018170b
	v_mul_f32_e32 v16, v15, v15                                 ; 10201f0f
	v_mul_f32_e32 v20, v19, v19                                 ; 10282713
	v_interp_p1_f32_e32 v0, v0, attr2.y                         ; c8000900
	v_interp_p2_f32_e32 v0, v1, attr2.y                         ; c8010901
	v_mac_f32_e32 v12, v13, v13                                 ; 3e181b0d
	v_mac_f32_e32 v16, v17, v17                                 ; 3e202311
	v_mac_f32_e32 v20, v21, v21                                 ; 3e282b15
	v_mac_f32_e32 v12, v14, v14                                 ; 3e181d0e
	v_mac_f32_e32 v16, v18, v18                                 ; 3e202512
	v_mac_f32_e32 v20, v0, v0                                   ; 3e280100
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_rsq_f32_e32 v16, v16                                      ; 7e205d10
	v_rsq_f32_e32 v20, v20                                      ; 7e285d14
	v_mul_f32_e32 v14, v14, v12                                 ; 101c190e
	v_mul_f32_e32 v11, v11, v12                                 ; 1016190b
	v_mul_f32_e32 v13, v13, v12                                 ; 101a190d
	v_mul_f32_e32 v17, v17, v16                                 ; 10222111
	v_mul_f32_e32 v15, v15, v16                                 ; 101e210f
	v_mul_f32_e32 v18, v18, v16                                 ; 10242112
	v_mul_f32_e32 v21, v21, v20                                 ; 102a2915
	v_mul_f32_e32 v19, v19, v20                                 ; 10262913
	v_mul_f32_e32 v0, v0, v20                                   ; 10002900
	v_mul_f32_e32 v22, v17, v13                                 ; 102c1b11
	v_mad_f32 v23, v15, -v11, -v22                              ; d5410017 c45a170f
	v_mac_f32_e32 v22, v15, v11                                 ; 3e2c170f
	v_mad_f32 v23, v18, -v14, v23 mul:2                         ; d5410017 4c5e1d12
	v_mac_f32_e32 v22, v18, v14                                 ; 3e2c1d12
	v_mad_f32 v1, v14, -v23, -v18                               ; d5410001 c44a2f0e
	v_mad_f32 v13, v13, -v23, -v17                              ; d541000d c4462f0d
	v_mad_f32 v2, v11, -v23, -v15                               ; d5410002 c43e2f0b
	v_max_f32_e32 v3, 0x3dcccccd, v22                           ; 20062cff 3dcccccd
	v_cmp_lt_f32_e32 vcc, 0, v22                                ; 7c022c80
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v5, v5, v8                                    ; 100a1105
	v_mul_f32_e32 v8, v8, v3                                    ; 10100708
	v_mul_f32_e32 v6, v6, v9                                    ; 100c1306
	v_mul_f32_e32 v9, v9, v3                                    ; 10120709
	v_mul_f32_e32 v7, v7, v10                                   ; 100e1507
	v_mul_f32_e32 v10, v10, v3                                  ; 1014070a
	s_and_saveexec_b64 s[0:1], vcc                              ; be80246a
BB1:
	v_mul_f32_e32 v13, v13, v21                                 ; 101a2b0d
	v_mac_f32_e32 v13, v2, v19                                  ; 3e1a2702
	v_mac_f32_e32 v13, v1, v0                                   ; 3e1a0101
	v_max_f32_e32 v13, 0, v13                                   ; 201a1a80
	v_log_f32_e32 v13, v13                                      ; 7e1a4f0d
	v_mul_f32_e32 v13, 0x41800000, v13                          ; 101a1aff 41800000
	v_exp_f32_e32 v13, v13                                      ; 7e1a4b0d
	v_mul_f32_e32 v13, 0x3f400000, v13                          ; 101a1aff 3f400000
	v_mul_f32_e32 v13, v13, v5                                  ; 101a0b0d
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
BB4:
	v_mov_b32_e32 v13, 0                                        ; 7e1a0280
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_fma_mixlo_f16 v0, v8, v5, v13                             ; cc210000 04360b08
	v_fma_mixhi_f16 v0, v9, v6, v13                             ; cc220000 04360d09
	v_mac_f32_e32 v13, v10, v7                                  ; 3e1a0f0a
	v_cvt_pkrtz_f16_f32_e64 v13, v13, 1.0                       ; d52f000d 0001e50d
	exp mrt0 v0, v0, v13, v13 done compr vm                     ; f8001c0f 80800d00
	s_endpgm                                                    ; bf810000
