# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s3                                            ; befc0303
	v_interp_p1_f32_e32 v2, v0, attr2.y                         ; c8080900
	v_interp_p1_f32_e32 v3, v0, attr3.x                         ; c80c0c00
	v_interp_p1_f32_e32 v5, v0, attr2.z                         ; c8140a00
	v_interp_p1_f32_e32 v8, v0, attr2.w                         ; c8200b00
	v_interp_p2_f32_e32 v2, v1, attr2.y                         ; c8090901
	v_interp_p2_f32_e32 v3, v1, attr3.x                         ; c80d0c01
	v_interp_p2_f32_e32 v5, v1, attr2.z                         ; c8150a01
	v_interp_p2_f32_e32 v8, v1, attr2.w                         ; c8210b01
	v_rcp_f32_e32 v4, v3                                        ; 7e085503
	v_mul_f32_e32 v6, v2, v4                                    ; 100c0902
	v_mul_f32_e32 v7, v5, v4                                    ; 100e0905
	v_mul_f32_e32 v8, v8, v4                                    ; 10100908
	v_mul_f32_e32 v3, v3, v4                                    ; 10060903
	v_cmp_gt_f32_e64 s[0:1], 1.0, v8                            ; d4040000 000210f2
	v_cmp_lt_f32_e32 vcc, -1.0, v8                              ; 7c0210f3
	s_and_b64 s[0:1], vcc, s[0:1]                               ; 8780006a
	s_and_saveexec_b64 s[0:1], s[0:1]                           ; be802400
	s_cbranch_execz BB4                                         ; bf880011
BB1:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x20                        ; f40c0201 fa000020
	s_load_dwordx4 s[4:7], s[2:3], 0x70                         ; f4080101 fa000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v6, v[6:7], s[8:15], s[4:7] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f0800108 00220606
	v_cmp_lt_f32_e32 vcc, 0, v3                                 ; 7c020680
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[2:3], v6, v8                             ; d4010002 00021106
	s_and_b64 s[2:3], vcc, s[2:3]                               ; 8782026a
	v_cndmask_b32_e64 v2, 1.0, 0x3dcccccd, s[2:3]               ; d5010002 0009fef2 3dcccccd
BB4:
	s_andn2_b64 exec, s[0:1], exec                              ; 8afe7e00
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v5, v0, attr0.z                         ; c8140200
	v_interp_p1_f32_e32 v6, v0, attr0.x                         ; c8180000
	v_interp_p1_f32_e32 v7, v0, attr1.w                         ; c81c0700
	v_interp_p1_f32_e32 v9, v0, attr2.x                         ; c8240800
	v_interp_p1_f32_e32 v10, v0, attr1.z                        ; c8280600
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v5, v1, attr0.z                         ; c8150201
	v_interp_p2_f32_e32 v6, v1, attr0.x                         ; c8190001
	v_interp_p2_f32_e32 v7, v1, attr1.w                         ; c81d0701
	v_interp_p2_f32_e32 v9, v1, attr2.x                         ; c8250801
	v_interp_p2_f32_e32 v10, v1, attr1.z                        ; c8290601
	v_mul_f32_e32 v4, v3, v3                                    ; 10080703
	v_mul_f32_e32 v8, v7, v7                                    ; 10100f07
	v_interp_p1_f32_e32 v11, v0, attr0.w                        ; c82c0300
	v_interp_p2_f32_e32 v11, v1, attr0.w                        ; c82d0301
	v_mac_f32_e32 v4, v5, v5                                    ; 3e080b05
	v_mac_f32_e32 v8, v9, v9                                    ; 3e101309
	v_interp_p1_f32_e32 v12, v0, attr1.x                        ; c8300400
	v_interp_p2_f32_e32 v12, v1, attr1.x                        ; c8310401
	v_mac_f32_e32 v4, v6, v6                                    ; 3e080d06
	v_mac_f32_e32 v8, v10, v10                                  ; 3e10150a
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_rsq_f32_e32 v4, v4                                        ; 7e085d04
	v_rsq_f32_e32 v8, v8                                        ; 7e105d08
	v_mul_f32_e32 v6, v6, v4                                    ; 100c0906
	v_mul_f32_e32 v3, v3, v4                                    ; 10060903
	v_mul_f32_e32 v5, v5, v4                                    ; 100a0905
	v_mul_f32_e32 v10, v10, v8                                  ; 1014110a
	v_mul_f32_e32 v7, v7, v8                                    ; 100e1107
	v_mul_f32_e32 v9, v9, v8                                    ; 10121109
	v_mul_f32_e32 v5, v5, v9                                    ; 100a1305
	v_mac_f32_e32 v5, v3, v7                                    ; 3e0a0f03
	v_mac_f32_e32 v5, v6, v10                                   ; 3e0a1506
	v_max_f32_e32 v5, 0x3dcccccd, v5                            ; 200a0aff 3dcccccd
	v_mul_f32_e32 v11, v11, v5                                  ; 10160b0b
	v_mul_f32_e32 v12, v12, v5                                  ; 10180b0c
	v_mul_f32_e32 v0, v0, v5                                    ; 10000b00
	v_fma_mixlo_f16 v13, v11, v2, neg(0) op_sel_hi:[0,0,1]      ; cc21400d 8202050b
	v_fma_mixhi_f16 v13, v12, v2, neg(0) op_sel_hi:[0,0,1]      ; cc22400d 8202050c
	v_mul_f32_e32 v0, v0, v2                                    ; 10000500
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 1.0                         ; d52f0000 0001e500
	exp mrt0 v13, v13, v0, v0 done compr vm                     ; f8001c0f 8080000d
	s_endpgm                                                    ; bf810000
