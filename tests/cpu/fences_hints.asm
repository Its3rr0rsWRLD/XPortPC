; coverage: source cpu_aot_fences_hints
; Source-owned differential fixture for the memory-ordering fences, PAUSE and the cache hints: LFENCE,
; MFENCE, SFENCE, PAUSE, PREFETCHT0, PREFETCHT1, PREFETCHT2, PREFETCHNTA, PREFETCH, PREFETCHW, CLFLUSH,
; CLFLUSHOPT and CLWB. Each export loads and stores around the instruction, so a lowering that drops or
; moves those accesses changes its result. Every export takes (p, v, q): p is a 512-byte buffer.
.code

; p[0] = v; SFENCE; r = p[0]; LFENCE; r += p[1]; MFENCE; p[2] = r; return r.
fence_order PROC FRAME
    .endprolog
    mov qword ptr [rcx], rdx
    sfence
    mov rax, qword ptr [rcx]
    lfence
    add rax, qword ptr [rcx+8]
    mfence
    mov qword ptr [rcx+16], rax
    ret
fence_order ENDP

; Returns 3 * v after v iterations that each execute PAUSE.
pause_spin PROC FRAME
    .endprolog
    xor eax, eax
    test rdx, rdx
    jz done
spin:
    pause
    add rax, 3
    sub rdx, 1
    jnz spin
done:
    ret
pause_spin ENDP

; Prefetches four lines of p with T0, T1, T2 and NTA, and q and q + 4096, which may be any address
; because a prefetch never faults. Returns p[0] + p[8] + p[16] + p[24].
prefetch_sum PROC FRAME
    .endprolog
    prefetcht0 byte ptr [rcx]
    prefetcht1 byte ptr [rcx+64]
    prefetcht2 byte ptr [rcx+128]
    prefetchnta byte ptr [rcx+192]
    prefetcht0 byte ptr [r8]
    prefetchnta byte ptr [r8+4096]
    mov rax, qword ptr [rcx]
    add rax, qword ptr [rcx+64]
    add rax, qword ptr [rcx+128]
    add rax, qword ptr [rcx+192]
    ret
prefetch_sum ENDP

; PREFETCH p and PREFETCHW p + 8 and q, then p[1] = v; return p[0] + v.
prefetch_write PROC FRAME
    .endprolog
    prefetch byte ptr [rcx]
    prefetchw byte ptr [rcx+8]
    prefetchw byte ptr [r8]
    mov qword ptr [rcx+8], rdx
    mov rax, qword ptr [rcx]
    add rax, rdx
    ret
prefetch_write ENDP

; p[0] = v; CLFLUSH p; return p[0].
flush_store PROC FRAME
    .endprolog
    mov qword ptr [rcx], rdx
    clflush byte ptr [rcx]
    mov rax, qword ptr [rcx]
    ret
flush_store ENDP

; p[8] = v; CLFLUSHOPT p + 64; return p[8] ^ p[9].
flushopt_store PROC FRAME
    .endprolog
    mov qword ptr [rcx+64], rdx
    clflushopt byte ptr [rcx+64]
    mov rax, qword ptr [rcx+64]
    xor rax, qword ptr [rcx+72]
    ret
flushopt_store ENDP

; p[16] = v; CLWB p + 128; return p[16] - p[17].
clwb_store PROC FRAME
    .endprolog
    mov qword ptr [rcx+128], rdx
    clwb byte ptr [rcx+128]
    mov rax, qword ptr [rcx+128]
    sub rax, qword ptr [rcx+136]
    ret
clwb_store ENDP

END
