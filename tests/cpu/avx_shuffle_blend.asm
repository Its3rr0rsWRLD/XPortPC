; Source-owned differential fixture for 26 AVX broadcast, extract/insert, permute, shuffle, blend, dot, round, and zeroall instructions.
.code

vbroadcastss_op PROC FRAME
    .endprolog
    vbroadcastss ymm0, dword ptr [rcx]
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vbroadcastss_op ENDP

vbroadcastsd_op PROC FRAME
    .endprolog
    vbroadcastsd ymm0, qword ptr [rcx]
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vbroadcastsd_op ENDP

vbroadcastf128_op PROC FRAME
    .endprolog
    vbroadcastf128 ymm0, xmmword ptr [rcx]
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vbroadcastf128_op ENDP

vextractf128_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vextractf128 xmm0, ymm1, 1
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vextractf128_op ENDP

vinsertf128_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vinsertf128 ymm0, ymm1, xmmword ptr [rdx], 1
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vinsertf128_op ENDP

vperm2f128_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vperm2f128 ymm0, ymm1, ymm2, 31h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vperm2f128_op ENDP

vpermilps_imm_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vpermilps ymm0, ymm1, 0B1h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vpermilps_imm_op ENDP

vpermilpd_imm_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vpermilpd ymm0, ymm1, 09h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vpermilpd_imm_op ENDP

vshufps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vshufps ymm0, ymm1, ymm2, 0D2h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vshufps_op ENDP

vshufpd_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vshufpd ymm0, ymm1, ymm2, 05h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vshufpd_op ENDP

vunpcklps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vunpcklps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vunpcklps_op ENDP

vunpckhps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vunpckhps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vunpckhps_op ENDP

vunpcklpd_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vunpcklpd ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vunpcklpd_op ENDP

vunpckhpd_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vunpckhpd ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vunpckhpd_op ENDP

vmovddup_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovddup ymm0, ymm1
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vmovddup_op ENDP

vmovsldup_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovsldup ymm0, ymm1
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vmovsldup_op ENDP

vmovshdup_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovshdup ymm0, ymm1
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vmovshdup_op ENDP

vblendps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vblendps ymm0, ymm1, ymm2, 0A5h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vblendps_op ENDP

vblendpd_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vblendpd ymm0, ymm1, ymm2, 0Ah
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vblendpd_op ENDP

vblendvps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vmovups ymm3, ymmword ptr [r9]
    vblendvps ymm0, ymm1, ymm2, ymm3
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vblendvps_op ENDP

vblendvpd_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vmovups ymm3, ymmword ptr [r9]
    vblendvpd ymm0, ymm1, ymm2, ymm3
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vblendvpd_op ENDP

vdpps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vdpps ymm0, ymm1, ymm2, 0D5h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vdpps_op ENDP

vdppd_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vdppd xmm0, xmm1, xmm2, 031h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vdppd_op ENDP

vroundps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vroundps ymm0, ymm1, 08h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vroundps_op ENDP

vroundpd_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vroundpd ymm0, ymm1, 09h
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vroundpd_op ENDP

vzeroall_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vzeroall
    vmovups ymmword ptr [r8], ymm0
    ret
vzeroall_op ENDP

END
