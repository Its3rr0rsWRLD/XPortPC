"""gfx1013 pixel-shader lowering for tools/pixel_aot.py, split by instruction family (docs/design/module-layout.md).

- lowering.py: lower() and the state it threads through the forms.
- dispatch.py: the form registry (@form) and the dispatch of one instruction to its form.
- registers.py: the register model and the operand readers.
- control_flow.py: basic blocks, structured control flow and join variables (CF-1).
- hlsl.py: the preamble and the helper functions the emitted HLSL needs.
- forms/: one module per instruction family; every module in it is imported and registers its forms.
"""
