; Source-owned control for memory reads in the jump-table translator. The processor performs each
; read of an instruction once, so an inaccessible operand faults whether or not the value is used.
; Every export takes RCX = address read, RDX = y and R8 = address of three writable QWORDs. Each
; stores 1 to [R8] before its read and 2 to [R8+8] after it.
.code
; Reads eight bytes at RCX, then overwrites the value. RAX = y.
read_dead PROC
    mov QWORD PTR [r8], 1
    mov rax, [rcx]
    mov QWORD PTR [r8+8], 2
    mov rax, rdx
    ret
read_dead ENDP

; Compares four bytes at RCX with zero; the flags are never read. RAX = y + 1.
cmp_dead PROC
    mov QWORD PTR [r8], 1
    cmp DWORD PTR [rcx], 0
    mov QWORD PTR [r8+8], 2
    lea rax, [rdx+1]
    ret
cmp_dead ENDP

; Reads one byte at RCX, then overwrites the value. RAX = y.
byte_dead PROC
    mov QWORD PTR [r8], 1
    movzx eax, BYTE PTR [rcx]
    mov QWORD PTR [r8+8], 2
    mov rax, rdx
    ret
byte_dead ENDP

; Reads eight bytes at RCX and eight at RCX + 8, then clears the sum. RAX = 0.
pair_dead PROC
    mov QWORD PTR [r8], 1
    mov rax, [rcx]
    add rax, [rcx+8]
    mov QWORD PTR [r8+8], 2
    xor eax, eax
    ret
pair_dead ENDP

; Control: the value read is returned, so no compiler can drop the read.
read_live PROC
    mov QWORD PTR [r8], 1
    mov rax, [rcx]
    mov QWORD PTR [r8+8], 2
    ret
read_live ENDP

; Skips its read when y is zero, and stores 3 to [R8+10h] on both paths. RAX = y.
read_skip PROC
    mov QWORD PTR [r8], 1
    test rdx, rdx
    jz skipped
    mov rax, [rcx]
    mov QWORD PTR [r8+8], 2
skipped:
    mov QWORD PTR [r8+10h], 3
    mov rax, rdx
    ret
read_skip ENDP

; One read of [RCX] gives both the sum and its zero flag: RAX = y + [RCX], and [R8+10h] = 1 when
; the sum is zero.
sum_zero PROC
    mov QWORD PTR [r8], 1
    mov rax, rdx
    add rax, [rcx]
    sete r9b
    movzx r9d, r9b
    mov QWORD PTR [r8+10h], r9
    mov QWORD PTR [r8+8], 2
    ret
sum_zero ENDP

; Adds y to the eight bytes at RCX in place: one read, one write. RAX = 1 when the sum is zero.
add_in_place PROC
    mov QWORD PTR [r8], 1
    add [rcx], rdx
    sete al
    movzx eax, al
    mov QWORD PTR [r8+8], 2
    ret
add_in_place ENDP
END
