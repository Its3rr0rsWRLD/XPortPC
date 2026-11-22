# Pixel Shader
BB0:
	s_mov_b32 s6, s3                                            ; be860303
	s_movk_i32 s7, 0x8000                                       ; b0078000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[6:7], null                        ; f40c0203 fa000000
	s_load_dwordx4 s[16:19], s[6:7], 0x50                       ; f4080403 fa000050
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	v_interp_p1_f32_e32 v2, v0, attr2.x                         ; c8080800
	v_interp_p1_f32_e32 v3, v0, attr1.w                         ; c80c0700
	v_interp_p2_f32_e32 v2, v1, attr2.x                         ; c8090801
	v_interp_p2_f32_e32 v3, v1, attr1.w                         ; c80d0701
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[4:7], [v3, v2], s[8:15], s[16:19] dmask:0xf dim:SQ_RSRC_IMG_2D ; f0800f0a 00820403 00000002
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_gt_f32_e32 vcc, 0.5, v7                               ; 7c080ef0
	s_andn2_b64 exec, exec, vcc                                 ; 8afe6a7e
	s_andn2_b64 s[0:1], s[0:1], vcc                             ; 8a806a00
	s_cbranch_scc0 BB10                                         ; bf8400ab
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx8 s[8:15], s[2:3], 0x70                        ; f40c0201 fa000070
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dwordx4 s[4:7], s[8:11], null                 ; f4280104 fa000000
	v_interp_p1_f32_e32 v8, v0, attr0.w                         ; c8200300
	v_interp_p2_f32_e32 v8, v1, attr0.w                         ; c8210301
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_cmp_gt_f32_e32 vcc, s4, v8                                ; 7c081004
	v_cndmask_b32_e64 v9, 0, 1, vcc                             ; d5010009 01a90280
	v_cmp_gt_f32_e32 vcc, s5, v8                                ; 7c081005
	v_cndmask_b32_e64 v9, v9, 2, vcc                            ; d5010009 01a90509
	v_cmp_gt_f32_e32 vcc, s6, v8                                ; 7c081006
	v_cndmask_b32_e64 v9, v9, 3, vcc                            ; d5010009 01a90709
	v_lshlrev_b32_e32 v10, 6, v9                                ; 34141286
	s_clause 0x3                                                ; bfa10003
	buffer_load_dwordx4 v[12:15], v10, s[12:15], 0 offen        ; e0381000 80030c0a
	buffer_load_dwordx4 v[16:19], v10, s[12:15], 0 offen offset:16 ; e0381010 8003100a
	buffer_load_dwordx4 v[20:23], v10, s[12:15], 0 offen offset:32 ; e0381020 8003140a
	buffer_load_dwordx4 v[24:27], v10, s[12:15], 0 offen offset:48 ; e0381030 8003180a
	v_interp_p1_f32_e32 v11, v0, attr1.z                        ; c82c0600
	v_interp_p1_f32_e32 v2, v0, attr1.y                         ; c8080500
	v_interp_p1_f32_e32 v3, v0, attr1.x                         ; c80c0400
	v_interp_p2_f32_e32 v11, v1, attr1.z                        ; c82d0601
	v_interp_p2_f32_e32 v2, v1, attr1.y                         ; c8090501
	v_interp_p2_f32_e32 v3, v1, attr1.x                         ; c80d0401
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_add_f32_e64 v13, v13, v15 div:2                           ; d503000d 18021f0d
	v_add_f32_e64 v12, v12, v15 div:2                           ; d503000c 18021f0c
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_add_f32_e64 v16, v16, v19 div:2                           ; d5030010 18022710
	v_add_f32_e64 v17, v17, v19 div:2                           ; d5030011 18022711
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_add_f32_e64 v21, v21, v23 div:2                           ; d5030015 18022f15
	v_add_f32_e64 v20, v20, v23 div:2                           ; d5030014 18022f14
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v26, v22, v11                                 ; 3e341716
	v_add_f32_e64 v25, v25, v27 div:2                           ; d5030019 18023719
	v_add_f32_e64 v24, v24, v27 div:2                           ; d5030018 18023718
	v_mac_f32_e32 v27, v23, v11                                 ; 3e361717
	v_mac_f32_e32 v26, v18, v2                                  ; 3e340512
	v_mac_f32_e32 v25, v21, v11                                 ; 3e321715
	v_mac_f32_e32 v24, v20, v11                                 ; 3e301714
	v_mac_f32_e32 v27, v19, v2                                  ; 3e360513
	v_mac_f32_e32 v26, v14, v3                                  ; 3e34070e
	v_mac_f32_e32 v25, v17, v2                                  ; 3e320511
	v_mac_f32_e32 v24, v16, v2                                  ; 3e300510
	v_mac_f32_e32 v27, v15, v3                                  ; 3e36070f
	v_mac_f32_e32 v25, v13, v3                                  ; 3e32070d
	v_mac_f32_e32 v24, v12, v3                                  ; 3e30070c
	v_rcp_f32_e32 v8, v27                                       ; 7e10551b
	v_mul_f32_e32 v11, v25, v8                                  ; 10161119
	v_mul_f32_e32 v10, v24, v8                                  ; 10141118
	v_mul_f32_e32 v26, v26, v8                                  ; 1034111a
	v_mul_f32_e32 v27, v27, v8                                  ; 1036111b
	v_cmp_lt_f32_e32 vcc, -1.0, v26                             ; 7c0234f3
	v_cmp_gt_f32_e64 s[4:5], 1.0, v26                           ; d4040004 000234f2
	s_and_b64 s[4:5], vcc, s[4:5]                               ; 8784046a
	s_and_saveexec_b64 s[4:5], s[4:5]                           ; be842404
	s_cbranch_execz BB4                                         ; bf880013
BB1:
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[16:23], s[2:3], null                       ; f40c0401 fa000000
	s_load_dwordx4 s[12:15], s[2:3], 0x50                       ; f4080301 fa000050
	v_cvt_f32_u32_e32 v12, v9                                   ; 7e180d09
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v10, v[10:12], s[16:23], s[12:15] dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY ; f0800128 00640a0a
	v_add_f32_e32 v26, 0xbba3d70a, v26                          ; 063434ff bba3d70a
	v_cmp_lt_f32_e32 vcc, 0, v27                                ; 7c023680
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e64 s[2:3], v10, v26                           ; d4010002 0002350a
	s_and_b64 s[2:3], vcc, s[2:3]                               ; 8782026a
	v_cndmask_b32_e64 v2, 1.0, 0x3e99999a, s[2:3]               ; d5010002 0009fef2 3e99999a
BB4:
	s_andn2_b64 exec, s[4:5], exec                              ; 8afe7e04
	v_mov_b32_e32 v2, 1.0                                       ; 7e0402f2
BB6:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx4 s[0:3], s[8:11], 0x50                 ; f4280004 fa000050
	s_buffer_load_dword s4, s[8:11], 0x60                       ; f4200104 fa000060
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v10, v0, attr0.z                        ; c8280200
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v10, v1, attr0.z                        ; c8290201
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	v_mul_f32_e32 v8, v3, v3                                    ; 10100703
	v_mac_f32_e32 v8, v10, v10                                  ; 3e10150a
	v_mac_f32_e32 v8, v0, v0                                    ; 3e100100
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v11, s1, s1                                   ; d508000b 00000201
	v_rsq_f32_e32 v8, v8                                        ; 7e105d08
	v_mad_f32 v11, s2, s2, v11                                  ; d541000b 042c0402
	v_mad_f32 v11, s0, s0, v11                                  ; d541000b 042c0000
	v_mul_f32_e32 v0, v0, v8                                    ; 10001100
	v_mul_f32_e32 v3, v3, v8                                    ; 10061103
	v_mul_f32_e32 v10, v10, v8                                  ; 1014110a
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_mul_f32_e32 v12, s0, v11                                  ; 10181600
	v_mul_f32_e32 v13, s1, v11                                  ; 101a1601
	v_mul_f32_e32 v11, s2, v11                                  ; 10161602
	s_cmp_eq_i32 s4, 1                                          ; bf008104
	v_mul_f32_e32 v11, v11, v10                                 ; 1016150b
	v_mad_f32 v13, v13, -v3, -v11                               ; d541000d c42e070d
	v_mad_f32 v12, v12, -v0, v13                                ; d541000c 4436010c
	v_max_f32_e32 v12, 0x3e99999a, v12                          ; 201818ff 3e99999a
	v_mul_f32_e32 v5, v5, v12                                   ; 100a1905
	v_mul_f32_e32 v4, v4, v12                                   ; 10081904
	v_mul_f32_e32 v6, v6, v12                                   ; 100c1906
	v_max_f32_e32 v5, 0, v5                                     ; 200a0a80
	v_max_f32_e32 v4, 0, v4                                     ; 20080880
	v_max_f32_e32 v6, 0, v6                                     ; 200c0c80
	v_mul_f32_e32 v5, v5, v2                                    ; 100a0505
	v_mul_f32_e32 v4, v4, v2                                    ; 10080504
	v_mul_f32_e32 v6, v6, v2                                    ; 100c0506
	s_cbranch_scc0 BB9                                          ; bf840014
BB7:
	s_mov_b32 s0, 0x3e800000                                    ; be8003ff 3e800000
	v_cmp_eq_i32_e32 vcc, 0, v9                                 ; 7d041280
	v_mul_f32_e32 v0, s0, v5                                    ; 10000a00
	v_mul_f32_e32 v1, s0, v6                                    ; 10020c00
	v_mul_f32_e32 v2, s0, v4                                    ; 10040800
	v_cndmask_b32_e32 v5, v5, v0, vcc                           ; 020a0105
	v_cndmask_b32_e32 v6, v6, v1, vcc                           ; 020c0306
	v_cmp_eq_i32_e32 vcc, 1, v9                                 ; 7d041281
	v_mul_f32_e32 v10, s0, v5                                   ; 10140a00
	v_mul_f32_e32 v3, s0, v6                                    ; 10060c00
	v_cndmask_b32_e32 v4, v4, v2, vcc                           ; 02080504
	v_cndmask_b32_e32 v6, v6, v3, vcc                           ; 020c0706
	v_cmp_eq_i32_e32 vcc, 2, v9                                 ; 7d041282
	v_mul_f32_e32 v8, s0, v4                                    ; 10100800
	v_mul_f32_e32 v11, s0, v6                                   ; 10160c00
	v_cndmask_b32_e32 v5, v5, v10, vcc                          ; 020a1505
	v_cndmask_b32_e32 v4, v4, v8, vcc                           ; 02081104
	v_cmp_eq_i32_e32 vcc, 3, v9                                 ; 7d041283
	v_cndmask_b32_e32 v6, v6, v11, vcc                          ; 020c1706
BB9:
	v_cvt_pkrtz_f16_f32_e32 v4, v4, v5                          ; 5e080b04
	v_cvt_pkrtz_f16_f32_e32 v6, v6, v7                          ; 5e0c0f06
	exp mrt0 v4, v4, v6, v6 done compr vm                       ; f8001c0f 80800604
	s_endpgm                                                    ; bf810000
BB10:
	exp null off, off, off, off done vm                         ; f8001890 80808080
	s_endpgm                                                    ; bf810000
