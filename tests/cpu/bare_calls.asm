; Source-owned differential fixture for direct calls and tail jumps to functions without unwind data.
; Each export is fn(x, y, trace) with x in RCX, y in RDX and a three-word trace in R8, and returns
; RAX. bare_mix and bare_low are leaves declared without FRAME, so the image has no .pdata entry
; for them, and they are not exported. fake_thunk has the shape of an import thunk and is never
; reached as built. The public *_end labels mark the byte after each leaf, and bare_mix_inner an
; aligned interior label from which MOV, SUB and RET would translate on their own: the linker map gives the range manifest these source
; labels. The register probe seeds RBX and RSI.
.data
thunk_slot dq 0
IFDEF IMAGE_SELECTOR
PUBLIC selector_bias, selector_result
selector_bias dq 5
selector_result dq -1
ENDIF

.code
PUBLIC bare_mix_inner, bare_mix_end, bare_low_end, fake_thunk_end
; RAX = 5 * RCX - RDX. Called by call_bare and twice_bare.
bare_mix PROC
    imul rcx, rcx, 5
bare_mix_inner::
    mov rax, rcx
    sub rax, rdx
IFDEF IMAGE_SELECTOR
    add rax, selector_bias
    mov selector_result, rax
    mov rax, selector_result
ENDIF
    ret
bare_mix ENDP
bare_mix_end LABEL BYTE

; AL = CL XOR DL. Only the low byte of RAX is defined at its RET.
bare_low PROC
    mov al, cl
    xor al, dl
    ret
bare_low ENDP
bare_low_end LABEL BYTE

; An indirect jump through memory, as an import thunk is.
fake_thunk PROC
    jmp qword ptr [thunk_slot]
fake_thunk ENDP
fake_thunk_end LABEL BYTE

; trace[0] = bare_mix(x, y), which is also returned. The trace pointer survives the call in RBX.
call_bare PROC FRAME
    push rbx
    .pushreg rbx
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rbx, r8
    call bare_mix
    mov qword ptr [rbx], rax
    add rsp, 20h
    pop rbx
    ret
call_bare ENDP

; trace[1] = bare_mix(x + 1, y), which is also returned: a second caller of the same leaf.
twice_bare PROC FRAME
    push rsi
    .pushreg rsi
    sub rsp, 20h
    .allocstack 20h
    .endprolog
    mov rsi, r8
    lea rcx, [rcx+1]
    call bare_mix
    mov qword ptr [rsi+8], rax
    add rsp, 20h
    pop rsi
    ret
twice_bare ENDP

; A tail jump to bare_low: only the low byte of RAX is defined.
tail_bare PROC FRAME
    .endprolog
    jmp bare_low
tail_bare ENDP
END
