# Pixel Shader
BB0:
	s_mov_b32 s0, s3                                            ; be800303
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_clause 0x6                                                ; bfa10006
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_load_dwordx4 s[4:7], s[2:3], 0x50                         ; f4080101 fa000050
	s_load_dwordx8 s[16:23], s[2:3], 0x60                       ; f40c0401 fa000060
	s_load_dwordx4 s[24:27], s[2:3], 0xb0                       ; f4080601 fa0000b0
	s_load_dwordx8 s[32:39], s[2:3], 0xc0                       ; f40c0801 fa0000c0
	s_load_dwordx4 s[28:31], s[2:3], 0x110                      ; f4080701 fa000110
	s_load_dwordx4 s[40:43], s[2:3], 0x1e0                      ; f4080a01 fa0001e0
	s_wqm_b64 exec, exec                                        ; befe0a7e
	s_mov_b32 m0, s0                                            ; befc0300
	v_interp_p1_f32_e32 v2, v0, attr0.y                         ; c8080100
	v_interp_p1_f32_e32 v0, v0, attr0.x                         ; c8000000
	v_interp_p2_f32_e32 v2, v1, attr0.y                         ; c8090101
	v_interp_p2_f32_e32 v0, v1, attr0.x                         ; c8010001
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v[3:5], [v0, v2], s[8:15], s[4:7] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00220300 00000002
	image_sample  v[6:8], [v0, v2], s[16:23], s[24:27] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00c40600 00000002
	image_sample  v[9:11], [v0, v2], s[32:39], s[28:31] dmask:0x7 dim:SQ_RSRC_IMG_2D ; f080070a 00e80900 00000002
	s_buffer_load_dword s1, s[40:43], 0x48                      ; f4200054 fa000048
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_eq_i32 s1, 1                                          ; bf008101
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mad_f32 v7, 2.0, v7, -1.0                                 ; d5410007 03ce0ef4
	v_mad_f32 v8, 2.0, v8, -1.0                                 ; d5410008 03ce10f4
	v_mad_f32 v6, 2.0, v6, -1.0                                 ; d5410006 03ce0cf4
	v_mul_f32_e32 v12, v7, v7                                   ; 10180f07
	v_mac_f32_e32 v12, v8, v8                                   ; 3e181108
	v_mac_f32_e32 v12, v6, v6                                   ; 3e180d06
	v_rsq_f32_e32 v12, v12                                      ; 7e185d0c
	v_mul_f32_e32 v6, v6, v12                                   ; 100c1906
	v_mul_f32_e32 v7, v7, v12                                   ; 100e1907
	v_mul_f32_e32 v8, v8, v12                                   ; 10101908
	s_cbranch_scc0 BB2                                          ; bf84000a
BB1:
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x180                       ; f40c0201 fa000180
	s_load_dwordx4 s[0:3], s[2:3], 0x1d0                        ; f4080001 fa0001d0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v2], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020000 00000002
	s_branch BB3                                                ; bf820009
BB2:
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx8 s[8:15], s[2:3], 0x120                       ; f40c0201 fa000120
	s_load_dwordx4 s[0:3], s[2:3], 0x170                        ; f4080001 fa000170
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_sample  v0, [v0, v2], s[8:15], s[0:3] dmask:0x1 dim:SQ_RSRC_IMG_2D ; f080010a 00020000 00000002
BB3:
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_buffer_load_dword s0, s[40:43], 0x44                      ; f4200014 fa000044
	v_mul_f32_e32 v1, v4, v4                                    ; 10020904
	v_mac_f32_e32 v1, v5, v5                                    ; 3e020b05
	v_mac_f32_e32 v1, v3, v3                                    ; 3e020703
	v_rsq_f32_e32 v1, v1                                        ; 7e025d01
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_lg_i32 s0, 1                                          ; bf018100
	v_mul_f32_e32 v3, v3, v1                                    ; 10060303
	v_mul_f32_e32 v4, v4, v1                                    ; 10080304
	v_mul_f32_e32 v5, v5, v1                                    ; 100a0305
	v_mul_f32_e32 v5, v5, v8                                    ; 100a1105
	v_mad_f32 v4, v4, -v7, -v5                                  ; d5410004 c4160f04
	v_mad_f32 v3, v3, -v6, v4                                   ; d5410003 44120d03
	s_cbranch_scc0 BB5                                          ; bf840012
BB4:
	s_buffer_load_dword s0, s[40:43], 0x40                      ; f4200014 fa000040
	v_max_f32_e32 v3, 0.5, v3                                   ; 200606f0
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v9, v9, v3                                    ; 10120709
	v_mul_f32_e32 v10, v10, v3                                  ; 1014070a
	v_mul_f32_e32 v11, v11, v3                                  ; 1016070b
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_cmp_eq_i32 s0, 1                                          ; bf008100
	s_cselect_b64 vcc, -1, 0                                    ; 85ea80c1
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v1, v0, v9                                    ; 10021300
	v_mul_f32_e32 v2, v0, v10                                   ; 10041500
	v_mul_f32_e32 v0, v0, v11                                   ; 10001700
	v_cndmask_b32_e32 v9, v9, v1, vcc                           ; 02120309
	v_cndmask_b32_e32 v10, v10, v2, vcc                         ; 0214050a
	v_cndmask_b32_e32 v0, v11, v0, vcc                          ; 0200010b
	s_branch BB6                                                ; bf820003
BB5:
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mov_b32_e32 v9, v0                                        ; 7e120300
	v_mov_b32_e32 v10, v0                                       ; 7e140300
BB6:
	v_cvt_pkrtz_f16_f32_e64 v0, v0, 0                           ; d52f0000 00010100
	v_cvt_pkrtz_f16_f32_e32 v9, v9, v10                         ; 5e121509
	exp mrt0 v9, v9, v0, v0 done compr vm                       ; f8001c0f 80800009
	s_endpgm                                                    ; bf810000
