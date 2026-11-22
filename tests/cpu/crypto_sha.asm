; Source-owned differential fixture for all 7 SHA-NI instructions.
.code

sha1msg1_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha1msg1 xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
sha1msg1_op ENDP

sha1msg2_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha1msg2 xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
sha1msg2_op ENDP

sha1nexte_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha1nexte xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
sha1nexte_op ENDP

sha1rnds4_0_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha1rnds4 xmm0, xmm1, 0
    movdqu xmmword ptr [r8], xmm0
    ret
sha1rnds4_0_op ENDP

sha1rnds4_1_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha1rnds4 xmm0, xmm1, 1
    movdqu xmmword ptr [r8], xmm0
    ret
sha1rnds4_1_op ENDP

sha1rnds4_2_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha1rnds4 xmm0, xmm1, 2
    movdqu xmmword ptr [r8], xmm0
    ret
sha1rnds4_2_op ENDP

sha1rnds4_3_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha1rnds4 xmm0, xmm1, 3
    movdqu xmmword ptr [r8], xmm0
    ret
sha1rnds4_3_op ENDP

sha256msg1_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha256msg1 xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
sha256msg1_op ENDP

sha256msg2_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    sha256msg2 xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
sha256msg2_op ENDP

sha256rnds2_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
    movdqu xmm0, xmmword ptr [r9]
    sha256rnds2 xmm1, xmm2, xmm0
    movdqu xmmword ptr [r8], xmm1
    ret
sha256rnds2_op ENDP

END
