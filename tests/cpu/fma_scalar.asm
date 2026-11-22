; coverage: source cpu_aot_fma_scalar
; Source-owned differential fixture for all 24 scalar FMA3 instructions (ss/sd).
; Each export loads YMM0=[rcx], YMM1=[rdx], YMM2=[r8], runs the FMA, and stores YMM0 to [r9].
.code

vfmadd132ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmadd132ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmadd132ss_op ENDP

vfmadd132sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmadd132sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmadd132sd_op ENDP

vfmadd213ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmadd213ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmadd213ss_op ENDP

vfmadd213sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmadd213sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmadd213sd_op ENDP

vfmadd231ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmadd231ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmadd231ss_op ENDP

vfmadd231sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmadd231sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmadd231sd_op ENDP

vfmsub132ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmsub132ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmsub132ss_op ENDP

vfmsub132sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmsub132sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmsub132sd_op ENDP

vfmsub213ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmsub213ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmsub213ss_op ENDP

vfmsub213sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmsub213sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmsub213sd_op ENDP

vfmsub231ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmsub231ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmsub231ss_op ENDP

vfmsub231sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfmsub231sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfmsub231sd_op ENDP

vfnmadd132ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmadd132ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmadd132ss_op ENDP

vfnmadd132sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmadd132sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmadd132sd_op ENDP

vfnmadd213ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmadd213ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmadd213ss_op ENDP

vfnmadd213sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmadd213sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmadd213sd_op ENDP

vfnmadd231ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmadd231ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmadd231ss_op ENDP

vfnmadd231sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmadd231sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmadd231sd_op ENDP

vfnmsub132ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmsub132ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmsub132ss_op ENDP

vfnmsub132sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmsub132sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmsub132sd_op ENDP

vfnmsub213ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmsub213ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmsub213ss_op ENDP

vfnmsub213sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmsub213sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmsub213sd_op ENDP

vfnmsub231ss_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmsub231ss xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmsub231ss_op ENDP

vfnmsub231sd_op PROC FRAME
    .endprolog
    vmovups ymm0, ymmword ptr [rcx]
    vmovups ymm1, ymmword ptr [rdx]
    vmovups ymm2, ymmword ptr [r8]
    vfnmsub231sd xmm0, xmm1, xmm2
    vmovups ymmword ptr [r9], ymm0
    vzeroupper
    ret
vfnmsub231sd_op ENDP

END
