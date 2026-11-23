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
	s_cbranch_execz BB15                                        ; bf8800b8
BB10:
	s_movk_i32 s9, 0x8000                                       ; b0098000
	s_clause 0x1                                                ; bfa10001
	s_load_dwordx4 s[8:11], s[8:9], null                        ; f4080204 fa000000
	s_load_dwordx4 s[0:3], s[0:1], 0x60                         ; f4080000 fa000060
	v_mul_u32_u24_e32 v7, 48, v7                                ; 160e0eb0
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	s_clause 0x2                                                ; bfa10002
	buffer_load_dwordx4 v[0:3], v7, s[0:3], s4 offen glc dlc    ; e038d000 04000007
	buffer_load_dwordx4 v[8:11], v7, s[0:3], s4 offen offset:16 glc dlc ; e038d010 04000807
	buffer_load_dwordx4 v[12:15], v7, s[0:3], s4 offen offset:32 glc dlc ; e038d020 04000c07
	s_buffer_load_dwordx16 s[16:31], s[8:11], 0x40              ; f4300404 fa000040
	s_waitcnt_depctr 0xffe3                                     ; bfa3ffe3
	s_buffer_load_dwordx16 s[0:15], s[8:11], null               ; f4300004 fa000000
	v_add_f32_e32 v4, v5, v6                                    ; 06080d05
	v_sub_f32_e32 v4, 1.0, v4                                   ; 080808f2
	s_waitcnt lgkmcnt(0)                                        ; bf8cc07f
	v_mul_f32_e64 v7, s14, s19                                  ; d5080007 0000260e
	s_waitcnt vmcnt(2)                                          ; bf8c3f72
	v_mul_f32_e32 v0, v0, v5                                    ; 10000b00
	v_mul_f32_e32 v1, v1, v5                                    ; 10020b01
	v_mul_f32_e32 v2, v2, v5                                    ; 10040b02
	v_mul_f32_e32 v3, v3, v5                                    ; 10060b03
	v_mul_f32_e64 v5, s12, s19                                  ; d5080005 0000260c
	v_mad_f32 v7, s10, s18, v7                                  ; d5410007 041c240a
	s_waitcnt vmcnt(1)                                          ; bf8c3f71
	v_mac_f32_e32 v0, v8, v6                                    ; 3e000d08
	v_mul_f32_e64 v8, s15, s19                                  ; d5080008 0000260f
	v_mac_f32_e32 v1, v9, v6                                    ; 3e020d09
	v_mac_f32_e32 v2, v10, v6                                   ; 3e040d0a
	v_mac_f32_e32 v3, v11, v6                                   ; 3e060d0b
	v_mul_f32_e64 v6, s13, s19                                  ; d5080006 0000260d
	v_mad_f32 v5, s8, s18, v5                                   ; d5410005 04142408
	v_mad_f32 v7, s6, s17, v7                                   ; d5410007 041c2206
	s_waitcnt vmcnt(0)                                          ; bf8c3f70
	v_mac_f32_e32 v0, v12, v4                                   ; 3e00090c
	v_mul_f32_e64 v9, s12, s23                                  ; d5080009 00002e0c
	v_mul_f32_e64 v10, s13, s23                                 ; d508000a 00002e0d
	v_mad_f32 v8, s11, s18, v8                                  ; d5410008 0420240b
	v_mac_f32_e32 v1, v13, v4                                   ; 3e02090d
	v_mul_f32_e64 v11, s14, s23                                 ; d508000b 00002e0e
	v_mul_f32_e64 v12, s15, s23                                 ; d508000c 00002e0f
	v_mac_f32_e32 v2, v14, v4                                   ; 3e04090e
	v_mac_f32_e32 v3, v15, v4                                   ; 3e06090f
	v_mad_f32 v6, s9, s18, v6                                   ; d5410006 04182409
	v_mad_f32 v5, s4, s17, v5                                   ; d5410005 04142204
	v_mad_f32 v7, s2, s16, v7                                   ; d5410007 041c2002
	v_mad_f32 v9, s8, s22, v9                                   ; d5410009 04242c08
	v_mad_f32 v10, s9, s22, v10                                 ; d541000a 04282c09
	v_mad_f32 v8, s7, s17, v8                                   ; d5410008 04202207
	v_mad_f32 v11, s10, s22, v11                                ; d541000b 042c2c0a
	v_mad_f32 v12, s11, s22, v12                                ; d541000c 04302c0b
	v_mul_f32_e64 v13, s12, s27                                 ; d508000d 0000360c
	v_mad_f32 v6, s5, s17, v6                                   ; d5410006 04182205
	v_mul_f32_e64 v14, s13, s27                                 ; d508000e 0000360d
	v_mad_f32 v5, s0, s16, v5                                   ; d5410005 04142000
	v_mul_f32_e64 v15, s14, s27                                 ; d508000f 0000360e
	v_mul_f32_e64 v16, s15, s27                                 ; d5080010 0000360f
	v_mad_f32 v9, s4, s21, v9                                   ; d5410009 04242a04
	v_mad_f32 v10, s5, s21, v10                                 ; d541000a 04282a05
	v_mad_f32 v8, s3, s16, v8                                   ; d5410008 04202003
	v_mad_f32 v11, s6, s21, v11                                 ; d541000b 042c2a06
	v_mad_f32 v12, s7, s21, v12                                 ; d541000c 04302a07
	v_mad_f32 v13, s8, s26, v13                                 ; d541000d 04343408
	v_mad_f32 v6, s1, s16, v6                                   ; d5410006 04182001
	v_mad_f32 v14, s9, s26, v14                                 ; d541000e 04383409
	v_mad_f32 v15, s10, s26, v15                                ; d541000f 043c340a
	v_mad_f32 v16, s11, s26, v16                                ; d5410010 0440340b
	v_mad_f32 v9, s0, s20, v9                                   ; d5410009 04242800
	v_mul_f32_e64 v17, s12, s31                                 ; d5080011 00003e0c
	v_mad_f32 v10, s1, s20, v10                                 ; d541000a 04282801
	v_mul_f32_e64 v18, s13, s31                                 ; d5080012 00003e0d
	v_mad_f32 v11, s2, s20, v11                                 ; d541000b 042c2802
	v_mul_f32_e64 v19, s14, s31                                 ; d5080013 00003e0e
	v_mad_f32 v12, s3, s20, v12                                 ; d541000c 04302803
	v_mul_f32_e64 v20, s15, s31                                 ; d5080014 00003e0f
	v_mad_f32 v13, s4, s25, v13                                 ; d541000d 04343204
	v_mad_f32 v14, s5, s25, v14                                 ; d541000e 04383205
	v_mad_f32 v15, s6, s25, v15                                 ; d541000f 043c3206
	v_mad_f32 v16, s7, s25, v16                                 ; d5410010 04403207
	v_mad_f32 v17, s8, s30, v17                                 ; d5410011 04443c08
	v_mad_f32 v18, s9, s30, v18                                 ; d5410012 04483c09
	v_mad_f32 v19, s10, s30, v19                                ; d5410013 044c3c0a
	v_mad_f32 v20, s11, s30, v20                                ; d5410014 04503c0b
	v_mad_f32 v13, s0, s24, v13                                 ; d541000d 04343000
	v_mad_f32 v14, s1, s24, v14                                 ; d541000e 04383001
	v_mad_f32 v15, s2, s24, v15                                 ; d541000f 043c3002
	v_mad_f32 v16, s3, s24, v16                                 ; d5410010 04403003
	v_mad_f32 v17, s4, s29, v17                                 ; d5410011 04443a04
	v_mad_f32 v18, s5, s29, v18                                 ; d5410012 04483a05
	v_mad_f32 v19, s6, s29, v19                                 ; d5410013 044c3a06
	v_mad_f32 v20, s7, s29, v20                                 ; d5410014 04503a07
	v_mad_f32 v17, s0, s28, v17                                 ; d5410011 04443800
	v_mad_f32 v18, s1, s28, v18                                 ; d5410012 04483801
	v_mad_f32 v19, s2, s28, v19                                 ; d5410013 044c3802
	v_mad_f32 v20, s3, s28, v20                                 ; d5410014 04503803
	v_mul_f32_e32 v17, v17, v3                                  ; 10220711
	v_mul_f32_e32 v18, v18, v3                                  ; 10240712
	v_mul_f32_e32 v19, v19, v3                                  ; 10260713
	v_mul_f32_e32 v20, v20, v3                                  ; 10280714
	v_mac_f32_e32 v17, v13, v2                                  ; 3e22050d
	v_mac_f32_e32 v18, v14, v2                                  ; 3e24050e
	v_mac_f32_e32 v19, v15, v2                                  ; 3e26050f
	v_mac_f32_e32 v20, v16, v2                                  ; 3e280510
	v_mac_f32_e32 v17, v9, v1                                   ; 3e220309
	v_mac_f32_e32 v18, v10, v1                                  ; 3e24030a
	v_mac_f32_e32 v19, v11, v1                                  ; 3e26030b
	v_mac_f32_e32 v20, v12, v1                                  ; 3e28030c
	v_mac_f32_e32 v17, v5, v0                                   ; 3e220105
	v_mac_f32_e32 v18, v6, v0                                   ; 3e240106
	v_mac_f32_e32 v19, v7, v0                                   ; 3e260107
	v_mac_f32_e32 v20, v8, v0                                   ; 3e280108
	exp pos0 v17, v18, v19, v20 done vm                         ; f80018cf 14131211
BB15:
	s_endpgm                                                    ; bf810000
