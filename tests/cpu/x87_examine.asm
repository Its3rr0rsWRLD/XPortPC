; coverage: source cpu_aot_x87_examine
; Source-owned differential fixture for FTST, FXAM, FICOM, FICOMP, FNOP, FNCLEX and FCLEX in the x87
; leaf-function profile. Each export reads an input block at RCX (an m80 value at +0, an m16 integer at
; +16 and an m32 integer at +24), records C0, C2 and C3 after each status-word writer as bytes of the
; output block at RDX, and returns with the x87 stack empty.
.code

ftst_fxam PROC FRAME
    .endprolog
    fld tbyte ptr [rcx]
    ftst
    fnstsw ax
    test ah, 001h
    mov byte ptr [rdx+0], 1
    jne tst_c0
    mov byte ptr [rdx+0], 0
tst_c0:
    test ah, 004h
    mov byte ptr [rdx+1], 1
    jne tst_c2
    mov byte ptr [rdx+1], 0
tst_c2:
    test ah, 040h
    mov byte ptr [rdx+2], 1
    jne tst_c3
    mov byte ptr [rdx+2], 0
tst_c3:
    fxam
    fnstsw ax
    test ah, 001h
    mov byte ptr [rdx+3], 1
    jne xam_c0
    mov byte ptr [rdx+3], 0
xam_c0:
    test ah, 004h
    mov byte ptr [rdx+4], 1
    jne xam_c2
    mov byte ptr [rdx+4], 0
xam_c2:
    test ah, 040h
    mov byte ptr [rdx+5], 1
    jne xam_c3
    mov byte ptr [rdx+5], 0
xam_c3:
    fstp tbyte ptr [rdx+16]
    fxam
    fnstsw ax
    test ah, 001h
    mov byte ptr [rdx+6], 1
    jne empty_c0
    mov byte ptr [rdx+6], 0
empty_c0:
    test ah, 004h
    mov byte ptr [rdx+7], 1
    jne empty_c2
    mov byte ptr [rdx+7], 0
empty_c2:
    test ah, 040h
    mov byte ptr [rdx+8], 1
    jne empty_c3
    mov byte ptr [rdx+8], 0
empty_c3:
    mov eax, 0
    ret
ftst_fxam ENDP

ficom_m16 PROC FRAME
    .endprolog
    fld tbyte ptr [rcx]
    ficom word ptr [rcx+16]
    fnstsw ax
    test ah, 001h
    mov byte ptr [rdx+0], 1
    jne icom16_c0
    mov byte ptr [rdx+0], 0
icom16_c0:
    test ah, 004h
    mov byte ptr [rdx+1], 1
    jne icom16_c2
    mov byte ptr [rdx+1], 0
icom16_c2:
    test ah, 040h
    mov byte ptr [rdx+2], 1
    jne icom16_c3
    mov byte ptr [rdx+2], 0
icom16_c3:
    ficomp word ptr [rcx+16]
    fnstsw ax
    test ah, 001h
    mov byte ptr [rdx+3], 1
    jne icomp16_c0
    mov byte ptr [rdx+3], 0
icomp16_c0:
    test ah, 004h
    mov byte ptr [rdx+4], 1
    jne icomp16_c2
    mov byte ptr [rdx+4], 0
icomp16_c2:
    test ah, 040h
    mov byte ptr [rdx+5], 1
    jne icomp16_c3
    mov byte ptr [rdx+5], 0
icomp16_c3:
    mov eax, 0
    ret
ficom_m16 ENDP

ficom_m32 PROC FRAME
    .endprolog
    fld tbyte ptr [rcx]
    ficom dword ptr [rcx+24]
    fnstsw ax
    test ah, 001h
    mov byte ptr [rdx+0], 1
    jne icom32_c0
    mov byte ptr [rdx+0], 0
icom32_c0:
    test ah, 004h
    mov byte ptr [rdx+1], 1
    jne icom32_c2
    mov byte ptr [rdx+1], 0
icom32_c2:
    test ah, 040h
    mov byte ptr [rdx+2], 1
    jne icom32_c3
    mov byte ptr [rdx+2], 0
icom32_c3:
    ficomp dword ptr [rcx+24]
    fnstsw ax
    test ah, 001h
    mov byte ptr [rdx+3], 1
    jne icomp32_c0
    mov byte ptr [rdx+3], 0
icomp32_c0:
    test ah, 004h
    mov byte ptr [rdx+4], 1
    jne icomp32_c2
    mov byte ptr [rdx+4], 0
icomp32_c2:
    test ah, 040h
    mov byte ptr [rdx+5], 1
    jne icomp32_c3
    mov byte ptr [rdx+5], 0
icomp32_c3:
    mov eax, 0
    ret
ficom_m32 ENDP

fnop_fclex PROC FRAME
    .endprolog
    fld tbyte ptr [rcx]
    fnop
    fnclex
    fclex
    fstp tbyte ptr [rdx+16]
    mov eax, 0
    ret
fnop_fclex ENDP

END
