; Slot thunks for the xgameruntime.dll gateway (src/xgr/xgr_gateway.cpp).
;
; Every object the gateway hands out has xgr_stub_table as its vtable: XGR_SLOTS entries, entry N being
; a two-instruction stub that puts N in r10d and jumps to xgr_dispatch. xgr_dispatch keeps the Win64
; argument registers (rcx..r9, xmm0..xmm3) and up to XGR_STACK_ARGS stack arguments, asks
;     void* xgr_slot_enter(void* self, unsigned slot, void** args, void* caller)
; for the function to run (args points at the caller's home area: args[0] is rcx, ..., args[3] r9, then
; the stack arguments; enter may rewrite args[0], the `this` the target sees), calls it with the same
; arguments, and passes the result through
;     uintptr_t xgr_slot_leave(void* self, unsigned slot, uintptr_t result, void* caller)
; whose return value is returned. When enter returns null nothing is called and E_NOTIMPL is returned.
; xmm0 is not preserved across leave, so a float result does not survive the trip (no Gaming Runtime
; flat function returns one).

XGR_SLOTS      EQU 256
XGR_STACK_ARGS EQU 12

EXTERN xgr_slot_enter:PROC
EXTERN xgr_slot_leave:PROC

; Frame: 3 pushes + FRAME bytes. Entry rsp is 8 mod 16, so after the pushes it is 0 mod 16 and FRAME
; must be a multiple of 16. Layout from rsp: 20h shadow, XGR_STACK_ARGS*8 outgoing stack arguments,
; 4*16 saved xmm0-3, 10h spare.
FRAME_SIZE  EQU 20h + XGR_STACK_ARGS*8 + 40h + 10h
XMM_SAVE    EQU 20h + XGR_STACK_ARGS*8
ENTRY_RSP   EQU FRAME_SIZE + 3*8          ; rsp + ENTRY_RSP = rsp at entry (points at the return address)
HOME        EQU ENTRY_RSP + 8             ; caller's home area (rcx, rdx, r8, r9)
CALLER_ARGS EQU ENTRY_RSP + 28h           ; caller's fifth argument

.code

xgr_dispatch PROC FRAME
    mov     [rsp+8], rcx
    mov     [rsp+10h], rdx
    mov     [rsp+18h], r8
    mov     [rsp+20h], r9
    push    rbx
    .pushreg rbx
    push    rsi
    .pushreg rsi
    push    rdi
    .pushreg rdi
    sub     rsp, FRAME_SIZE
    .allocstack FRAME_SIZE
    .endprolog

    mov     ebx, r10d                     ; slot
    mov     rsi, rcx                      ; self
    movdqu  [rsp+XMM_SAVE], xmm0
    movdqu  [rsp+XMM_SAVE+10h], xmm1
    movdqu  [rsp+XMM_SAVE+20h], xmm2
    movdqu  [rsp+XMM_SAVE+30h], xmm3

    mov     edx, ebx
    lea     r8, [rsp+HOME]
    mov     r9, [rsp+ENTRY_RSP]
    call    xgr_slot_enter
    test    rax, rax
    jz      not_implemented
    mov     r11, rax

    i = 0
    REPT XGR_STACK_ARGS
        mov     rax, [rsp+CALLER_ARGS+i*8]
        mov     [rsp+20h+i*8], rax
        i = i + 1
    ENDM

    movdqu  xmm0, [rsp+XMM_SAVE]
    movdqu  xmm1, [rsp+XMM_SAVE+10h]
    movdqu  xmm2, [rsp+XMM_SAVE+20h]
    movdqu  xmm3, [rsp+XMM_SAVE+30h]
    mov     rcx, [rsp+HOME]
    mov     rdx, [rsp+HOME+8]
    mov     r8, [rsp+HOME+10h]
    mov     r9, [rsp+HOME+18h]
    call    r11

    mov     rcx, rsi
    mov     edx, ebx
    mov     r8, rax
    mov     r9, [rsp+ENTRY_RSP]
    call    xgr_slot_leave
    jmp     done

not_implemented:
    mov     eax, 80004001h                ; E_NOTIMPL

done:
    add     rsp, FRAME_SIZE
    pop     rdi
    pop     rsi
    pop     rbx
    ret
xgr_dispatch ENDP

XGR_STUB MACRO n
xgr_stub_&n& PROC
    mov     r10d, n
    jmp     xgr_dispatch
xgr_stub_&n& ENDP
ENDM

XGR_ENTRY MACRO n
    DQ      xgr_stub_&n&
ENDM

slot = 0
REPT XGR_SLOTS
    XGR_STUB %slot
    slot = slot + 1
ENDM

.data
PUBLIC xgr_stub_table
xgr_stub_table DQ xgr_stub_0
slot = 1
REPT XGR_SLOTS - 1
    XGR_ENTRY %slot
    slot = slot + 1
ENDM

END
