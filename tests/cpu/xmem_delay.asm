; Source-built fixture for tools/xmem_attribute_scan.py: an XMemAlloc call through the
; delay-load IAT (the image is linked with /DELAYLOAD:xmem.dll). The image is only read.
EXTERN __imp_XMemAlloc:QWORD

.code
; Stand-in for delayimp.lib's helper, which the linker's delay-load stubs call. Nothing here runs,
; and the fixture links without the CRT that delayimp.lib needs.
__delayLoadHelper2 PROC
    xor eax, eax
    ret
__delayLoadHelper2 ENDP

delay_site PROC
    mov edx, 05E50000h
    call QWORD PTR __imp_XMemAlloc
    ret
delay_site ENDP
END
