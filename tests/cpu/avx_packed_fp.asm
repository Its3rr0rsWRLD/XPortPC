; Source-owned differential fixture for 31 AVX 256-bit packed floating-point instructions.
.code

vaddps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vaddps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vaddps_op ENDP

vsubps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vsubps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vsubps_op ENDP

vmulps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vmulps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vmulps_op ENDP

vdivps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vdivps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vdivps_op ENDP

vsqrtps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vsqrtps ymm0, ymm1
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vsqrtps_op ENDP

vminps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vminps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vminps_op ENDP

vmaxps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vmaxps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vmaxps_op ENDP

vandps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vandps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vandps_op ENDP

vandnps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vandnps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vandnps_op ENDP

vorps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vorps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vorps_op ENDP

vxorps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vxorps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vxorps_op ENDP

vaddsubps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vaddsubps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vaddsubps_op ENDP

vhaddps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vhaddps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vhaddps_op ENDP

vhsubps_op PROC FRAME
    .endprolog
    vmovups ymm1, ymmword ptr [rcx]
    vmovups ymm2, ymmword ptr [rdx]
    vhsubps ymm0, ymm1, ymm2
    vmovups ymmword ptr [r8], ymm0
    vzeroupper
    ret
vhsubps_op ENDP

vmovmskps_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovmskps eax, ymm0
    vzeroupper
    ret
vmovmskps_op ENDP

vaddpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vaddpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vaddpd_op ENDP

vsubpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vsubpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vsubpd_op ENDP

vmulpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vmulpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vmulpd_op ENDP

vdivpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vdivpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vdivpd_op ENDP

vsqrtpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vsqrtpd ymm0, ymm1
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vsqrtpd_op ENDP

vminpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vminpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vminpd_op ENDP

vmaxpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vmaxpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vmaxpd_op ENDP

vandpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vandpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vandpd_op ENDP

vandnpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vandnpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vandnpd_op ENDP

vorpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vorpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vorpd_op ENDP

vxorpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vxorpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vxorpd_op ENDP

vaddsubpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vaddsubpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vaddsubpd_op ENDP

vhaddpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vhaddpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vhaddpd_op ENDP

vhsubpd_op PROC FRAME
    .endprolog
    vmovupd ymm1, ymmword ptr [rcx]
    vmovupd ymm2, ymmword ptr [rdx]
    vhsubpd ymm0, ymm1, ymm2
    vmovupd ymmword ptr [r8], ymm0
    vzeroupper
    ret
vhsubpd_op ENDP

vmovmskpd_op PROC FRAME
    .endprolog
    vmovupd ymm0, ymmword ptr [rcx]
    vmovmskpd eax, ymm0
    vzeroupper
    ret
vmovmskpd_op ENDP

END
