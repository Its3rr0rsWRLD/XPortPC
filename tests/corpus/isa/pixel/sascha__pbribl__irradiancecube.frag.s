# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s5                                            ; befc0305
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v4, v0, attr0.z                         ; c8100200
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v4, v1, attr0.z                         ; c8110201
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_mul_f32_e32 v3, v2, v2                                    ; 10060502
	s_mov_b32 s0, 0                                             ; be800380
	v_mov_b32_e32 v1, 0                                         ; 7e020280
	v_mac_f32_e32 v3, v4, v4                                    ; 3e060904
	v_lshrrev_b64 v[10:11], 0, 0                                ; d700000a 00010080
	v_mac_f32_e32 v3, v0, v0                                    ; 3e060100
	v_rsq_f32_e32 v3, v3                                        ; 7e065d03
	v_mul_f32_e32 v0, v0, v3                                    ; 10000700
	v_mul_f32_e32 v2, v2, v3                                    ; 10040702
	v_mul_f32_e32 v4, v4, v3                                    ; 10080704
	v_mov_b32_e32 v3, 0                                         ; 7e060280
	v_mul_f32_e32 v5, v4, v4                                    ; 100a0904
	v_mac_f32_e32 v5, v0, v0                                    ; 3e0a0100
	v_rsq_f32_e32 v5, v5                                        ; 7e0a5d05
	v_mul_f32_e32 v6, v4, v5                                    ; 100c0b04
	v_mul_f32_e32 v5, v0, v5                                    ; 100a0b00
	v_mul_f32_e32 v8, v2, v6                                    ; 10100d02
	v_mul_f32_e32 v9, v5, v2                                    ; 10120505
	v_mul_f32_e32 v7, v5, v0                                    ; 100e0105
	v_mac_f32_e32 v7, v4, v6                                    ; 3e0e0d04
BB1:
	s_mov_b32 s6, s2                                            ; be860302
	s_movk_i32 s7, 0x8000                                       ; b0078000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[6:7], null                        ; f40c0203 fa000000
	s_load_dwordx4 s[16:19], s[6:7], 0x50                       ; f4080403 fa000050
	v_mul_f32_e32 v12, 0.15915494, v11                          ; 101816f8
	v_cos_f32_e32 v13, v12                                      ; 7e1a6d0c
	v_sin_f32_e32 v12, v12                                      ; 7e186b0c
	v_mul_f32_e32 v14, v6, v13                                  ; 101c1b06
	v_mul_f32_e32 v13, v5, v13                                  ; 101a1b05
	v_mul_f32_e32 v15, v7, v12                                  ; 101e1907
	v_mad_f32 v14, v9, -v12, v14                                ; d541000e 443a1909
	v_mad_f32 v12, v8, -v12, -v13                               ; d541000c c4361908
	v_mov_b32_e32 v13, 0                                        ; 7e1a0280
	s_nop 0                                                     ; bf800000
BB2:
	v_mul_f32_e32 v16, 0.15915494, v13                          ; 10201af8
	v_cos_f32_e32 v17, v16                                      ; 7e226d10
	v_sin_f32_e32 v16, v16                                      ; 7e206b10
	v_mul_f32_e32 v18, v0, v17                                  ; 10242300
	v_mul_f32_e32 v19, v2, v17                                  ; 10262302
	v_mul_f32_e32 v20, v4, v17                                  ; 10282304
	v_mac_f32_e32 v18, v14, v16                                 ; 3e24210e
	v_mac_f32_e32 v19, v15, v16                                 ; 3e26210f
	v_mac_f32_e32 v20, v12, v16                                 ; 3e28210c
	v_cubema_f32 v21, v18, v19, v20                             ; d5470015 04522712
	v_cubesc_f32 v22, v18, v19, v20                             ; d5450016 04522712
	v_cubetc_f32 v23, v18, v19, v20                             ; d5460017 04522712
	v_cubeid_f32 v20, v18, v19, v20                             ; d5440014 04522712
	v_rcp_f32_e64 v21, |v21|                                    ; d5aa0115 00000115
	v_madak_f32 v19, v23, v21, 0x3fc00000                       ; 42262b17 3fc00000
	v_madak_f32 v18, v22, v21, 0x3fc00000                       ; 42242b16 3fc00000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[21:23], v[18:20], s[8:15], s[16:19] dmask:0x7 dim:SQ_RSRC_IMG_CUBE ; f0800718 00821512
	v_add_f32_e32 v13, s4, v13                                  ; 061a1a04
	s_add_u32 s0, s0, 1                                         ; 80008100
	v_cmp_ngt_f32_e32 vcc, 0x3fc90fdb, v13                      ; 7c161aff 3fc90fdb
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v21, v21, v17                                 ; 102a2315
	v_mul_f32_e32 v22, v22, v17                                 ; 102c2316
	v_mul_f32_e32 v23, v23, v17                                 ; 102e2317
	v_mac_f32_e32 v10, v21, v16                                 ; 3e142115
	v_mac_f32_e32 v3, v22, v16                                  ; 3e062116
	v_mac_f32_e32 v1, v23, v16                                  ; 3e022117
	s_cbranch_vccz BB2                                          ; bf86ffda
BB6:
	v_add_f32_e32 v11, s3, v11                                  ; 06161603
	v_cmp_ngt_f32_e32 vcc, 0x40c90fdb, v11                      ; 7c1616ff 40c90fdb
	s_cbranch_vccz BB1                                          ; bf86ffc3
BB10:
	v_cvt_f32_u32_e32 v0, s0                                    ; 7e000c00
	v_mul_f32_e32 v10, 0x40490fdb, v10                          ; 101414ff 40490fdb
	v_mul_f32_e32 v3, 0x40490fdb, v3                            ; 100606ff 40490fdb
	v_mul_f32_e32 v1, 0x40490fdb, v1                            ; 100202ff 40490fdb
	v_rcp_f32_e32 v0, v0                                        ; 7e005500
	v_fma_mixlo_f16 v2, v10, v0, neg(0) op_sel_hi:[0,0,1]       ; cc214002 8202010a
	v_fma_mixhi_f16 v2, v3, v0, neg(0) op_sel_hi:[0,0,1]        ; cc224002 82020103
	v_mul_f32_e32 v1, v1, v0                                    ; 10020101
	v_cvt_pkrtz_f16_f32_e64 v1, v1, 1.0                         ; d52f0001 0001e501
	exp mrt0 v2, v2, v1, v1 done compr vm                       ; f8001c0f 80800102
	s_endpgm                                                    ; bf810000
