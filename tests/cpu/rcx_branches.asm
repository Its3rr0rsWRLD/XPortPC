; Source-owned differential fixture for the RCX-counted branches LOOP, LOOPE, LOOPNE and JRCXZ, and their
; 67h (ECX) forms loopd, looped, loopned and jecxz. Each export takes (count, pointer, value or preset,
; state) in RCX, RDX, R8 and R9, returns RAX and writes (CF << 1) | ZF, RCX and the final pointer offset
; to state[0..2]. The 67h prefix of the ECX LOOP forms is emitted with db; jecxz has its own spelling.
.code

BRANCH_LEAVE MACRO
    LOCAL no_carry, no_zero
    mov r11d, 0
    jae short no_carry
    mov r11d, 2
no_carry:
    jne short no_zero
    or r11d, 1
no_zero:
    mov qword ptr [r9], r11
    mov qword ptr [r9+8], rcx
    sub r10, rdx
    mov qword ptr [r9+16], r10
    ret
ENDM

; RAX counts the iterations. LEA leaves the flags from add r8, r8 untouched, so they must survive LOOP.
loop_count PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 0
    add r8, r8
again:
    lea rax, [rax+1]
    loop again
    BRANCH_LEAVE
loop_count ENDP

loopd_count PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 0
    add r8, r8
again:
    lea rax, [rax+1]
    db 67h
    loop again
    BRANCH_LEAVE
loopd_count ENDP

; Scan bytes from RDX while they equal (LOOPE) or differ from (LOOPNE) the low byte of R8. JRCXZ skips
; the scan for a zero count, and the flags then come from add r8, 0.
loope_scan PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 0
    add r8, 0
    jrcxz done
again:
    cmp byte ptr [r10], r8b
    lea r10, [r10+1]
    loope again
done:
    BRANCH_LEAVE
loope_scan ENDP

loopne_scan PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 0
    add r8, 0
    jrcxz done
again:
    cmp byte ptr [r10], r8b
    lea r10, [r10+1]
    loopne again
done:
    BRANCH_LEAVE
loopne_scan ENDP

looped_scan PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 0
    add r8, 0
    jecxz done
again:
    cmp byte ptr [r10], r8b
    lea r10, [r10+1]
    db 67h
    loope again
done:
    BRANCH_LEAVE
looped_scan ENDP

loopned_scan PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 0
    add r8, 0
    jecxz done
again:
    cmp byte ptr [r10], r8b
    lea r10, [r10+1]
    db 67h
    loopne again
done:
    BRANCH_LEAVE
loopned_scan ENDP

; RAX = 1 when the branch is taken, 2 otherwise; the flags from add r8, r8 must survive.
jrcxz_probe PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 1
    add r8, r8
    jrcxz taken
    mov eax, 2
taken:
    BRANCH_LEAVE
jrcxz_probe ENDP

jecxz_probe PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 1
    add r8, r8
    jecxz taken
    mov eax, 2
taken:
    BRANCH_LEAVE
jecxz_probe ENDP

END
