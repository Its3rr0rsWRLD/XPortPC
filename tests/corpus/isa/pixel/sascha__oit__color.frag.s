# Pixel Shader
BB0:
	s_load_dwordx2 s[0:1], s[0:1], null                         ; f4040000 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_add_u32 s0, s0, s4                                        ; 80000400
	s_addc_u32 s1, s1, 0x7fff0000                               ; 8201ff01 7fff0000
	s_setreg_b32 hwreg(HW_REG_FLAT_SCR_LO), s0                  ; b980f814
	s_setreg_b32 hwreg(HW_REG_FLAT_SCR_HI), s1                  ; b981f815
	s_movk_i32 s3, 0x8000                                       ; b0038000
	s_load_dwordx8 s[8:15], s[2:3], null                        ; f40c0201 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	image_load v2, v2, s[8:15] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm a16 ; f0001108 40020202
	s_mov_b64 s[0:1], exec                                      ; be80047e
	s_mov_b32 s4, 0                                             ; be840380
BB1:
	s_cmpk_lt_i32 s4, 0x80                                      ; b3840080
	s_cselect_b64 s[6:7], -1, 0                                 ; 858680c1
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_ne_i32_e32 vcc, -1, v2                                ; 7d0a04c1
	s_nand_b64 s[6:7], vcc, s[6:7]                              ; 8c86066a
	s_and_saveexec_b64 s[6:7], s[6:7]                           ; be862406
BB2:
	v_mov_b32_e32 v0, s4                                        ; 7e000204
	s_andn2_b64 s[6:7], s[6:7], exec                            ; 8a867e06
	s_cbranch_scc0 BB10                                         ; bf840016
BB9:
	s_load_dwordx4 s[8:11], s[2:3], 0x20                        ; f4080201 fa000020
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	v_lshlrev_b32_e32 v2, 5, v2                                 ; 34040485
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x1                                                ; bfa10001
	buffer_load_dwordx4 v[4:7], v2, s[8:11], 0 offen            ; e0381000 80020402
	buffer_load_dwordx2 v[0:1], v2, s[8:11], 0 offen offset:16  ; e0341010 80020002
	s_mul_i32 s5, s4, 24                                        ; 93059804
	s_add_u32 s4, s4, 1                                         ; 80048104
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	scratch_store_dwordx4 off, v[4:7], s5                       ; dc784000 00050480
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_add_u32 s5, 16, s5                                        ; 80050590
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mov_b32_e32 v2, v1                                        ; 7e040301
	scratch_store_dwordx2 off, v[0:1], s5                       ; dc744000 00050080
	s_branch BB1                                                ; bf82ffe1
BB10:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_mov_b32 s2, 1                                             ; be820381
	s_mov_b64 s[4:5], exec                                      ; be84047e
BB11:
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_ge_u32_e32 s2, v0                                    ; 7dac0002
BB12:
	s_andn2_b64 s[4:5], s[4:5], exec                            ; 8a847e04
	s_cbranch_scc0 BB33                                         ; bf840039
BB19:
	s_mov_b64 exec, s[4:5]                                      ; befe0404
	s_mul_i32 s3, s2, 24                                        ; 93039802
	scratch_load_dwordx4 v[4:7], off, s3                        ; dc384000 04030080
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_add_u32 s3, 16, s3                                        ; 80030390
	scratch_load_dwordx2 v[2:3], off, s3                        ; dc344000 02030080
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b32 s3, s2                                            ; be830302
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mov_b32_e32 v1, v2                                        ; 7e020302
BB20:
	s_cmp_lg_i32 s3, 0                                          ; bf018003
	s_cbranch_scc0 BB22                                         ; bf840006
BB21:
	s_mul_i32 s6, s3, 24                                        ; 93069803
	scratch_load_dword v8, off, s6 offset:-8                    ; dc304ff8 08060080
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_cmp_lt_f32_e32 vcc, v8, v1                                ; 7c020308
	s_branch BB23                                               ; bf820001
BB22:
	s_mov_b64 vcc, 0                                            ; beea0480
BB23:
	s_not_b64 s[6:7], vcc                                       ; be86086a
	s_and_saveexec_b64 s[6:7], s[6:7]                           ; be862406
BB24:
	v_mov_b32_e32 v1, s3                                        ; 7e020203
	s_andn2_b64 s[6:7], s[6:7], exec                            ; 8a867e06
	s_cbranch_scc0 BB32                                         ; bf840015
BB31:
	s_mov_b64 exec, s[6:7]                                      ; befe0406
	s_add_u32 s6, s3, -1                                        ; 8006c103
	s_mul_i32 s7, s6, 24                                        ; 93079806
	scratch_load_dwordx4 v[8:11], off, s7                       ; dc384000 08070080
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_add_u32 s7, 16, s7                                        ; 80070790
	scratch_load_dwordx2 v[12:13], off, s7                      ; dc344000 0c070080
	s_mul_i32 s3, s3, 24                                        ; 93039803
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	scratch_store_dwordx4 off, v[8:11], s3                      ; dc784000 00030880
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_add_u32 s3, 16, s3                                        ; 80030390
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	scratch_store_dwordx2 off, v[12:13], s3                     ; dc744000 00030c80
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_mov_b32 s3, s6                                            ; be830306
	s_branch BB20                                               ; bf82ffdd
BB32:
	s_mov_b64 exec, s[4:5]                                      ; befe0404
	v_mul_lo_u32 v1, 24, v1                                     ; d5690001 00020298
	scratch_store_dwordx4 v1, v[4:7], off                       ; dc784000 007d0401
	v_add_nc_u32_e32 v1, 16, v1                                 ; 4a020290
	scratch_store_dwordx2 v1, v[2:3], off                       ; dc744000 007d0201
	s_add_u32 s2, s2, 1                                         ; 80028102
	s_branch BB11                                               ; bf82ffc3
BB33:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	s_mov_b32 s2, 0                                             ; be820380
	s_mov_b64 s[4:5], exec                                      ; be84047e
	v_mov_b32_e32 v1, 1.0                                       ; 7e0202f2
	v_mov_b32_e32 v2, 0x3ccccccd                                ; 7e0402ff 3ccccccd
	v_mov_b32_e32 v3, 0x3ccccccd                                ; 7e0602ff 3ccccccd
	v_mov_b32_e32 v4, 0x3ccccccd                                ; 7e0802ff 3ccccccd
BB34:
	s_waitcnt_depctr 0xfffe                                     ; bfa3fffe
	v_cmpx_ge_i32_e32 s2, v0                                    ; 7d2c0002
BB35:
	s_andn2_b64 s[4:5], s[4:5], exec                            ; 8a847e04
	s_cbranch_scc0 BB43                                         ; bf84000f
BB42:
	s_mov_b64 exec, s[4:5]                                      ; befe0404
	s_mul_i32 s3, s2, 24                                        ; 93039802
	scratch_load_dwordx4 v[8:11], off, s3                       ; dc384000 08030080
	s_add_u32 s2, s2, 1                                         ; 80028102
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_sub_f32_e32 v8, v8, v4                                    ; 08100908
	v_sub_f32_e32 v9, v9, v3                                    ; 08120709
	v_sub_f32_e32 v10, v10, v2                                  ; 0814050a
	v_sub_f32_e32 v5, v11, v1                                   ; 080a030b
	v_mac_f32_e32 v4, v11, v8                                   ; 3e08110b
	v_mac_f32_e32 v3, v11, v9                                   ; 3e06130b
	v_mac_f32_e32 v2, v11, v10                                  ; 3e04150b
	v_mac_f32_e32 v1, v11, v5                                   ; 3e020b0b
	s_branch BB34                                               ; bf82ffed
BB43:
	s_mov_b64 exec, s[0:1]                                      ; befe0400
	v_cvt_pkrtz_f16_f32_e32 v4, v4, v3                          ; 5e080704
	v_cvt_pkrtz_f16_f32_e32 v2, v2, v1                          ; 5e040302
	exp mrt0 v4, v4, v2, v2 done compr vm                       ; f8001c0f 80800204
	s_endpgm                                                    ; bf810000
