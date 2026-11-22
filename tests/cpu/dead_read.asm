; Source-owned control for memory reads whose value is never used. The processor performs
; each read, so an inaccessible operand faults whether or not the value matters afterwards.
.code
; Reads eight bytes at RCX, then overwrites the value. RAX = RDX.
read_dead PROC
    mov rax, [rcx]
    mov rax, rdx
    ret
read_dead ENDP

; Compares four bytes at RCX with zero; the flags are never read. RAX = RDX + 1.
cmp_dead PROC
    cmp dword ptr [rcx], 0
    lea rax, [rdx+1]
    ret
cmp_dead ENDP

; Reads one byte at RCX, then overwrites the value. RAX = RDX.
byte_dead PROC
    movzx eax, byte ptr [rcx]
    mov rax, rdx
    ret
byte_dead ENDP

; Reads eight bytes at RCX and eight at RCX + 8, then clears the sum. RAX = 0.
pair_dead PROC
    mov rax, [rcx]
    add rax, [rcx+8]
    xor eax, eax
    ret
pair_dead ENDP

; Control: the value read is returned, so no compiler can drop the read.
read_live PROC
    mov rax, [rcx]
    ret
read_live ENDP
END
