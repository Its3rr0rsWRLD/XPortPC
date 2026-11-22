; Source-owned differential fixture for 32 baseline 128-bit SSE/SSE2 packed floating-point instructions.
.code

addps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    addps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
addps_op ENDP

subps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    subps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
subps_op ENDP

mulps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    mulps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
mulps_op ENDP

divps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    divps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
divps_op ENDP

sqrtps_op PROC FRAME
    .endprolog
    movups xmm1, xmmword ptr [rcx]
    sqrtps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
sqrtps_op ENDP

minps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    minps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
minps_op ENDP

maxps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    maxps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
maxps_op ENDP

andps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    andps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
andps_op ENDP

andnps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    andnps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
andnps_op ENDP

orps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    orps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
orps_op ENDP

xorps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    xorps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
xorps_op ENDP

shufps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    shufps xmm0, xmm1, 0D2h
    movups xmmword ptr [r8], xmm0
    ret
shufps_op ENDP

unpcklps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    unpcklps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
unpcklps_op ENDP

unpckhps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movups xmm1, xmmword ptr [rdx]
    unpckhps xmm0, xmm1
    movups xmmword ptr [r8], xmm0
    ret
unpckhps_op ENDP

movmskps_op PROC FRAME
    .endprolog
    movups xmm0, xmmword ptr [rcx]
    movmskps eax, xmm0
    ret
movmskps_op ENDP

addpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    addpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
addpd_op ENDP

subpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    subpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
subpd_op ENDP

mulpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    mulpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
mulpd_op ENDP

divpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    divpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
divpd_op ENDP

sqrtpd_op PROC FRAME
    .endprolog
    movupd xmm1, xmmword ptr [rcx]
    sqrtpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
sqrtpd_op ENDP

minpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    minpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
minpd_op ENDP

maxpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    maxpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
maxpd_op ENDP

andpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    andpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
andpd_op ENDP

andnpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    andnpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
andnpd_op ENDP

orpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    orpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
orpd_op ENDP

xorpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    xorpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
xorpd_op ENDP

shufpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    shufpd xmm0, xmm1, 01h
    movupd xmmword ptr [r8], xmm0
    ret
shufpd_op ENDP

unpcklpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    unpcklpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
unpcklpd_op ENDP

unpckhpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movupd xmm1, xmmword ptr [rdx]
    unpckhpd xmm0, xmm1
    movupd xmmword ptr [r8], xmm0
    ret
unpckhpd_op ENDP

movmskpd_op PROC FRAME
    .endprolog
    movupd xmm0, xmmword ptr [rcx]
    movmskpd eax, xmm0
    ret
movmskpd_op ENDP

END
