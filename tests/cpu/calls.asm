; Source-owned differential fixture for direct calls and tail jumps between functions of one image.
; Each export is fn(x, y, trace) with x in RCX, y in RDX and a three-word trace in R8, and returns
; RAX. The callees are not exported: each has its own runtime-function entry and lies below its
; callers. The register probe seeds RBX and RSI, so a save or restore that the translation loses
; shows up as a changed sentinel.
.code

; RAX = 3 * RCX + RDX. Called by call_leaf and mid_step and reached by tail_call.
leaf_mix PROC FRAME
    .endprolog
    lea rax, [rcx+rcx*2]
    add rax, rdx
    ret
leaf_mix ENDP

; AL = CL + DL. Only the low byte of RAX is defined at its RET.
low_byte PROC FRAME
    .endprolog
    mov al, cl
    add al, dl
    ret
low_byte ENDP

; RAX = leaf_mix(RCX ^ RDX, RDX) + RDX. RDX is spilled into its own frame above the callee's
; home area and reloaded after the call.
mid_step PROC FRAME
    sub rsp, 28h
    .allocstack 28h
    .endprolog
    mov qword ptr [rsp+20h], rdx
    xor rcx, rdx
    call leaf_mix
    add rax, qword ptr [rsp+20h]
    add rsp, 28h
    ret
mid_step ENDP

; trace[0] = leaf_mix(x, y); returns it plus one. The trace pointer survives the call in RBX.
call_leaf PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, r8
    call leaf_mix
    mov qword ptr [rbx], rax
    add rax, 1
    add rsp, 20h
    pop rbx
    ret
call_leaf ENDP

; Three levels: chain3 -> mid_step -> leaf_mix. trace[1] = the result, kept in RSI.
chain3 PROC FRAME
    push rsi
    .pushreg rsi
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rsi, r8
    call mid_step
    mov qword ptr [rsi+8], rax
    add rsp, 20h
    pop rsi
    ret
chain3 ENDP

; trace[2] and RAX = (x + y) & 0FFh: low_byte defines one byte, which MOVZX widens.
narrow_call PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, r8
    call low_byte
    movzx eax, al
    mov qword ptr [rbx+10h], rax
    add rsp, 20h
    pop rbx
    ret
narrow_call ENDP

; A tail jump to low_byte: only the low byte of RAX is defined.
narrow_tail PROC FRAME
    .endprolog
    jmp low_byte
narrow_tail ENDP

; A tail jump to leaf_mix with x + 5.
tail_call PROC FRAME
    .endprolog
    add rcx, 5
    jmp leaf_mix
tail_call ENDP

; trace[0] = x, then the frame is popped and mid_step(x + 1, y) returns to the caller.
tail_after_frame PROC FRAME
    push rbx
    .pushreg rbx
    .endprolog
    mov rbx, rcx
    mov qword ptr [r8], rbx
    lea rcx, [rbx+1]
    pop rbx
    jmp mid_step
tail_after_frame ENDP

; The MSVC /O2 save shapes across a call: RBX saved by MOV into this function's own home space
; above entry RSP, and RSI saved by MOV into the allocation above the callee's home space. Both
; survive the call. trace[1] = leaf_mix(x, y); returns it XOR x, with x kept in RBX.
home_save_call PROC FRAME
    mov qword ptr [rsp+8], rbx
    sub rsp, 28h
    .allocstack 28h
    .savereg rbx, 30h
    mov qword ptr [rsp+20h], rsi
    .savereg rsi, 20h
    .endprolog
    mov rbx, rcx
    mov rsi, r8
    call leaf_mix
    mov qword ptr [rsi+8], rax
    xor rax, rbx
    mov rsi, qword ptr [rsp+20h]
    mov rbx, qword ptr [rsp+30h]
    add rsp, 28h
    ret
home_save_call ENDP

; A regression control, not translated by the build: x is stored at entry RSP-0x40, RSP rises
; to entry RSP-0x38 for the call, whose return address then overwrites that slot, and RSP falls
; back before the reload. Natively the reload returns the return address, not x.
below_call PROC FRAME
    sub rsp, 58h
    .allocstack 58h
    .endprolog
    mov qword ptr [rsp+18h], rcx
    add rsp, 20h
    call leaf_mix
    sub rsp, 20h
    mov rax, qword ptr [rsp+18h]
    add rsp, 58h
    ret
below_call ENDP
END
