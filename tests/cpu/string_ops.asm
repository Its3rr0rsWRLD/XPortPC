; Source-owned differential fixture for the x64 string instructions MOVS, STOS, LODS, SCAS and CMPS
; in byte, word, dword and qword widths, with REP, REPE and REPNE and with DF set by STD.
; Each export takes (destination, source, count, state). It enters with RDI, RSI and RCX set from the
; first three arguments, RAX from state[1] and the flags from comparing state[0] with 1 (0: CF, 1: ZF,
; 2: neither). It writes (CF << 1) | ZF, RAX, RSI, RDI and RCX to state[0..4]. RSI and RDI are
; callee-saved and kept in R10 and R11.
.code

STRING_ENTER MACRO
    mov r10, rsi
    mov r11, rdi
    mov rdi, rcx
    mov rsi, rdx
    mov rcx, r8
    mov rax, qword ptr [r9+8]
    cmp qword ptr [r9], 1
ENDM

STRING_LEAVE MACRO
    LOCAL no_carry, no_zero
    mov edx, 0
    jae short no_carry
    mov edx, 2
no_carry:
    jne short no_zero
    or edx, 1
no_zero:
    mov qword ptr [r9], rdx
    mov qword ptr [r9+8], rax
    mov qword ptr [r9+16], rsi
    mov qword ptr [r9+24], rdi
    mov qword ptr [r9+32], rcx
    mov rsi, r10
    mov rdi, r11
    ret
ENDM

once_movsb PROC FRAME
    .endprolog
    STRING_ENTER
    movsb
    STRING_LEAVE
once_movsb ENDP

once_movsw PROC FRAME
    .endprolog
    STRING_ENTER
    movsw
    STRING_LEAVE
once_movsw ENDP

once_movsd PROC FRAME
    .endprolog
    STRING_ENTER
    movsd
    STRING_LEAVE
once_movsd ENDP

once_movsq PROC FRAME
    .endprolog
    STRING_ENTER
    movsq
    STRING_LEAVE
once_movsq ENDP

once_stosb PROC FRAME
    .endprolog
    STRING_ENTER
    stosb
    STRING_LEAVE
once_stosb ENDP

once_stosw PROC FRAME
    .endprolog
    STRING_ENTER
    stosw
    STRING_LEAVE
once_stosw ENDP

once_stosd PROC FRAME
    .endprolog
    STRING_ENTER
    stosd
    STRING_LEAVE
once_stosd ENDP

once_stosq PROC FRAME
    .endprolog
    STRING_ENTER
    stosq
    STRING_LEAVE
once_stosq ENDP

once_lodsb PROC FRAME
    .endprolog
    STRING_ENTER
    lodsb
    STRING_LEAVE
once_lodsb ENDP

once_lodsw PROC FRAME
    .endprolog
    STRING_ENTER
    lodsw
    STRING_LEAVE
once_lodsw ENDP

once_lodsd PROC FRAME
    .endprolog
    STRING_ENTER
    lodsd
    STRING_LEAVE
once_lodsd ENDP

once_lodsq PROC FRAME
    .endprolog
    STRING_ENTER
    lodsq
    STRING_LEAVE
once_lodsq ENDP

once_scasb PROC FRAME
    .endprolog
    STRING_ENTER
    scasb
    STRING_LEAVE
once_scasb ENDP

once_scasw PROC FRAME
    .endprolog
    STRING_ENTER
    scasw
    STRING_LEAVE
once_scasw ENDP

once_scasd PROC FRAME
    .endprolog
    STRING_ENTER
    scasd
    STRING_LEAVE
once_scasd ENDP

once_scasq PROC FRAME
    .endprolog
    STRING_ENTER
    scasq
    STRING_LEAVE
once_scasq ENDP

once_cmpsb PROC FRAME
    .endprolog
    STRING_ENTER
    cmpsb
    STRING_LEAVE
once_cmpsb ENDP

once_cmpsw PROC FRAME
    .endprolog
    STRING_ENTER
    cmpsw
    STRING_LEAVE
once_cmpsw ENDP

once_cmpsd PROC FRAME
    .endprolog
    STRING_ENTER
    cmpsd
    STRING_LEAVE
once_cmpsd ENDP

once_cmpsq PROC FRAME
    .endprolog
    STRING_ENTER
    cmpsq
    STRING_LEAVE
once_cmpsq ENDP

rep_movsb PROC FRAME
    .endprolog
    STRING_ENTER
    rep movsb
    STRING_LEAVE
rep_movsb ENDP

rep_movsw PROC FRAME
    .endprolog
    STRING_ENTER
    rep movsw
    STRING_LEAVE
rep_movsw ENDP

rep_movsd PROC FRAME
    .endprolog
    STRING_ENTER
    rep movsd
    STRING_LEAVE
rep_movsd ENDP

rep_movsq PROC FRAME
    .endprolog
    STRING_ENTER
    rep movsq
    STRING_LEAVE
rep_movsq ENDP

rep_stosb PROC FRAME
    .endprolog
    STRING_ENTER
    rep stosb
    STRING_LEAVE
rep_stosb ENDP

rep_stosw PROC FRAME
    .endprolog
    STRING_ENTER
    rep stosw
    STRING_LEAVE
rep_stosw ENDP

rep_stosd PROC FRAME
    .endprolog
    STRING_ENTER
    rep stosd
    STRING_LEAVE
rep_stosd ENDP

rep_stosq PROC FRAME
    .endprolog
    STRING_ENTER
    rep stosq
    STRING_LEAVE
rep_stosq ENDP

rep_lodsb PROC FRAME
    .endprolog
    STRING_ENTER
    rep lodsb
    STRING_LEAVE
rep_lodsb ENDP

rep_lodsw PROC FRAME
    .endprolog
    STRING_ENTER
    rep lodsw
    STRING_LEAVE
rep_lodsw ENDP

rep_lodsd PROC FRAME
    .endprolog
    STRING_ENTER
    rep lodsd
    STRING_LEAVE
rep_lodsd ENDP

rep_lodsq PROC FRAME
    .endprolog
    STRING_ENTER
    rep lodsq
    STRING_LEAVE
rep_lodsq ENDP

repe_scasb PROC FRAME
    .endprolog
    STRING_ENTER
    repe scasb
    STRING_LEAVE
repe_scasb ENDP

repe_scasw PROC FRAME
    .endprolog
    STRING_ENTER
    repe scasw
    STRING_LEAVE
repe_scasw ENDP

repe_scasd PROC FRAME
    .endprolog
    STRING_ENTER
    repe scasd
    STRING_LEAVE
repe_scasd ENDP

repe_scasq PROC FRAME
    .endprolog
    STRING_ENTER
    repe scasq
    STRING_LEAVE
repe_scasq ENDP

repne_scasb PROC FRAME
    .endprolog
    STRING_ENTER
    repne scasb
    STRING_LEAVE
repne_scasb ENDP

repne_scasw PROC FRAME
    .endprolog
    STRING_ENTER
    repne scasw
    STRING_LEAVE
repne_scasw ENDP

repne_scasd PROC FRAME
    .endprolog
    STRING_ENTER
    repne scasd
    STRING_LEAVE
repne_scasd ENDP

repne_scasq PROC FRAME
    .endprolog
    STRING_ENTER
    repne scasq
    STRING_LEAVE
repne_scasq ENDP

repe_cmpsb PROC FRAME
    .endprolog
    STRING_ENTER
    repe cmpsb
    STRING_LEAVE
repe_cmpsb ENDP

repe_cmpsw PROC FRAME
    .endprolog
    STRING_ENTER
    repe cmpsw
    STRING_LEAVE
repe_cmpsw ENDP

repe_cmpsd PROC FRAME
    .endprolog
    STRING_ENTER
    repe cmpsd
    STRING_LEAVE
repe_cmpsd ENDP

repe_cmpsq PROC FRAME
    .endprolog
    STRING_ENTER
    repe cmpsq
    STRING_LEAVE
repe_cmpsq ENDP

repne_cmpsb PROC FRAME
    .endprolog
    STRING_ENTER
    repne cmpsb
    STRING_LEAVE
repne_cmpsb ENDP

repne_cmpsw PROC FRAME
    .endprolog
    STRING_ENTER
    repne cmpsw
    STRING_LEAVE
repne_cmpsw ENDP

repne_cmpsd PROC FRAME
    .endprolog
    STRING_ENTER
    repne cmpsd
    STRING_LEAVE
repne_cmpsd ENDP

repne_cmpsq PROC FRAME
    .endprolog
    STRING_ENTER
    repne cmpsq
    STRING_LEAVE
repne_cmpsq ENDP

std_movsw PROC FRAME
    .endprolog
    STRING_ENTER
    std
    movsw
    cld
    STRING_LEAVE
std_movsw ENDP

std_rep_movsb PROC FRAME
    .endprolog
    STRING_ENTER
    std
    rep movsb
    cld
    STRING_LEAVE
std_rep_movsb ENDP

std_rep_movsq PROC FRAME
    .endprolog
    STRING_ENTER
    std
    rep movsq
    cld
    STRING_LEAVE
std_rep_movsq ENDP

std_stosb PROC FRAME
    .endprolog
    STRING_ENTER
    std
    stosb
    cld
    STRING_LEAVE
std_stosb ENDP

std_rep_stosw PROC FRAME
    .endprolog
    STRING_ENTER
    std
    rep stosw
    cld
    STRING_LEAVE
std_rep_stosw ENDP

std_rep_stosd PROC FRAME
    .endprolog
    STRING_ENTER
    std
    rep stosd
    cld
    STRING_LEAVE
std_rep_stosd ENDP

std_lodsb PROC FRAME
    .endprolog
    STRING_ENTER
    std
    lodsb
    cld
    STRING_LEAVE
std_lodsb ENDP

std_lodsq PROC FRAME
    .endprolog
    STRING_ENTER
    std
    lodsq
    cld
    STRING_LEAVE
std_lodsq ENDP

std_cmpsb PROC FRAME
    .endprolog
    STRING_ENTER
    std
    cmpsb
    cld
    STRING_LEAVE
std_cmpsb ENDP

std_repne_scasb PROC FRAME
    .endprolog
    STRING_ENTER
    std
    repne scasb
    cld
    STRING_LEAVE
std_repne_scasb ENDP

std_repe_scasq PROC FRAME
    .endprolog
    STRING_ENTER
    std
    repe scasq
    cld
    STRING_LEAVE
std_repe_scasq ENDP

std_repe_cmpsw PROC FRAME
    .endprolog
    STRING_ENTER
    std
    repe cmpsw
    cld
    STRING_LEAVE
std_repe_cmpsw ENDP

std_repne_cmpsd PROC FRAME
    .endprolog
    STRING_ENTER
    std
    repne cmpsd
    cld
    STRING_LEAVE
std_repne_cmpsd ENDP

std_cld_rep_movsb PROC FRAME
    .endprolog
    STRING_ENTER
    std
    cld
    rep movsb
    STRING_LEAVE
std_cld_rep_movsb ENDP

END
