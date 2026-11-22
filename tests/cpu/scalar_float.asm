; Windows x64 leaves built from scalar SSE/SSE2 instructions. An argument arrives in the XMM
; register of its slot when it is floating point and in the integer register otherwise.
; SWAP_OPERANDS builds the control: one operand order or source differs in every function.
.code
; float blend_ss(float a, float b, float* c, float d)
; c[1] = (a + b) * c[0] - d, and the result is a / c[1].
blend_ss PROC FRAME
    .endprolog
    movaps xmm2, xmm0
IFDEF SWAP_OPERANDS
    ; b + a has the same value, but returns the other payload when both are NaN.
    addss xmm1, xmm2
    movss xmm2, xmm1
ELSE
    addss xmm2, xmm1
ENDIF
    movss xmm4, DWORD PTR [r8]
    mulss xmm2, xmm4
    subss xmm2, xmm3
    movss DWORD PTR [r8+4], xmm2
    divss xmm0, DWORD PTR [r8+4]
    ret
blend_ss ENDP

; double blend_sd(double a, double b, double* c, double d)
; c[1] = (a - b) * c[0] + d, and the result is c[1] / c[0].
blend_sd PROC FRAME
    .endprolog
IFDEF SWAP_OPERANDS
    movsd xmm4, xmm1
    subsd xmm4, xmm0
ELSE
    movsd xmm4, xmm0
    subsd xmm4, xmm1
ENDIF
    mulsd xmm4, QWORD PTR [r8]
    addsd xmm4, xmm3
    movsd QWORD PTR [r8+8], xmm4
    movsd xmm0, QWORD PTR [r8+8]
    divsd xmm0, QWORD PTR [r8]
    ret
blend_sd ENDP

; unsigned convert(float f, double d, void* out)
; out: +0 int32 of f, +4 int32 of d, +8 int64 of f, +16 int64 of d, +24 double of f,
; +32 float of d, +36 the bits of f, +40 the bits of d, +48 int32 of the stored float,
; +56 double of the stored float, +64 the bits of d with the float of d as the low dword,
; +72 the bits of d with f as the low dword.
; The result is the sum of the first two.
convert PROC FRAME
    .endprolog
IFDEF SWAP_OPERANDS
    cvttsd2si eax, xmm1
    cvttss2si ecx, xmm0
ELSE
    cvttss2si eax, xmm0
    cvttsd2si ecx, xmm1
ENDIF
    mov DWORD PTR [r8], eax
    mov DWORD PTR [r8+4], ecx
    add eax, ecx
    cvttss2si rdx, xmm0
    mov QWORD PTR [r8+8], rdx
    cvttsd2si rdx, xmm1
    mov QWORD PTR [r8+16], rdx
    cvtss2sd xmm2, xmm0
    movsd QWORD PTR [r8+24], xmm2
    cvtsd2ss xmm3, xmm1
    movss DWORD PTR [r8+32], xmm3
    movd ecx, xmm0
    movd xmm4, ecx
    movd DWORD PTR [r8+36], xmm4
    movq xmm5, xmm1
    movq QWORD PTR [r8+40], xmm5
    movss xmm5, xmm0
    movq QWORD PTR [r8+72], xmm5
    cvttss2si ecx, DWORD PTR [r8+32]
    mov DWORD PTR [r8+48], ecx
    movq xmm4, QWORD PTR [r8+40]
    cvtsd2ss xmm4, QWORD PTR [r8+40]
    movq QWORD PTR [r8+64], xmm4
    cvtss2sd xmm4, DWORD PTR [r8+32]
    movsd QWORD PTR [r8+56], xmm4
    ret
convert ENDP

; double from_int(int64 n, void* out)
; out: +0 float of the low 32 bits, +4 float of n, +8 double of the low 32 bits,
; +16 double of n, +24 n. The result is the sum of the two doubles.
from_int PROC FRAME
    .endprolog
    xorps xmm0, xmm0
    pxor xmm1, xmm1
IFDEF SWAP_OPERANDS
    cvtsi2ss xmm0, rcx
    cvtsi2ss xmm1, ecx
ELSE
    cvtsi2ss xmm0, ecx
    cvtsi2ss xmm1, rcx
ENDIF
    movss DWORD PTR [rdx], xmm0
    movss DWORD PTR [rdx+4], xmm1
    xorpd xmm2, xmm2
    cvtsi2sd xmm2, ecx
    movsd QWORD PTR [rdx+8], xmm2
    mov QWORD PTR [rdx+24], rcx
    cvtsi2sd xmm0, QWORD PTR [rdx+24]
    movsd QWORD PTR [rdx+16], xmm0
    addsd xmm0, xmm2
    ret
from_int ENDP

; unsigned classify_ss(float a, float b)
; Bit 0: equal. Bit 1: a above b. Bit 2: a below b. Bit 3: unordered.
classify_ss PROC FRAME
    .endprolog
    xor eax, eax
    ucomiss xmm0, xmm1
    jp short ss_unordered
    jne short ss_above
    or eax, 1
ss_above:
    comiss xmm0, xmm1
    jbe short ss_below
    or eax, 2
ss_below:
IFDEF SWAP_OPERANDS
    ucomiss xmm1, xmm0
ELSE
    ucomiss xmm0, xmm1
ENDIF
    jae short ss_done
    or eax, 4
    ret
ss_unordered:
    or eax, 8
ss_done:
    ret
classify_ss ENDP

; unsigned classify_sd(double a, const double* b), with the same bits for a and *b.
classify_sd PROC FRAME
    .endprolog
    xor eax, eax
    ucomisd xmm0, QWORD PTR [rdx]
    jnp short sd_ordered
    or eax, 8
    ret
sd_ordered:
    ucomisd xmm0, QWORD PTR [rdx]
    je short sd_equal
IFDEF SWAP_OPERANDS
    movsd xmm1, QWORD PTR [rdx]
    comisd xmm1, xmm0
ELSE
    comisd xmm0, QWORD PTR [rdx]
ENDIF
    ja short sd_above
    comisd xmm0, QWORD PTR [rdx]
    jb short sd_below
    ret
sd_equal:
    or eax, 1
    ret
sd_above:
    or eax, 2
    ret
sd_below:
    or eax, 4
    ret
classify_sd ENDP

; round_trip(f): CVTSS2SD then CVTSD2SS. Each conversion quiets a signalling NaN, so the pair is
; not an identity. The swapped-operand build keeps the value with MOVSS instead.
round_trip PROC FRAME
    .endprolog
IFDEF SWAP_OPERANDS
    movss xmm0, xmm0
ELSE
    cvtss2sd xmm0, xmm0
    cvtsd2ss xmm0, xmm0
ENDIF
    ret
round_trip ENDP
END