; Runtime pixel input layout (docs/design/runtime.md, "Pixel input layout"): a pixel program that reads its
; position-derived input VGPRs. SPI_PS_INPUT_ENA = ADDR = persp_center | pos_x | pos_y | pos_z | front_face (0x1702):
; v0, v1 the barycentrics, v2 pos_x, v3 pos_y, v4 pos_z, v5 front_face. Exports (x * y, y, z, face) as 32-bit floats.
v_mul_f32_e32 v6, v2, v3
exp mrt0 v6, v3, v4, v5 done vm
s_endpgm
