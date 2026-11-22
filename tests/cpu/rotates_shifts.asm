; Source-owned differential fixture for 32-bit and 64-bit ROL, ROR, SHLD, and SHRD
; with both immediate and CL counts, verifying values, 32-bit zero-extension, and ZF/CF.
.code

rol32_cl PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10d, 1        ; seed CF=1, ZF=0
    mov rax, rcx
    mov rcx, rdx
    rol eax, cl
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
rol32_cl ENDP

rol64_cl PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10d, 1
    mov rax, rcx
    mov rcx, rdx
    rol rax, cl
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
rol64_cl ENDP

ror32_cl PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10d, 1
    mov rax, rcx
    mov rcx, rdx
    ror eax, cl
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
ror32_cl ENDP

ror64_cl PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10d, 1
    mov rax, rcx
    mov rcx, rdx
    ror rax, cl
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
ror64_cl ENDP

rol32_imm PROC FRAME
    .endprolog
    mov rax, rcx
    rol eax, 7
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    mov qword ptr [rdx], r9
    ret
rol32_imm ENDP

ror64_imm PROC FRAME
    .endprolog
    mov rax, rcx
    ror rax, 19
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    mov qword ptr [rdx], r9
    ret
ror64_imm ENDP

; RCX = dst, RDX = src, R8 = count, R9 = flags_out
shld32_cl PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10d, 1
    mov rax, rcx
    mov rcx, r8
    shld eax, edx, cl
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
shld32_cl ENDP

shld64_cl PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10d, 1
    mov rax, rcx
    mov rcx, r8
    shld rax, rdx, cl
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
shld64_cl ENDP

shrd32_cl PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10d, 1
    mov rax, rcx
    mov rcx, r8
    shrd eax, edx, cl
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
shrd32_cl ENDP

shrd64_cl PROC FRAME
    .endprolog
    mov r10d, 0
    cmp r10d, 1
    mov rax, rcx
    mov rcx, r8
    shrd rax, rdx, cl
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
shrd64_cl ENDP

shld32_imm PROC FRAME
    .endprolog
    mov rax, rcx
    shld eax, edx, 13
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r8], r10
    ret
shld32_imm ENDP

shrd64_imm PROC FRAME
    .endprolog
    mov rax, rcx
    shrd rax, rdx, 21
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r8], r10
    ret
shrd64_imm ENDP

; Immediate count 32 masks to 0 for 32-bit SHLD: must preserve ZF=1, CF=0 and zero-extend RAX.
shld32_imm32 PROC FRAME
    .endprolog
    cmp r10d, r10d      ; seed ZF=1, CF=0
    mov rax, rcx
    shld eax, edx, 32
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r8], r10
    ret
shld32_imm32 ENDP

; Alternate flag seed (ZF=1, CF=0) for CL zero-count preservation checks.
rol32_cl_zf PROC FRAME
    .endprolog
    cmp r10d, r10d      ; seed ZF=1, CF=0
    mov rax, rcx
    mov rcx, rdx
    rol eax, cl
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
rol32_cl_zf ENDP

shld32_cl_zf PROC FRAME
    .endprolog
    cmp r10d, r10d      ; seed ZF=1, CF=0
    mov rax, rcx
    mov rcx, r8
    shld eax, edx, cl
    mov r10d, 0
    jae short @F
    mov r10d, 2
@@:
    jne short @F
    or r10d, 1
@@:
    mov qword ptr [r9], r10
    ret
shld32_cl_zf ENDP

END
