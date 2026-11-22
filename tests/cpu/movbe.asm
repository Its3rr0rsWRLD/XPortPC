; Source-owned differential fixture for MOVBE loads and stores in 16-, 32- and 64-bit widths. Each export
; takes (pointer, value, flag preset, state) in RCX, RDX, R8 and R9. The destination register starts as
; RDX, so a 16-bit load must keep its upper bits and a 32-bit load must clear them. ADD R8, R8 sets ZF and
; CF from the preset before the MOVBE, which leaves the flags alone; (CF << 1) | ZF goes to state[0].
.code

MOVBE_LEAVE MACRO
    LOCAL no_carry, no_zero
    mov r11d, 0
    jae short no_carry
    mov r11d, 2
no_carry:
    jne short no_zero
    or r11d, 1
no_zero:
    mov qword ptr [r9], r11
    ret
ENDM

load16 PROC FRAME
    .endprolog
    mov rax, rdx
    add r8, r8
    movbe ax, word ptr [rcx]
    MOVBE_LEAVE
load16 ENDP

load32 PROC FRAME
    .endprolog
    mov rax, rdx
    add r8, r8
    movbe eax, dword ptr [rcx]
    MOVBE_LEAVE
load32 ENDP

load64 PROC FRAME
    .endprolog
    mov rax, rdx
    add r8, r8
    movbe rax, qword ptr [rcx]
    MOVBE_LEAVE
load64 ENDP

; REX.R destinations with a displacement.
load16_r10 PROC FRAME
    .endprolog
    mov r10, rdx
    add r8, r8
    movbe r10w, word ptr [rcx+1]
    mov rax, r10
    MOVBE_LEAVE
load16_r10 ENDP

load64_r11 PROC FRAME
    .endprolog
    mov r11, rdx
    add r8, r8
    movbe r11, qword ptr [rcx+3]
    mov rax, r11
    MOVBE_LEAVE
load64_r11 ENDP

store16 PROC FRAME
    .endprolog
    mov rax, rdx
    add r8, r8
    movbe word ptr [rcx], dx
    MOVBE_LEAVE
store16 ENDP

store32 PROC FRAME
    .endprolog
    mov rax, rdx
    add r8, r8
    movbe dword ptr [rcx], edx
    MOVBE_LEAVE
store32 ENDP

store64 PROC FRAME
    .endprolog
    mov rax, rdx
    add r8, r8
    movbe qword ptr [rcx], rdx
    MOVBE_LEAVE
store64 ENDP

; A REX.R source and a scaled index: the store lands at pointer + 3.
store64_index PROC FRAME
    .endprolog
    mov r10, rdx
    mov eax, 2
    add r8, r8
    movbe qword ptr [rcx+rax*2-1], r10
    mov rax, r10
    MOVBE_LEAVE
store64_index ENDP

; Load and store back eight bytes further on: the bytes there come out in the original order.
roundtrip32 PROC FRAME
    .endprolog
    mov rax, rdx
    add r8, r8
    movbe eax, dword ptr [rcx]
    movbe dword ptr [rcx+8], eax
    MOVBE_LEAVE
roundtrip32 ENDP

END
