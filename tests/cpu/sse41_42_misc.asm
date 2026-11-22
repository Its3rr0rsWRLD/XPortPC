; Source-owned differential fixture for 16 SSSE3/SSE4.1/SSE4.2 integer, insert/extract, ptest, and crc32 instructions.
.code

pextrb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    pextrb eax, xmm0, 11
    ret
pextrb_op ENDP

pextrw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    pextrw eax, xmm0, 5
    ret
pextrw_op ENDP

pextrd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    pextrd eax, xmm0, 2
    ret
pextrd_op ENDP

pextrq_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    pextrq rax, xmm0, 1
    ret
pextrq_op ENDP

pinsrb_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    mov eax, dword ptr [rdx]
    pinsrb xmm0, eax, 9
    movdqu xmmword ptr [r8], xmm0
    ret
pinsrb_op ENDP

pinsrw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    mov eax, dword ptr [rdx]
    pinsrw xmm0, eax, 6
    movdqu xmmword ptr [r8], xmm0
    ret
pinsrw_op ENDP

pinsrd_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    mov eax, dword ptr [rdx]
    pinsrd xmm0, eax, 3
    movdqu xmmword ptr [r8], xmm0
    ret
pinsrd_op ENDP

pinsrq_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    mov rax, qword ptr [rdx]
    pinsrq xmm0, rax, 1
    movdqu xmmword ptr [r8], xmm0
    ret
pinsrq_op ENDP

pmaddubsw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmaddubsw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmaddubsw_op ENDP

pmulhrsw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pmulhrsw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pmulhrsw_op ENDP

phminposuw_op PROC FRAME
    .endprolog
    movdqu xmm1, xmmword ptr [rcx]
    phminposuw xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
phminposuw_op ENDP

ptest_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    xor eax, eax
    xor r9d, r9d
    ptest xmm0, xmm1
    sete al
    jb ptest_cf
    ret
ptest_cf:
    or eax, 2
    ret
ptest_op ENDP

mpsadbw_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    mpsadbw xmm0, xmm1, 05h
    movdqu xmmword ptr [r8], xmm0
    ret
mpsadbw_op ENDP

movntdqa_op PROC FRAME
    .endprolog
    movntdqa xmm0, xmmword ptr [rcx]
    movdqu xmmword ptr [r8], xmm0
    ret
movntdqa_op ENDP

pcmpgtq_op PROC FRAME
    .endprolog
    movdqu xmm0, xmmword ptr [rcx]
    movdqu xmm1, xmmword ptr [rdx]
    pcmpgtq xmm0, xmm1
    movdqu xmmword ptr [r8], xmm0
    ret
pcmpgtq_op ENDP

crc32_8_op PROC FRAME
    .endprolog
    mov eax, ecx
    crc32 eax, dl
    ret
crc32_8_op ENDP

crc32_32_op PROC FRAME
    .endprolog
    mov eax, ecx
    crc32 eax, edx
    ret
crc32_32_op ENDP

crc32_64_op PROC FRAME
    .endprolog
    mov rax, rcx
    crc32 rax, rdx
    ret
crc32_64_op ENDP

END
