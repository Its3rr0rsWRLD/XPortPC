; Native-only harness for tests/cpu/x87_add.py; it is never translated.
;
; x87_call(fn, input, output) saves the caller's whole x87 state with FNSAVE (environment and all eight
; register values), which also leaves the profile's entry state: TOP 0, eight empty registers and a
; clear status word. It then loads control word 0x027F (53-bit precision, round to nearest-even, all
; exceptions masked), calls fn(input, output), records the state fn left and restores the caller's state
; with FRSTOR. It returns the control word in bits 0 to 15, the status word in bits 16 to 31 and the tag
; word in bits 32 to 47, as they were when fn returned. The native and translated functions both run
; through it.
;
; x87_call_envonly is the same with FNSTENV/FNINIT and FLDENV, which keep TOP and the tags but not the
; register values. It exists only as a control for x87_seeded.
;
; x87_seeded(harness, fn, io, probe) checks that a harness preserves a live caller value. It saves its own
; caller's state, loads the control word at probe+16, pushes the m80 value at probe+0, and calls
; harness(fn, io[0], io[1]). Then it stores the environment it sees at probe+48 (28 bytes), pops the
; value to probe+32 and restores its caller's state. It returns what the harness returned.
.code

x87_call PROC FRAME
    sub rsp, 200
    .allocstack 200
    .endprolog
    fnsave [rsp+72]
    mov word ptr [rsp+32], 027Fh
    fldcw word ptr [rsp+32]
    mov rax, rcx
    mov rcx, rdx
    mov rdx, r8
    call rax
    fnstenv [rsp+40]
    movzx eax, word ptr [rsp+40]
    movzx edx, word ptr [rsp+44]
    shl edx, 16
    or eax, edx
    movzx edx, word ptr [rsp+48]
    shl rdx, 32
    or rax, rdx
    frstor [rsp+72]
    add rsp, 200
    ret
x87_call ENDP

x87_call_envonly PROC FRAME
    sub rsp, 104
    .allocstack 104
    .endprolog
    fnstenv [rsp+72]
    fninit
    mov word ptr [rsp+32], 027Fh
    fldcw word ptr [rsp+32]
    mov rax, rcx
    mov rcx, rdx
    mov rdx, r8
    call rax
    fnstenv [rsp+40]
    movzx eax, word ptr [rsp+40]
    movzx edx, word ptr [rsp+44]
    shl edx, 16
    or eax, edx
    movzx edx, word ptr [rsp+48]
    shl rdx, 32
    or rax, rdx
    fldenv [rsp+72]
    add rsp, 104
    ret
x87_call_envonly ENDP

x87_seeded PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 160
    .allocstack 160
    .endprolog
    mov rbx, r9
    fnsave [rsp+40]
    fldcw word ptr [rbx+16]
    fld tbyte ptr [rbx]
    mov rax, rcx
    mov rcx, rdx
    mov rdx, qword ptr [r8]
    mov r8, qword ptr [r8+8]
    call rax
    fnstenv [rbx+48]
    fstp tbyte ptr [rbx+32]
    frstor [rsp+40]
    add rsp, 160
    pop rbx
    ret
x87_seeded ENDP

END
