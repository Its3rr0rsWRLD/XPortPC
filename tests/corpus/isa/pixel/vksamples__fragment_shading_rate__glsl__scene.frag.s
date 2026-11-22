# Pixel Shader
BB0:
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s4                                            ; befc0304
	s_cmp_eq_i32 s3, 0                                          ; bf008003
	v_interp_p1_f32_e32 v3, v0, attr0.y                         ; c80c0100
	v_interp_p1_f32_e32 v4, v0, attr0.x                         ; c8100000
	v_interp_p2_f32_e32 v3, v1, attr0.y                         ; c80d0101
	v_interp_p2_f32_e32 v4, v1, attr0.x                         ; c8110001
	s_cbranch_scc0 BB3                                          ; bf84000b
BB1:
	s_mov_b32 s0, s2                                            ; be800302
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[0:1], 0x20                        ; f40c0200 fa000020
	s_load_dwordx4 s[4:7], s[0:1], 0x70                         ; f4080100 fa000070
	v_sub_f32_e32 v5, 1.0, v3                                   ; 080a06f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample v[5:7], v[4:5], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f0800708 00220504
BB3:
	s_cmp_eq_i32 s3, 1                                          ; bf008103
	s_cbranch_scc0 BB6                                          ; bf840050
BB4:
	s_mov_b32 s0, s2                                            ; be800302
	s_movk_i32 s1, 0x8000                                       ; b0018000
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[0:1], 0x80                        ; f40c0200 fa000080
	s_load_dwordx4 s[4:7], s[0:1], 0xd0                         ; f4080100 fa0000d0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[3:5], [v4, v3], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220304 00000003
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_interp_p1_f32_e32 v6, v0, attr0.w                         ; c8180300
	v_interp_p1_f32_e32 v8, v0, attr1.x                         ; c8200400
	v_interp_p1_f32_e32 v9, v0, attr0.z                         ; c8240200
	v_interp_p1_f32_e32 v10, v0, attr2.y                        ; c8280900
	v_interp_p1_f32_e32 v12, v0, attr2.z                        ; c8300a00
	v_interp_p1_f32_e32 v13, v0, attr2.x                        ; c8340800
	v_interp_p2_f32_e32 v6, v1, attr0.w                         ; c8190301
	v_interp_p2_f32_e32 v8, v1, attr1.x                         ; c8210401
	v_interp_p2_f32_e32 v9, v1, attr0.z                         ; c8250201
	v_interp_p2_f32_e32 v10, v1, attr2.y                        ; c8290901
	v_interp_p2_f32_e32 v12, v1, attr2.z                        ; c8310a01
	v_interp_p2_f32_e32 v13, v1, attr2.x                        ; c8350801
	v_interp_p1_f32_e32 v14, v0, attr1.z                        ; c8380600
	v_interp_p2_f32_e32 v14, v1, attr1.z                        ; c8390601
	v_interp_p1_f32_e32 v16, v0, attr1.w                        ; c8400700
	v_interp_p2_f32_e32 v16, v1, attr1.w                        ; c8410701
	v_mul_f32_e32 v7, v6, v6                                    ; 100e0d06
	v_mul_f32_e32 v11, v10, v10                                 ; 1016150a
	v_mul_f32_e32 v15, v14, v14                                 ; 101e1d0e
	v_interp_p1_f32_e32 v0, v0, attr1.y                         ; c8000500
	v_interp_p2_f32_e32 v0, v1, attr1.y                         ; c8010501
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
	v_mac_f32_e32 v11, v12, v12                                 ; 3e16190c
	v_mac_f32_e32 v15, v16, v16                                 ; 3e1e2110
	v_mac_f32_e32 v7, v9, v9                                    ; 3e0e1309
	v_mac_f32_e32 v11, v13, v13                                 ; 3e161b0d
	v_mac_f32_e32 v15, v0, v0                                   ; 3e1e0100
	v_rsq_f32_e32 v7, v7                                        ; 7e0e5d07
	v_rsq_f32_e32 v11, v11                                      ; 7e165d0b
	v_rsq_f32_e32 v15, v15                                      ; 7e1e5d0f
	v_mul_f32_e32 v6, v6, v7                                    ; 100c0f06
	v_mul_f32_e32 v8, v8, v7                                    ; 10100f08
	v_mul_f32_e32 v9, v9, v7                                    ; 10120f09
	v_mul_f32_e32 v12, v12, v11                                 ; 1018170c
	v_mul_f32_e32 v13, v13, v11                                 ; 101a170d
	v_mul_f32_e32 v10, v10, v11                                 ; 1014170a
	v_mul_f32_e32 v0, v0, v15                                   ; 10001f00
	v_mul_f32_e32 v14, v14, v15                                 ; 101c1f0e
	v_mul_f32_e32 v16, v16, v15                                 ; 10201f10
	v_mul_f32_e32 v17, v12, v8                                  ; 1022110c
	v_mad_f32 v18, v10, -v6, -v17                               ; d5410012 c4460d0a
	v_mac_f32_e32 v17, v10, v6                                  ; 3e220d0a
	v_mad_f32 v18, v13, -v9, v18 mul:2                          ; d5410012 4c4a130d
	v_mac_f32_e32 v17, v13, v9                                  ; 3e22130d
	v_mad_f32 v8, v8, -v18, -v12                                ; d5410008 c4322508
	v_mad_f32 v19, v9, -v18, -v13                               ; d5410013 c4362509
	v_mad_f32 v20, v6, -v18, -v10                               ; d5410014 c42a2506
	v_max_f32_e32 v17, 0, v17                                   ; 20222280
	v_mul_f32_e32 v8, v8, v16                                   ; 10102108
	v_mac_f32_e32 v8, v20, v14                                  ; 3e101d14
	v_mac_f32_e32 v8, v19, v0                                   ; 3e100113
	v_max_f32_e32 v8, 0, v8                                     ; 20101080
	v_mul_f32_e32 v8, v8, v8                                    ; 10101108
	(then repeated 1 times)
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_add_f32_e32 v6, v4, v17                                   ; 060c2304
	v_add_f32_e32 v3, v3, v17                                   ; 06062303
	v_add_f32_e32 v7, v5, v17                                   ; 060e2305
	v_mac_f32_e32 v6, v8, v8                                    ; 3e0c1108
	v_mad_f32 v5, v8, v8, v3                                    ; d5410005 040e1108
	v_mac_f32_e32 v7, v8, v8                                    ; 3e0e1108
BB6:
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx4 s[0:3], s[2:3], null                         ; f4080001 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_buffer_load_dword s0, s[0:3], 0xc0                        ; f4200000 fa0000c0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	s_cbranch_scc0 BB9                                          ; bf840026
BB7:
	v_bfe_u32 v0, v2, 4, 2                                      ; d5480000 02090902
	v_bfe_u32 v2, v2, 2, 2                                      ; d5480002 02090502
	v_cmp_eq_i32_e32 vcc, 1, v0                                 ; 7d040081
	v_cndmask_b32_e64 v1, 0, 1, vcc                             ; d5010001 01a90280
	v_cmp_eq_i32_e32 vcc, 1, v2                                 ; 7d040481
	v_cndmask_b32_e64 v2, 0, 4, vcc                             ; d5010002 01a90880
	v_or_b32_e32 v2, v2, v1                                     ; 38040302
	v_cmp_class_f16_e32 vcc, 0x7c01, v2                         ; 7d1e04ff 00007c01
	v_cndmask_b32_e64 v3, 1, 2, vcc                             ; d5010003 01a90481
	v_cmp_class_f32_e32 vcc, -1, v2                             ; 7d1004c1
	v_cndmask_b32_e64 v3, v3, 4, vcc                            ; d5010003 01a90903
	v_cmp_class_f32_e32 vcc, 0xff800000, v2                     ; 7d1004ff ff800000
	v_cndmask_b32_e64 v4, 1, 2, vcc                             ; d5010004 01a90481
	v_cmp_class_f32_e32 vcc, -1.0, v2                           ; 7d1004f3
	v_cndmask_b32_e64 v4, v4, 4, vcc                            ; d5010004 01a90904
	v_cmp_eq_i32_e32 vcc, 1, v3                                 ; 7d040681
	v_cmp_eq_i32_e64 s[0:1], 1, v4                              ; d4820000 00020881
	v_add_nc_u32_e32 v3, v3, v4                                 ; 4a060903
	s_and_b64 vcc, vcc, s[0:1]                                  ; 87ea006a
	v_cvt_f32_i32_e32 v3, v3                                    ; 7e060b03
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mad_f32 v3, 0x3d4ccccd, -v3, v5                           ; d5410003 441606ff 3d4ccccd
	v_cndmask_b32_e32 v7, v3, v5, vcc                           ; 020e0b03
	v_mov_b32_e32 v5, v7                                        ; 7e0a0307
	v_mov_b32_e32 v6, v7                                        ; 7e0c0307
BB9:
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cvt_pkrtz_f16_f32_e64 v7, v7, 1.0                         ; d52f0007 0001e507
	v_cvt_pkrtz_f16_f32_e32 v5, v5, v6                          ; 5e0a0d05
	exp mrt0 v5, v5, v7, v7 done compr vm                       ; f8001c0f 80800705
	s_endpgm                                                    ; bf810000
