; coverage: source cpu_aot_chained_dead_reads
; Source-owned control for memory reads in the chained-range translator. The processor performs each
; read of an instruction once, so an inaccessible operand faults whether or not the value is used.
; Every export takes RCX = address read and RDX = y.
.code
; Reads eight bytes at RCX, then overwrites the value. RAX = y.
read_dead PROC FRAME
.endprolog
    mov rax, [rcx]
    mov rax, rdx
    ret
read_dead ENDP

; Reads eight bytes at RCX + 8 into a register that is never read. RAX = y.
disp_dead PROC FRAME
.endprolog
    mov r8, [rcx + 8]
    mov rax, rdx
    ret
disp_dead ENDP

; Reads eight bytes at RCX and eight at RCX + 8; neither value is used. RAX = y.
pair_dead PROC FRAME
.endprolog
    mov r8, [rcx]
    mov r9, [rcx + 8]
    mov rax, rdx
    ret
pair_dead ENDP

; Skips its read when y is zero; the value is never used on either path. RAX = y.
read_skip PROC FRAME
.endprolog
    test rdx, rdx
    jz skipped
    mov r8, [rcx]
skipped:
    mov rax, rdx
    ret
read_skip ENDP

; Control: the value read is returned, so no compiler can drop the read.
read_live PROC FRAME
.endprolog
    mov rax, [rcx]
    ret
read_live ENDP
END
