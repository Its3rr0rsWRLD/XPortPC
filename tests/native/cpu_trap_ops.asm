; Leaf functions that each run one Zen 2 instruction a host may lack, for tests/native/cpu_trap_title.cpp.
; The register forms and the AMD-only instructions are written as bytes (assembled with llvm-mc from the
; mnemonic in each comment), since not every MASM knows them; the memory forms of SHA-NI use mnemonics so the
; assembler encodes the RIP-relative displacement. Each instruction starts at a global label listed in x2w_cpu_trap_sites,
; which x2w_launch --force-cpu-traps overwrites with UD2. The vector functions take (a, b, out): XMM1 from
; [rcx], XMM2 from [rdx], the result from XMM1 to [r8]; sha256rnds2 also takes XMM0 from [r9].

.data
ALIGN 16
rip_slot dq 0, 0

ALIGN 8
PUBLIC x2w_cpu_trap_sites
x2w_cpu_trap_sites LABEL QWORD
    dq site_sha1rnds4_0, site_sha1rnds4_1, site_sha1rnds4_2, site_sha1rnds4_3
    dq site_sha1nexte, site_sha1msg1, site_sha1msg2
    dq site_sha256rnds2, site_sha256msg1, site_sha256msg2
    dq site_sha256msg1_sib, site_sha1rnds4_rip, site_sha1nexte_disp
    dq site_extrq_16_8, site_extrq_64_0, site_extrq_5_59, site_extrq_reg
    dq site_insertq_12_20, site_insertq_64_0, site_insertq_1_63, site_insertq_reg
    dq site_movntsd, site_movntss
    dq site_clzero, site_rdpid_rax, site_rdpid_r10, site_rdpru, site_monitorx, site_mwaitx, site_clwb
    dq 0

.code

VECOP MACRO name, site, bytes:VARARG
name PROC
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
site::
    db bytes
    movdqu xmmword ptr [r8], xmm1
    ret
name ENDP
ENDM

VECOP op_sha1rnds4_0, site_sha1rnds4_0, 0fh, 3ah, 0cch, 0cah, 00h   ; sha1rnds4 xmm1, xmm2, 0
VECOP op_sha1rnds4_1, site_sha1rnds4_1, 0fh, 3ah, 0cch, 0cah, 01h   ; sha1rnds4 xmm1, xmm2, 1
VECOP op_sha1rnds4_2, site_sha1rnds4_2, 0fh, 3ah, 0cch, 0cah, 02h   ; sha1rnds4 xmm1, xmm2, 2
VECOP op_sha1rnds4_3, site_sha1rnds4_3, 0fh, 3ah, 0cch, 0cah, 03h   ; sha1rnds4 xmm1, xmm2, 3
VECOP op_sha1nexte, site_sha1nexte, 0fh, 38h, 0c8h, 0cah            ; sha1nexte xmm1, xmm2
VECOP op_sha1msg1, site_sha1msg1, 0fh, 38h, 0c9h, 0cah              ; sha1msg1 xmm1, xmm2
VECOP op_sha1msg2, site_sha1msg2, 0fh, 38h, 0cah, 0cah              ; sha1msg2 xmm1, xmm2
VECOP op_sha256msg1, site_sha256msg1, 0fh, 38h, 0cch, 0cah          ; sha256msg1 xmm1, xmm2
VECOP op_sha256msg2, site_sha256msg2, 0fh, 38h, 0cdh, 0cah          ; sha256msg2 xmm1, xmm2
VECOP op_extrq_16_8, site_extrq_16_8, 66h, 0fh, 78h, 0c1h, 10h, 08h ; extrq xmm1, 16, 8
VECOP op_extrq_64_0, site_extrq_64_0, 66h, 0fh, 78h, 0c1h, 00h, 00h ; extrq xmm1, 0, 0 (length 64)
VECOP op_extrq_5_59, site_extrq_5_59, 66h, 0fh, 78h, 0c1h, 05h, 3bh ; extrq xmm1, 5, 59
VECOP op_extrq_reg, site_extrq_reg, 66h, 0fh, 79h, 0cah             ; extrq xmm1, xmm2
VECOP op_insertq_12_20, site_insertq_12_20, 0f2h, 0fh, 78h, 0cah, 0ch, 14h ; insertq xmm1, xmm2, 12, 20
VECOP op_insertq_64_0, site_insertq_64_0, 0f2h, 0fh, 78h, 0cah, 00h, 00h   ; insertq xmm1, xmm2, 0, 0
VECOP op_insertq_1_63, site_insertq_1_63, 0f2h, 0fh, 78h, 0cah, 01h, 3fh   ; insertq xmm1, xmm2, 1, 63
VECOP op_insertq_reg, site_insertq_reg, 0f2h, 0fh, 79h, 0cah        ; insertq xmm1, xmm2

op_sha256rnds2 PROC
    movdqu xmm1, xmmword ptr [rcx]
    movdqu xmm2, xmmword ptr [rdx]
    movdqu xmm0, xmmword ptr [r9]
site_sha256rnds2::
    db 0fh, 38h, 0cbh, 0cah                 ; sha256rnds2 xmm1, xmm2, xmm0
    movdqu xmmword ptr [r8], xmm1
    ret
op_sha256rnds2 ENDP

; (a, b, out, index): sha256msg1 xmm8, [rdx+r9*4+16] with RDX moved back by index*4+16, so the operand
; is b again. XMM8 is nonvolatile and is saved on the stack.
op_sha256msg1_sib PROC FRAME
    sub rsp, 24
    .allocstack 24
    .endprolog
    movdqu xmmword ptr [rsp], xmm8
    movdqu xmm8, xmmword ptr [rcx]
    lea r10, [r9*4+16]
    sub rdx, r10
site_sha256msg1_sib::
    sha256msg1 xmm8, xmmword ptr [rdx+r9*4+16]
    movdqu xmmword ptr [r8], xmm8
    movdqu xmm8, xmmword ptr [rsp]
    add rsp, 24
    ret
op_sha256msg1_sib ENDP

; (a, b, out): b is copied to rip_slot, then sha1rnds4 xmm1, [rip_slot], 2 (RIP-relative, with an imm8 after
; the displacement).
op_sha1rnds4_rip PROC
    movdqu xmm1, xmmword ptr [rdx]
    movdqu xmmword ptr [rip_slot], xmm1
    movdqu xmm1, xmmword ptr [rcx]
site_sha1rnds4_rip::
    sha1rnds4 xmm1, xmmword ptr [rip_slot], 2
    movdqu xmmword ptr [r8], xmm1
    ret
op_sha1rnds4_rip ENDP

; (a, b, out): sha1nexte xmm5, [r13+200h] with R13 = b - 200h (REX.B, mod 10, disp32). R13 is saved.
op_sha1nexte_disp PROC FRAME
    push r13
    .pushreg r13
    .endprolog
    lea r13, [rdx-200h]
    movdqu xmm5, xmmword ptr [rcx]
site_sha1nexte_disp::
    sha1nexte xmm5, xmmword ptr [r13+200h]
    movdqu xmmword ptr [r8], xmm5
    pop r13
    ret
op_sha1nexte_disp ENDP

; (a, destination): the low 64 or 32 bits of [rcx] to [rdx].
op_movntsd PROC
    movdqu xmm1, xmmword ptr [rcx]
site_movntsd::
    db 0f2h, 0fh, 2bh, 0ah                  ; movntsd qword ptr [rdx], xmm1
    sfence
    ret
op_movntsd ENDP

op_movntss PROC
    movdqu xmm1, xmmword ptr [rcx]
site_movntss::
    db 0f3h, 0fh, 2bh, 0ah                  ; movntss dword ptr [rdx], xmm1
    sfence
    ret
op_movntss ENDP

; (address): zero the 64-byte line holding address.
op_clzero PROC
    mov rax, rcx
site_clzero::
    db 0fh, 01h, 0fch                       ; clzero
    ret
op_clzero ENDP

; (out): RDPID into RAX, and into R10 (REX.B), with the register first set to all ones.
op_rdpid_rax PROC
    mov rax, -1
site_rdpid_rax::
    db 0f3h, 0fh, 0c7h, 0f8h                ; rdpid rax
    mov qword ptr [rcx], rax
    ret
op_rdpid_rax ENDP

op_rdpid_r10 PROC
    mov r10, -1
site_rdpid_r10::
    db 0f3h, 41h, 0fh, 0c7h, 0fah           ; rdpid r10
    mov qword ptr [rcx], r10
    ret
op_rdpid_r10 ENDP

; (id, out): RDPRU with ECX = id; out = RAX, RDX (both all ones before), CF.
op_rdpru PROC
    mov r9, rdx
    mov rax, -1
    mov rdx, -1
    clc
site_rdpru::
    db 0fh, 01h, 0fdh                       ; rdpru
    setc r10b
    movzx r10d, r10b
    mov qword ptr [r9], rax
    mov qword ptr [r9+8], rdx
    mov qword ptr [r9+16], r10
    ret
op_rdpru ENDP

; (address, out): MONITORX on address, then MWAITX with a timer of 1000 TSC ticks (ECX bit 1, EBX); out =
; RAX, RCX, RDX, RBX after both, which neither changes.
op_monitorx_mwaitx PROC FRAME
    push rbx
    .pushreg rbx
    .endprolog
    mov r9, rdx
    mov rax, rcx
    xor ecx, ecx
    xor edx, edx
site_monitorx::
    db 0fh, 01h, 0fah                       ; monitorx
    xor eax, eax
    mov ecx, 2
    mov ebx, 1000
site_mwaitx::
    db 0fh, 01h, 0fbh                       ; mwaitx
    mov qword ptr [r9], rax
    mov qword ptr [r9+8], rcx
    mov qword ptr [r9+16], rdx
    mov qword ptr [r9+24], rbx
    pop rbx
    ret
op_monitorx_mwaitx ENDP

; (address): CLWB on address, with EDX:EAX all ones (an XSAVEOPT component mask, should a CPU without CLWB
; ignore the 66 prefix).
op_clwb PROC
    mov eax, -1
    mov edx, -1
site_clwb::
    db 66h, 0fh, 0aeh, 31h                  ; clwb byte ptr [rcx]
    ret
op_clwb ENDP

; The unhandled control: UD2, not a listed site.
op_ud2 PROC
    db 0fh, 0bh                             ; ud2
    ret
op_ud2 ENDP

END
