; A source-built EXE that starts without a C runtime. A TLS callback and the entry point each append one
; base-4 digit to a log in .data, so the process exit code records the order in which they ran:
;   digit 1 or 3  TLS callback on DLL_PROCESS_ATTACH (3 when the reserved argument is non-null)
;   digit 2       entry point
; The entry point then calls the named import mix_args(5, 3, out), which returns 5 - 3 + 11, and returns
;   (log << 8) | (mix_args result & 0xff)
; as its exit code, and also stores it in the exported DWORD body_status, which stays 0FEEDFACEh until the body
; has returned. Defining NO_TLS drops the TLS directory, the negative control for the callback.
EXTERN __imp_mix_args:QWORD

PUBLIC body_status

.data
log_digits  DD 0
body_status DD 0FEEDFACEh          ; exported; the body stores its return value here (sentinel until then)
IFNDEF NO_TLS
tlscb SEGMENT READ ALIAS(".tlscb") 'DATA'
callbacks   DQ tls_callback, 0
tlscb ENDS

.data
tls_index DD 0
            DD 0
PUBLIC _tls_used
_tls_used   DQ 0, 0                ; StartAddressOfRawData, EndAddressOfRawData (empty template)
            DQ tls_index           ; AddressOfIndex
            DQ callbacks           ; AddressOfCallBacks
            DD 0, 0                ; SizeOfZeroFill, Characteristics
ENDIF

.code
IFNDEF NO_TLS
; (module, reason, reserved)
tls_callback PROC
    cmp edx, 1                      ; DLL_PROCESS_ATTACH only
    jne tls_done
    mov eax, 1
    test r8, r8
    jz tls_store
    mov eax, 3
tls_store:
    mov ecx, log_digits
    shl ecx, 2
    or ecx, eax
    mov log_digits, ecx
tls_done:
    ret
tls_callback ENDP
ENDIF

native_entry PROC FRAME
    sub rsp, 38h                    ; 20h shadow space, 18h for mix_args' three-word output
    .allocstack 38h
    .endprolog
    mov eax, log_digits
    shl eax, 2
    or eax, 2
    mov log_digits, eax
    mov ecx, 5
    mov edx, 3
    lea r8, [rsp+20h]
    call QWORD PTR [__imp_mix_args]
    movzx eax, al
    mov ecx, log_digits
    shl ecx, 8
    or eax, ecx
    mov body_status, eax
    add rsp, 38h
    ret
native_entry ENDP
END
