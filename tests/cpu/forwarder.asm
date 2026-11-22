; A DLL with one local export and one forwarded export. The linker records the forwarder string as
; "cpu_import_provider.mix_args"; Windows appends ".dll" when it resolves the target.
.code
PUBLIC local_value
local_value PROC
    mov eax, 7
    ret
local_value ENDP
END
