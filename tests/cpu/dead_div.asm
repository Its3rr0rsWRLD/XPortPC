; Divides whose quotient and remainder are never used, for the jump-table translator. The processor
; raises a divide error when it reaches DIV or IDIV with a zero divisor or a quotient that does not
; fit, whether or not the results are read afterwards.
; Every export takes RCX = x, RDX = y and R8 = address of three writable QWORDs. Each stores 1 to
; [R8] before its divide and 2 to [R8+8] after it, overwrites RAX and RDX, and returns y + 1.
.code
; Unsigned divide of EDX:EAX = x by the low 32 bits of y.
div32_dead PROC FRAME
    .endprolog
    mov r9d, edx
    lea r10, [rdx+1]
    mov QWORD PTR [r8], 1
    mov rax, rcx
    shr rcx, 32
    mov edx, ecx
    div r9d
    mov QWORD PTR [r8+8], 2
    xor edx, edx
    mov rax, r10
    ret
div32_dead ENDP

; Signed divide of ECX by the low 32 bits of y after CDQ.
idiv32_dead PROC FRAME
    .endprolog
    mov r9d, edx
    lea r10, [rdx+1]
    mov QWORD PTR [r8], 1
    mov eax, ecx
    cdq
    idiv r9d
    mov QWORD PTR [r8+8], 2
    xor edx, edx
    mov rax, r10
    ret
idiv32_dead ENDP

; Unsigned divide of RDX:RAX = x:x by y: the quotient fits only when x < y.
udiv128_dead PROC FRAME
    .endprolog
    mov r9, rdx
    lea r10, [rdx+1]
    mov QWORD PTR [r8], 1
    mov rax, rcx
    mov rdx, rcx
    div r9
    mov QWORD PTR [r8+8], 2
    xor edx, edx
    mov rax, r10
    ret
udiv128_dead ENDP

; Signed divide of RCX by y after CQO.
idiv64_dead PROC FRAME
    .endprolog
    mov r9, rdx
    lea r10, [rdx+1]
    mov QWORD PTR [r8], 1
    mov rax, rcx
    cqo
    idiv r9
    mov QWORD PTR [r8+8], 2
    xor edx, edx
    mov rax, r10
    ret
idiv64_dead ENDP

; Unsigned divide of RCX by y, skipped when y is zero. Stores 3 to [R8+10h] on both paths.
div_skip PROC FRAME
    .endprolog
    mov r9, rdx
    lea r10, [rdx+1]
    mov QWORD PTR [r8], 1
    test r9, r9
    jz skipped
    mov rax, rcx
    xor edx, edx
    div r9
    mov QWORD PTR [r8+8], 2
skipped:
    mov QWORD PTR [r8+10h], 3
    xor edx, edx
    mov rax, r10
    ret
div_skip ENDP
END
