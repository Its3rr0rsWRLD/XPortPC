; coverage: source cpu_aot_bit_ops
; Source-owned differential fixture for x64 integer bit-scan, bit-count,
; byte-swap, and register bit-test instructions in 32-bit and 64-bit forms:
; BSF, BSR, BSWAP, POPCNT, LZCNT, BT, BTS, BTR, BTC.
.code

bsf32 PROC FRAME
    .endprolog
    mov rax, 01234567800000077h
    bsf eax, ecx
    mov r9d, 0
    jne short @F
    mov r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
bsf32 ENDP

bsf64 PROC FRAME
    .endprolog
    mov rax, 01234567800000077h
    bsf rax, rcx
    mov r9d, 0
    jne short @F
    mov r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
bsf64 ENDP

bsr32 PROC FRAME
    .endprolog
    mov rax, 01234567800000077h
    bsr eax, ecx
    mov r9d, 0
    jne short @F
    mov r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
bsr32 ENDP

bsr64 PROC FRAME
    .endprolog
    mov rax, 01234567800000077h
    bsr rax, rcx
    mov r9d, 0
    jne short @F
    mov r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
bsr64 ENDP

bswap32 PROC FRAME
    .endprolog
    mov rax, rcx
    bswap eax
    ret
bswap32 ENDP

bswap64 PROC FRAME
    .endprolog
    mov rax, rcx
    bswap rax
    ret
bswap64 ENDP

popcnt32 PROC FRAME
    .endprolog
    mov rax, -1
    popcnt eax, ecx
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
popcnt32 ENDP

popcnt64 PROC FRAME
    .endprolog
    popcnt rax, rcx
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
popcnt64 ENDP

lzcnt32 PROC FRAME
    .endprolog
    mov rax, -1
    lzcnt eax, ecx
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
lzcnt32 ENDP

lzcnt64 PROC FRAME
    .endprolog
    lzcnt rax, rcx
    mov r9d, 0
    jae short @F
    mov r9d, 2
@@:
    jne short @F
    or r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
lzcnt64 ENDP

bt32 PROC FRAME
    .endprolog
    mov rax, rcx
    bt eax, edx
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
bt32 ENDP

bt64 PROC FRAME
    .endprolog
    mov rax, rcx
    bt rax, rdx
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
bt64 ENDP

bts32 PROC FRAME
    .endprolog
    mov rax, rcx
    bts eax, edx
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
bts32 ENDP

bts64 PROC FRAME
    .endprolog
    mov rax, rcx
    bts rax, rdx
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
bts64 ENDP

btr32 PROC FRAME
    .endprolog
    mov rax, rcx
    btr eax, edx
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
btr32 ENDP

btr64 PROC FRAME
    .endprolog
    mov rax, rcx
    btr rax, rdx
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
btr64 ENDP

btc32 PROC FRAME
    .endprolog
    mov rax, rcx
    btc eax, edx
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
btc32 ENDP

btc64 PROC FRAME
    .endprolog
    mov rax, rcx
    btc rax, rdx
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [r8], r9
    ret
btc64 ENDP

btc64_imm PROC FRAME
    .endprolog
    mov rax, rcx
    btc rax, 47
    mov r9d, 0
    jae short @F
    mov r9d, 1
@@:
    mov qword ptr [rdx], r9
    ret
btc64_imm ENDP

END
