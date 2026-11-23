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
	s_cbranch_execz BB15                                        ; bf8800b7
BB10:
	s_load_dwordx4 s[0:3], s[0:1], 0x60                         ; f4080000 fa000060
	v_mul_u32_u24_e32 v7, 48, v7                                ; 160e0eb0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x3                                                ; bfa10003
	buffer_load_dwordx4 v[0:3], v7, s[0:3], s4 offen glc dlc    ; e038d000 04000007
	buffer_load_dwordx3 v[8:10], v7, s[0:3], s4 offen offset:16 glc dlc ; e03cd010 04000807
	buffer_load_dwordx3 v[11:13], v7, s[0:3], s4 offen offset:32 glc dlc ; e03cd020 04000b07
	buffer_load_dwordx2 v[14:15], v7, s[0:3], s4 offen offset:3072 glc dlc ; e034dc00 04000e07
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_load_dwordx4 s[0:3], s[8:9], null                         ; f4080004 fa000000
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x1                                                ; bfa10001
	s_buffer_load_dwordx16 s[16:31], s[0:3], 0x40               ; f4300400 fa000040
	s_buffer_load_dwordx16 s[0:15], s[0:3], null                ; f4300000 fa000000
	v_add_f32_e32 v16, v5, v6                                   ; 06200d05
	v_sub_f32_e32 v16, 1.0, v16                                 ; 082020f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v17, s12, s19                                 ; d5080011 0000260c
	v_mul_f32_e64 v18, s13, s19                                 ; d5080012 0000260d
	v_mul_f32_e64 v19, s14, s19                                 ; d5080013 0000260e
	v_mul_f32_e64 v20, s15, s19                                 ; d5080014 0000260f
	v_mad_f32 v17, s8, s18, v17                                 ; d5410011 04442408
	v_mad_f32 v18, s9, s18, v18                                 ; d5410012 04482409
	v_mad_f32 v19, s10, s18, v19                                ; d5410013 044c240a
	v_mad_f32 v20, s11, s18, v20                                ; d5410014 0450240b
	v_mad_f32 v17, s4, s17, v17                                 ; d5410011 04442204
	v_mad_f32 v18, s5, s17, v18                                 ; d5410012 04482205
	v_mul_f32_e64 v21, s12, s23                                 ; d5080015 00002e0c
	v_mad_f32 v19, s6, s17, v19                                 ; d5410013 044c2206
	v_mul_f32_e64 v22, s13, s23                                 ; d5080016 00002e0d
	v_mad_f32 v20, s7, s17, v20                                 ; d5410014 04502207
	v_mul_f32_e64 v23, s14, s23                                 ; d5080017 00002e0e
	v_mul_f32_e64 v24, s15, s23                                 ; d5080018 00002e0f
	v_mad_f32 v17, s0, s16, v17                                 ; d5410011 04442000
	v_mad_f32 v18, s1, s16, v18                                 ; d5410012 04482001
	v_mad_f32 v21, s8, s22, v21                                 ; d5410015 04542c08
	v_mad_f32 v19, s2, s16, v19                                 ; d5410013 044c2002
	v_mad_f32 v22, s9, s22, v22                                 ; d5410016 04582c09
	v_mad_f32 v20, s3, s16, v20                                 ; d5410014 04502003
	v_mad_f32 v23, s10, s22, v23                                ; d5410017 045c2c0a
	v_mad_f32 v24, s11, s22, v24                                ; d5410018 04602c0b
	v_mad_f32 v21, s4, s21, v21                                 ; d5410015 04542a04
	v_mad_f32 v22, s5, s21, v22                                 ; d5410016 04582a05
	v_mul_f32_e64 v25, s12, s27                                 ; d5080019 0000360c
	v_mad_f32 v23, s6, s21, v23                                 ; d5410017 045c2a06
	v_mul_f32_e64 v26, s13, s27                                 ; d508001a 0000360d
	v_mul_f32_e64 v27, s14, s27                                 ; d508001b 0000360e
	v_mad_f32 v24, s7, s21, v24                                 ; d5410018 04602a07
	v_mad_f32 v21, s0, s20, v21                                 ; d5410015 04542800
	v_mul_f32_e64 v28, s15, s27                                 ; d508001c 0000360f
	v_mad_f32 v22, s1, s20, v22                                 ; d5410016 04582801
	v_mad_f32 v25, s8, s26, v25                                 ; d5410019 04643408
	v_mad_f32 v23, s2, s20, v23                                 ; d5410017 045c2802
	v_mad_f32 v26, s9, s26, v26                                 ; d541001a 04683409
	v_mad_f32 v27, s10, s26, v27                                ; d541001b 046c340a
	v_mad_f32 v24, s3, s20, v24                                 ; d5410018 04602803
	v_mad_f32 v28, s11, s26, v28                                ; d541001c 0470340b
	v_mad_f32 v25, s4, s25, v25                                 ; d5410019 04643204
	v_mad_f32 v26, s5, s25, v26                                 ; d541001a 04683205
	v_mul_f32_e64 v29, s12, s31                                 ; d508001d 00003e0c
	v_mad_f32 v27, s6, s25, v27                                 ; d541001b 046c3206
	v_mul_f32_e64 v30, s13, s31                                 ; d508001e 00003e0d
	v_mad_f32 v28, s7, s25, v28                                 ; d541001c 04703207
	v_mul_f32_e64 v31, s14, s31                                 ; d508001f 00003e0e
	v_mad_f32 v25, s0, s24, v25                                 ; d5410019 04643000
	v_mad_f32 v26, s1, s24, v26                                 ; d541001a 04683001
	v_mad_f32 v29, s8, s30, v29                                 ; d541001d 04743c08
	v_mad_f32 v27, s2, s24, v27                                 ; d541001b 046c3002
	v_mad_f32 v30, s9, s30, v30                                 ; d541001e 04783c09
	v_mad_f32 v28, s3, s24, v28                                 ; d541001c 04703003
	v_mad_f32 v31, s10, s30, v31                                ; d541001f 047c3c0a
	v_mad_f32 v29, s4, s29, v29                                 ; d541001d 04743a04
	v_mad_f32 v30, s5, s29, v30                                 ; d541001e 04783a05
	v_mad_f32 v31, s6, s29, v31                                 ; d541001f 047c3a06
	v_mad_f32 v29, s0, s28, v29                                 ; d541001d 04743800
	v_mad_f32 v30, s1, s28, v30                                 ; d541001e 04783801
	v_mad_f32 v31, s2, s28, v31                                 ; d541001f 047c3802
	s_waitcnt vmcnt(3)                                          ; bf8c3f73
	v_mul_f32_e32 v0, v5, v0                                    ; 10000105
	v_mul_f32_e32 v1, v5, v1                                    ; 10020305
	v_mul_f32_e32 v5, v5, v2                                    ; 100a0505
	v_mul_f32_e64 v2, s15, s31                                  ; d5080002 00003e0f
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mac_f32_e32 v0, v6, v8                                    ; 3e001106
	v_mac_f32_e32 v1, v6, v9                                    ; 3e021306
	v_mac_f32_e32 v5, v6, v10                                   ; 3e0a1506
	v_mad_f32 v2, s11, s30, v2                                  ; d5410002 04083c0b
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v0, v16, v11                                  ; 3e001710
	v_mac_f32_e32 v1, v16, v12                                  ; 3e021910
	v_mac_f32_e32 v5, v16, v13                                  ; 3e0a1b10
	v_mad_f32 v2, s7, s29, v2                                   ; d5410002 04083a07
	v_mac_f32_e32 v29, v25, v5                                  ; 3e3a0b19
	v_mac_f32_e32 v30, v26, v5                                  ; 3e3c0b1a
	v_mac_f32_e32 v31, v27, v5                                  ; 3e3e0b1b
	v_mad_f32 v2, s3, s28, v2                                   ; d5410002 04083803
	v_mac_f32_e32 v29, v21, v1                                  ; 3e3a0315
	v_mac_f32_e32 v30, v22, v1                                  ; 3e3c0316
	v_mac_f32_e32 v31, v23, v1                                  ; 3e3e0317
	v_mac_f32_e32 v2, v28, v5                                   ; 3e040b1c
	v_mac_f32_e32 v29, v17, v0                                  ; 3e3a0111
	v_mac_f32_e32 v30, v18, v0                                  ; 3e3c0112
	v_mac_f32_e32 v31, v19, v0                                  ; 3e3e0113
	v_mac_f32_e32 v2, v24, v1                                   ; 3e040318
	v_mac_f32_e32 v2, v20, v0                                   ; 3e040114
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	exp pos0 v29, v30, v31, v2 done vm                          ; f80018cf 021f1e1d
	exp param0 v3, v14, v15, off                                ; f8000207 800f0e03
BB15:
	s_endpgm                                                    ; bf810000
