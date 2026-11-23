# Tessellation Evaluation Shader as ESGS
BB0:
	s_setprio 3                                                 ; bf8f0003
	s_barrier                                                   ; bf8a0000
	s_and_b32 s5, s3, 0xf000000                                 ; 8705ff03 0f000000
	s_cbranch_scc1 BB3                                          ; bf850007
BB1:
	s_bfe_u32 s5, s2, 0x90016                                   ; 9385ff02 00090016
	s_lshl_b32 s5, s5, 12                                       ; 8f058c05
	s_bfe_u32 s2, s2, 0x9000c                                   ; 9382ff02 0009000c
	s_or_b32 m0, s5, s2                                         ; 887c0205
	s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)                         ; bf900009
BB3:
	s_lshl_b32 s2, s3, 8                                        ; 8f028803
	s_bfe_u64 exec, -1, s2                                      ; 94fe02c1
	s_cbranch_execz BB9                                         ; bf880002
BB4:
	exp prim v0, off, off, off done                             ; f8000941 80808000
BB9:
	s_pack_ll_b32_b16 s3, 0, s3                                 ; 99030380
	s_waitcnt expcnt(0)                                         ; bf8cff0f
	s_bfe_u64 exec, -1, s3                                      ; 94fe03c1
	s_cbranch_execz BB15                                        ; bf88005f
BB10:
	s_load_dwordx4 s[0:3], s[0:1], 0x60                         ; f4080000 fa000060
	v_mul_u32_u24_e32 v7, 48, v7                                ; 160e0eb0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x5                                                ; bfa10005
	buffer_load_dwordx4 v[8:11], v7, s[0:3], s4 offen offset:32 glc dlc ; e038d020 04000807
	buffer_load_dwordx4 v[12:15], v7, s[0:3], s4 offen offset:16 glc dlc ; e038d010 04000c07
	buffer_load_dwordx4 v[16:19], v7, s[0:3], s4 offen glc dlc  ; e038d000 04001007
	buffer_load_dwordx4 v[20:23], v7, s[0:3], s4 offen offset:3104 glc dlc ; e038dc20 04001407
	buffer_load_dwordx4 v[24:27], v7, s[0:3], s4 offen offset:3088 glc dlc ; e038dc10 04001807
	buffer_load_dwordx4 v[28:31], v7, s[0:3], s4 offen offset:3072 glc dlc ; e038dc00 04001c07
	v_add_f32_e32 v1, v5, v6                                    ; 06020d05
	v_add_nc_u32_e32 v0, 0x1000, v7                             ; 4a000eff 00001000
	v_add_nc_u32_e32 v7, 0x2000, v7                             ; 4a0e0eff 00002000
	v_sub_f32_e32 v1, 1.0, v1                                   ; 080202f2
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mul_f32_e32 v8, v8, v5                                    ; 10100b08
	v_mul_f32_e32 v9, v9, v5                                    ; 10120b09
	v_mul_f32_e32 v10, v10, v5                                  ; 10140b0a
	v_mul_f32_e32 v11, v11, v5                                  ; 10160b0b
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v8, v12, v6                                   ; 3e100d0c
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mul_f32_e32 v21, v21, v5                                  ; 102a0b15
	v_mov_b32_e32 v4, v1                                        ; 7e080301
	v_mac_f32_e32 v9, v13, v6                                   ; 3e120d0d
	v_mac_f32_e32 v10, v14, v6                                  ; 3e140d0e
	v_mul_f32_e32 v22, v22, v5                                  ; 102c0b16
	v_mul_f32_e32 v20, v20, v5                                  ; 10280b14
	v_mac_f32_e32 v11, v15, v6                                  ; 3e160d0f
	v_mac_f32_e32 v8, v16, v1                                   ; 3e100310
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v21, v25, v6                                  ; 3e2a0d19
	v_mac_f32_e32 v9, v17, v1                                   ; 3e120311
	v_mac_f32_e32 v10, v18, v1                                  ; 3e140312
	v_mac_f32_e32 v22, v26, v6                                  ; 3e2c0d1a
	v_mac_f32_e32 v20, v24, v6                                  ; 3e280d18
	v_mac_f32_e32 v11, v19, v1                                  ; 3e160313
	s_clause 0x5                                                ; bfa10005
	buffer_load_dwordx4 v[12:15], v0, s[0:3], s4 offen offset:2080 glc dlc ; e038d820 04000c00
	buffer_load_dwordx4 v[16:19], v7, s[0:3], s4 offen offset:1056 glc dlc ; e038d420 04001007
	buffer_load_dwordx4 v[32:35], v0, s[0:3], s4 offen offset:2064 glc dlc ; e038d810 04002000
	buffer_load_dwordx4 v[36:39], v7, s[0:3], s4 offen offset:1040 glc dlc ; e038d410 04002407
	buffer_load_dwordx4 v[0:3], v0, s[0:3], s4 offen offset:2048 glc dlc ; e038d800 04000000
	buffer_load_dwordx4 v[24:27], v7, s[0:3], s4 offen offset:1024 glc dlc ; e038d400 04001807
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mac_f32_e32 v21, v29, v4                                  ; 3e2a091d
	v_mac_f32_e32 v22, v30, v4                                  ; 3e2c091e
	v_mac_f32_e32 v20, v28, v4                                  ; 3e28091c
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mul_f32_e32 v14, v14, v5                                  ; 101c0b0e
	v_mul_f32_e32 v15, v15, v5                                  ; 101e0b0f
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mul_f32_e32 v18, v18, v5                                  ; 10240b12
	v_mul_f32_e32 v19, v19, v5                                  ; 10260b13
	v_mul_f32_e32 v16, v16, v5                                  ; 10200b10
	v_mul_f32_e32 v17, v17, v5                                  ; 10220b11
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mac_f32_e32 v14, v34, v6                                  ; 3e1c0d22
	v_mac_f32_e32 v15, v35, v6                                  ; 3e1e0d23
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v18, v38, v6                                  ; 3e240d26
	v_mac_f32_e32 v19, v39, v6                                  ; 3e260d27
	v_mac_f32_e32 v16, v36, v6                                  ; 3e200d24
	v_mac_f32_e32 v17, v37, v6                                  ; 3e220d25
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v14, v2, v4                                   ; 3e1c0902
	v_mac_f32_e32 v15, v3, v4                                   ; 3e1e0903
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v18, v26, v4                                  ; 3e24091a
	v_mac_f32_e32 v19, v27, v4                                  ; 3e26091b
	v_mac_f32_e32 v16, v24, v4                                  ; 3e200918
	v_mac_f32_e32 v17, v25, v4                                  ; 3e220919
	exp pos0 v8, v9, v10, v11 done vm                           ; f80018cf 0b0a0908
	exp param0 v20, v21, v22, v31                               ; f800020f 1f161514
	exp param1 v0, v1, v14, v15                                 ; f800021f 0f0e0100
	exp param2 v16, v17, v18, v19                               ; f800022f 13121110
BB15:
	s_endpgm                                                    ; bf810000
