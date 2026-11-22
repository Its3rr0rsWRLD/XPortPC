; coverage: source cpu_aot_crypto_aes_pclmul
; Source-owned differential fixture for 14 legacy and 128-bit VEX AES-NI and PCLMULQDQ instructions.
.code

aesenc_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    aesenc xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
aesenc_op ENDP

aesenclast_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    aesenclast xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
aesenclast_op ENDP

aesdec_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    aesdec xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
aesdec_op ENDP

aesdeclast_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    aesdeclast xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
aesdeclast_op ENDP

aesimc_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    aesimc xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
aesimc_op ENDP

aeskeygenassist_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    aeskeygenassist xmm0, xmm1, 1Bh
    movdqu xmmword ptr [r8], xmm0
    ret
aeskeygenassist_op ENDP

pclmulqdq_00_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pclmulqdq xmm0, xmm1, 00h
    movdqu xmmword ptr [r8], xmm0
    ret
pclmulqdq_00_op ENDP

pclmulqdq_11_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pclmulqdq xmm0, xmm1, 11h
    movdqu xmmword ptr [r8], xmm0
    ret
pclmulqdq_11_op ENDP

vaesenc_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
    vaesenc xmm0, xmm1, xmm2
    movdqu xmmword ptr [r8], xmm0
    ret
vaesenc_op ENDP

vaesenclast_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
    vaesenclast xmm0, xmm1, xmm2
    movdqu xmmword ptr [r8], xmm0
    ret
vaesenclast_op ENDP

vaesdec_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
    vaesdec xmm0, xmm1, xmm2
    movdqu xmmword ptr [r8], xmm0
    ret
vaesdec_op ENDP

vaesdeclast_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
    vaesdeclast xmm0, xmm1, xmm2
    movdqu xmmword ptr [r8], xmm0
    ret
vaesdeclast_op ENDP

vaesimc_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    vaesimc xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
vaesimc_op ENDP

vaeskeygenassist_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    vaeskeygenassist xmm0, xmm1, 36h
    movdqu xmmword ptr [r8], xmm0
    ret
vaeskeygenassist_op ENDP

vpclmulqdq_01_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
    vpclmulqdq xmm0, xmm1, xmm2, 01h
    movdqu xmmword ptr [r8], xmm0
    ret
vpclmulqdq_01_op ENDP

END
