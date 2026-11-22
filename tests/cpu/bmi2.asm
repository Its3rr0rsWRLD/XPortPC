; Source-owned differential fixture for BMI2 instructions
; (BZHI, MULX, PDEP, PEXT, RORX, SARX, SHLX, SHRX) in 32-bit and 64-bit forms.
.code

bzhi32 PROC FRAME
    .endprolog
    mov rax, -1
    bzhi eax, ecx, edx
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
bzhi32 ENDP

bzhi64 PROC FRAME
    .endprolog
    bzhi rax, rcx, rdx
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
bzhi64 ENDP

rorx32 PROC FRAME
    .endprolog
    mov r9d, 0
    cmp r9d, 1
    mov rax, -1
    rorx eax, ecx, 13
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
rorx32 ENDP

rorx64 PROC FRAME
    .endprolog
    mov r9d, 0
    cmp r9d, 1
    rorx rax, rcx, 19
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
rorx64 ENDP

shlx32 PROC FRAME
    .endprolog
    mov r9d, 0
    cmp r9d, 1
    mov rax, -1
    shlx eax, ecx, edx
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
shlx32 ENDP

shlx64 PROC FRAME
    .endprolog
    mov r9d, 0
    cmp r9d, 1
    shlx rax, rcx, rdx
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
shlx64 ENDP

shrx32 PROC FRAME
    .endprolog
    mov rax, -1
    shrx eax, ecx, edx
    ret
shrx32 ENDP

shrx64 PROC FRAME
    .endprolog
    shrx rax, rcx, rdx
    ret
shrx64 ENDP

sarx32 PROC FRAME
    .endprolog
    mov rax, -1
    sarx eax, ecx, edx
    ret
sarx32 ENDP

sarx64 PROC FRAME
    .endprolog
    sarx rax, rcx, rdx
    ret
sarx64 ENDP

pdep32 PROC FRAME
    .endprolog
    mov rax, -1
    pdep eax, ecx, edx
    ret
pdep32 ENDP

pdep64 PROC FRAME
    .endprolog
    pdep rax, rcx, rdx
    ret
pdep64 ENDP

pext32 PROC FRAME
    .endprolog
    mov rax, -1
    pext eax, ecx, edx
    ret
pext32 ENDP

pext64 PROC FRAME
    .endprolog
    pext rax, rcx, rdx
    ret
pext64 ENDP

; RCX = multiplier, RDX = implicit multiplicand, R8 = low-half output pointer. Returns high half.
mulx32 PROC FRAME
    .endprolog
    mov rax, -1
    mov r9, -1
    mulx eax, r9d, ecx
    mov qword ptr [r8], r9
    ret
mulx32 ENDP

mulx64 PROC FRAME
    .endprolog
    mulx rax, r9, rcx
    mov qword ptr [r8], r9
    ret
mulx64 ENDP

; Same-destination control: high half must win over low half.
mulx64_same PROC FRAME
    .endprolog
    mulx rax, rax, rcx
    ret
mulx64_same ENDP

END
