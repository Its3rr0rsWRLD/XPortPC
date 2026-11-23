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
	s_cbranch_execz BB15                                        ; bf88011b
BB10:
	s_load_dwordx4 s[0:3], s[0:1], 0x60                         ; f4080000 fa000060
	v_mul_u32_u24_e32 v7, 48, v7                                ; 160e0eb0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x5                                                ; bfa10005
	buffer_load_dwordx4 v[0:3], v7, s[0:3], s4 offen glc dlc    ; e038d000 04000007
	buffer_load_dwordx4 v[8:11], v7, s[0:3], s4 offen offset:16 glc dlc ; e038d010 04000807
	buffer_load_dwordx4 v[12:15], v7, s[0:3], s4 offen offset:32 glc dlc ; e038d020 04000c07
	buffer_load_dwordx4 v[16:19], v7, s[0:3], s4 offen offset:3072 glc dlc ; e038dc00 04001007
	buffer_load_dwordx4 v[20:23], v7, s[0:3], s4 offen offset:3088 glc dlc ; e038dc10 04001407
	buffer_load_dwordx4 v[24:27], v7, s[0:3], s4 offen offset:3104 glc dlc ; e038dc20 04001807
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_load_dwordx4 s[8:11], s[8:9], null                        ; f4080204 fa000000
	v_add_f32_e32 v4, v5, v6                                    ; 06080d05
	v_mul_f32_e32 v28, v5, v5                                   ; 10380b05
	v_mul_f32_e32 v30, v6, v6                                   ; 103c0d06
	v_add_nc_u32_e32 v7, 0x1000, v7                             ; 4a0e0eff 00001000
	v_sub_f32_e32 v4, 1.0, v4                                   ; 080808f2
	v_mul_f32_e32 v29, v28, v5                                  ; 103a0b1c
	v_mul_f32_e32 v28, 0x40400000, v28                          ; 103838ff 40400000
	v_mul_f32_e32 v31, v30, v6                                  ; 103e0d1e
	v_mul_f32_e32 v32, v4, v4                                   ; 10400904
	v_mul_f32_e32 v33, v32, v4                                  ; 10420920
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mul_f32_e32 v34, v0, v4                                   ; 10440900
	v_mul_f32_e32 v35, v1, v4                                   ; 10460901
	v_mul_f32_e32 v32, 0x40400000, v32                          ; 104040ff 40400000
	v_mul_f32_e32 v36, v2, v4                                   ; 10480902
	v_mul_f32_e32 v0, v0, v33                                   ; 10004300
	v_mul_f32_e32 v1, v1, v33                                   ; 10024301
	v_mul_f32_e32 v2, v2, v33                                   ; 10044302
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mac_f32_e32 v34, v8, v5                                   ; 3e440b08
	v_mac_f32_e32 v35, v9, v5                                   ; 3e460b09
	v_mac_f32_e32 v36, v10, v5                                  ; 3e480b0a
	v_mac_f32_e32 v0, v8, v29                                   ; 3e003b08
	v_mac_f32_e32 v1, v9, v29                                   ; 3e023b09
	v_mac_f32_e32 v2, v10, v29                                  ; 3e043b0a
	v_mov_b32_e32 v11, v1                                       ; 7e160301
	v_mov_b32_e32 v29, v2                                       ; 7e3a0302
	s_clause 0x2                                                ; bfa10002
	buffer_load_dwordx3 v[37:39], v7, s[0:3], s4 offen offset:2048 glc dlc ; e03cd800 04002507
	buffer_load_dwordx3 v[8:10], v7, s[0:3], s4 offen offset:2064 glc dlc ; e03cd810 04000807
	buffer_load_dwordx3 v[1:3], v7, s[0:3], s4 offen offset:2080 glc dlc ; e03cd820 04000107
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_clause 0x2                                                ; bfa10002
	s_buffer_load_dword s0, s[8:11], 0x80                       ; f4200004 fa000080
	s_buffer_load_dwordx16 s[16:31], s[8:11], 0x40              ; f4300404 fa000040
	s_buffer_load_dwordx16 s[32:47], s[8:11], null              ; f4300804 fa000000
	v_mul_f32_e32 v30, 0x40400000, v30                          ; 103c3cff 40400000
	s_waitcnt vmcnt(6)                                          ; bf8c3f76
	v_mac_f32_e32 v34, v12, v6                                  ; 3e440d0c
	v_mac_f32_e32 v35, v13, v6                                  ; 3e460d0d
	v_mac_f32_e32 v36, v14, v6                                  ; 3e480d0e
	v_mac_f32_e32 v0, v12, v31                                  ; 3e003f0c
	s_waitcnt vmcnt(5)                                          ; bf8c3f75
	v_mul_f32_e32 v16, v16, v32                                 ; 10204110
	v_mul_f32_e32 v17, v17, v28                                 ; 10223911
	v_mac_f32_e32 v11, v13, v31                                 ; 3e163f0d
	v_mac_f32_e32 v29, v14, v31                                 ; 3e3a3f0e
	v_mul_f32_e32 v18, v18, v28                                 ; 10243912
	s_waitcnt vmcnt(4)                                          ; bf8c3f74
	v_mul_f32_e32 v20, v20, v32                                 ; 10284114
	v_mul_f32_e32 v21, v21, v28                                 ; 102a3915
	v_mul_f32_e32 v22, v22, v28                                 ; 102c3916
	v_mul_f32_e32 v19, v19, v30                                 ; 10263d13
	v_mul_f32_e32 v23, v23, v30                                 ; 102e3d17
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mul_f32_e32 v24, v24, v32                                 ; 10304118
	v_mul_f32_e32 v25, v25, v28                                 ; 10323919
	v_mac_f32_e32 v0, v16, v5                                   ; 3e000b10
	v_mul_f32_e32 v26, v26, v28                                 ; 1034391a
	v_mac_f32_e32 v11, v20, v5                                  ; 3e160b14
	v_mac_f32_e32 v29, v24, v5                                  ; 3e3a0b18
	v_mac_f32_e32 v0, v17, v4                                   ; 3e000911
	v_mac_f32_e32 v11, v21, v4                                  ; 3e160915
	v_mac_f32_e32 v29, v25, v4                                  ; 3e3a0919
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_sub_f32_e64 v31, 1.0, s0                                  ; d504001f 000000f2
	v_mul_f32_e64 v7, s47, s19                                  ; d5080007 0000262f
	v_mul_f32_e64 v33, s44, s19                                 ; d5080021 0000262c
	v_mul_f32_e32 v34, v34, v31                                 ; 10443f22
	v_mul_f32_e32 v35, v35, v31                                 ; 10463f23
	v_mul_f32_e32 v36, v36, v31                                 ; 10483f24
	v_mad_f32 v7, s43, s18, v7                                  ; d5410007 041c242b
	v_mad_f32 v33, s40, s18, v33                                ; d5410021 04842428
	v_mad_f32 v7, s39, s17, v7                                  ; d5410007 041c2227
	v_mad_f32 v33, s36, s17, v33                                ; d5410021 04842224
	v_mad_f32 v7, s35, s16, v7                                  ; d5410007 041c2023
	v_mad_f32 v33, s32, s16, v33                                ; d5410021 04842020
	v_mul_f32_e64 v12, s44, s23                                 ; d508000c 00002e2c
	v_mul_f32_e64 v13, s45, s23                                 ; d508000d 00002e2d
	v_mul_f32_e64 v14, s46, s23                                 ; d508000e 00002e2e
	v_mul_f32_e64 v15, s47, s23                                 ; d508000f 00002e2f
	v_mad_f32 v12, s40, s22, v12                                ; d541000c 04302c28
	v_mad_f32 v13, s41, s22, v13                                ; d541000d 04342c29
	v_mad_f32 v14, s42, s22, v14                                ; d541000e 04382c2a
	v_mad_f32 v15, s43, s22, v15                                ; d541000f 043c2c2b
	v_mad_f32 v12, s36, s21, v12                                ; d541000c 04302a24
	v_mad_f32 v13, s37, s21, v13                                ; d541000d 04342a25
	v_mad_f32 v14, s38, s21, v14                                ; d541000e 04382a26
	v_mad_f32 v15, s39, s21, v15                                ; d541000f 043c2a27
	v_mad_f32 v12, s32, s20, v12                                ; d541000c 04302820
	v_mad_f32 v13, s33, s20, v13                                ; d541000d 04342821
	v_mad_f32 v14, s34, s20, v14                                ; d541000e 04382822
	v_mad_f32 v15, s35, s20, v15                                ; d541000f 043c2823
	v_mul_f32_e64 v16, s44, s27                                 ; d5080010 0000362c
	v_mul_f32_e64 v17, s45, s27                                 ; d5080011 0000362d
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mul_f32_e32 v38, v38, v32                                 ; 104c4126
	v_mul_f32_e32 v37, v37, v30                                 ; 104a3d25
	v_mad_f32 v16, s40, s26, v16                                ; d5410010 04403428
	v_mad_f32 v17, s41, s26, v17                                ; d5410011 04443429
	v_mac_f32_e32 v0, v38, v6                                   ; 3e000d26
	v_mul_f32_e64 v38, s46, s19                                 ; d5080026 0000262e
	v_mad_f32 v16, s36, s25, v16                                ; d5410010 04403224
	v_mad_f32 v17, s37, s25, v17                                ; d5410011 04443225
	v_mac_f32_e32 v0, v18, v6                                   ; 3e000d12
	v_mul_f32_e64 v18, s46, s27                                 ; d5080012 0000362e
	v_mad_f32 v38, s42, s18, v38                                ; d5410026 0498242a
	v_mad_f32 v16, s32, s24, v16                                ; d5410010 04403020
	v_mad_f32 v17, s33, s24, v17                                ; d5410011 04443021
	v_mul_f32_e32 v39, 0x40c00000, v39                          ; 104e4eff 40c00000
	v_mac_f32_e32 v0, v37, v4                                   ; 3e000925
	v_mul_f32_e64 v37, s45, s19                                 ; d5080025 0000262d
	v_mad_f32 v18, s42, s26, v18                                ; d5410012 0448342a
	v_mad_f32 v38, s38, s17, v38                                ; d5410026 04982226
	v_mul_f32_e64 v20, s44, s31                                 ; d5080014 00003e2c
	v_mul_f32_e64 v21, s45, s31                                 ; d5080015 00003e2d
	v_mul_f32_e32 v39, v39, v5                                  ; 104e0b27
	v_mul_f32_e64 v24, s46, s31                                 ; d5080018 00003e2e
	v_mac_f32_e32 v0, v19, v5                                   ; 3e000b13
	v_mul_f32_e64 v19, s47, s27                                 ; d5080013 0000362f
	v_mad_f32 v37, s41, s18, v37                                ; d5410025 04942429
	v_mul_f32_e64 v25, s47, s31                                 ; d5080019 00003e2f
	v_mad_f32 v18, s38, s25, v18                                ; d5410012 04483226
	v_mad_f32 v38, s34, s16, v38                                ; d5410026 04982022
	v_mad_f32 v20, s40, s30, v20                                ; d5410014 04503c28
	v_mad_f32 v21, s41, s30, v21                                ; d5410015 04543c29
	v_mul_f32_e32 v39, v39, v6                                  ; 104e0d27
	v_mad_f32 v24, s42, s30, v24                                ; d5410018 04603c2a
	v_mad_f32 v19, s43, s26, v19                                ; d5410013 044c342b
	v_mad_f32 v37, s37, s17, v37                                ; d5410025 04942225
	v_mad_f32 v25, s43, s30, v25                                ; d5410019 04643c2b
	v_mad_f32 v18, s34, s24, v18                                ; d5410012 04483022
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mul_f32_e32 v9, v9, v32                                   ; 10124109
	v_mad_f32 v20, s36, s29, v20                                ; d5410014 04503a24
	v_mad_f32 v21, s37, s29, v21                                ; d5410015 04543a25
	v_mac_f32_e32 v0, v39, v4                                   ; 3e000927
	v_mul_f32_e32 v8, v8, v30                                   ; 10103d08
	v_mad_f32 v24, s38, s29, v24                                ; d5410018 04603a26
	v_mad_f32 v19, s39, s25, v19                                ; d5410013 044c3227
	v_mad_f32 v37, s33, s16, v37                                ; d5410025 04942021
	v_mad_f32 v25, s39, s29, v25                                ; d5410019 04643a27
	v_mul_f32_e32 v10, 0x40c00000, v10                          ; 101414ff 40c00000
	v_mac_f32_e32 v11, v9, v6                                   ; 3e160d09
	v_mad_f32 v20, s32, s28, v20                                ; d5410014 04503820
	v_mad_f32 v21, s33, s28, v21                                ; d5410015 04543821
	v_mac_f32_e32 v34, s0, v0                                   ; 3e440000
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mul_f32_e32 v2, v2, v32                                   ; 10044102
	v_mad_f32 v24, s34, s28, v24                                ; d5410018 04603822
	v_mad_f32 v19, s35, s24, v19                                ; d5410013 044c3023
	v_mul_f32_e32 v1, v1, v30                                   ; 10023d01
	v_mul_f32_e32 v27, v27, v30                                 ; 10363d1b
	v_mad_f32 v25, s35, s28, v25                                ; d5410019 04643823
	v_mul_f32_e32 v10, v10, v5                                  ; 10140b0a
	v_mac_f32_e32 v11, v22, v6                                  ; 3e160d16
	v_mul_f32_e32 v3, 0x40c00000, v3                            ; 100606ff 40c00000
	v_mac_f32_e32 v29, v2, v6                                   ; 3e3a0d02
	v_mul_f32_e32 v10, v10, v6                                  ; 10140d0a
	v_mac_f32_e32 v11, v8, v4                                   ; 3e160908
	v_mul_f32_e32 v3, v3, v5                                    ; 10060b03
	v_mac_f32_e32 v29, v26, v6                                  ; 3e3a0d1a
	v_mac_f32_e32 v11, v23, v5                                  ; 3e160b17
	v_mul_f32_e32 v3, v3, v6                                    ; 10060d03
	v_mac_f32_e32 v29, v1, v4                                   ; 3e3a0901
	v_mac_f32_e32 v11, v10, v4                                  ; 3e16090a
	v_mac_f32_e32 v29, v27, v5                                  ; 3e3a0b1b
	v_mac_f32_e32 v35, s0, v11                                  ; 3e461600
	v_mac_f32_e32 v29, v3, v4                                   ; 3e3a0903
	v_mac_f32_e32 v36, s0, v29                                  ; 3e483a00
	v_mac_f32_e32 v20, v16, v36                                 ; 3e284910
	v_mac_f32_e32 v21, v17, v36                                 ; 3e2a4911
	v_mac_f32_e32 v24, v18, v36                                 ; 3e304912
	v_mac_f32_e32 v25, v19, v36                                 ; 3e324913
	v_mac_f32_e32 v20, v12, v35                                 ; 3e28470c
	v_mac_f32_e32 v21, v13, v35                                 ; 3e2a470d
	v_mac_f32_e32 v24, v14, v35                                 ; 3e30470e
	v_mac_f32_e32 v25, v15, v35                                 ; 3e32470f
	v_mac_f32_e32 v20, v33, v34                                 ; 3e284521
	v_mac_f32_e32 v21, v37, v34                                 ; 3e2a4525
	v_mac_f32_e32 v24, v38, v34                                 ; 3e304526
	v_mac_f32_e32 v25, v7, v34                                  ; 3e324507
	exp pos0 v20, v21, v24, v25 done vm                         ; f80018cf 19181514
BB15:
	s_endpgm                                                    ; bf810000
