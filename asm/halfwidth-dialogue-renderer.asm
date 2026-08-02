.psx

; INPUT_EXE is supplied by scripts/build_halfwidth_text_patch.py.
; PS-X EXE file offset 0 maps to load address - 0x800.
.open INPUT_EXE, 0x8002F800

; Replace sub_80032704 in place.  Rebuilding the compact font-selection head
; leaves enough room for the variable visual advance without a code cave.
.org 0x80032704
    addiu sp, sp, -0x30
    sw ra, 0x2C(sp)
    sw s0, 0x28(sp)
    sw s1, 0x24(sp)
    sw s2, 0x20(sp)
    sw s3, 0x1C(sp)
    move s3, zero

    lui t0, 0x8006
    lw t0, 0x1194(t0)
    nop
    lhu t0, 0(t0)
    nop
    andi v0, t0, 0x0180
    beqz v0, @@direct_text
    andi v0, t0, 0x0080

    ; Player-name rendering selects one of the two live name arrays and always
    ; uses the primary 14x14 table.  It keeps the original fixed advance.
    lui a0, 0x8001
    ori a0, a0, 0x4A00
    lui v1, 0x8006
    lw v1, 0x122C(v1)
    lui t0, 0x8006
    lbu v1, 0(v1)
    nop
    sll v1, v1, 1
    beqz v0, @@given_name
    nop
    lw t0, 0x1580(t0)
    b @@name_glyph
    nop

@@given_name:
    lw t0, 0x15F8(t0)

@@name_glyph:
    nop
    addu v1, v1, t0
    lhu v1, 0(v1)
    b @@glyph_selected
    nop

@@direct_text:
    ; Direct streams choose the primary or alternate table from flag 0x2000.
    lui v0, 0x8006
    lw v0, 0x1140(v0)
    nop
    lhu v0, 0(v0)
    nop
    andi v0, v0, 0x2000
    beqz v0, @@primary_font
    addiu s3, zero, 1
    lui a0, 0x8018
    ori a0, a0, 0x5000
    addiu s3, zero, 2
    b @@load_direct_glyph
    nop

@@primary_font:
    lui a0, 0x8001
    ori a0, a0, 0x4A00

@@load_direct_glyph:
    lui v0, 0x8006
    lw v0, 0x0FA0(v0)
    lui v1, 0x8006
    lw v1, 0x1158(v1)
    lhu v0, 0(v0)
    lw v1, 0(v1)
    nop
    sll v0, v0, 1
    addu v0, v0, v1
    lhu v1, 0(v0)
    nop
    andi v1, v1, 0x0FFF

@@glyph_selected:
    move s0, v1

    ; a1 = selected_font_base + glyph_id * 74
    sll v0, s0, 3
    addu v0, v0, s0
    sll v0, v0, 2
    addu v0, v0, s0
    sll v0, v0, 1
    addu a1, v0, a0

    ; Keep the engine's fixed 17-column logical position.  Only the destination
    ; byte coordinate is shifted left by prior half-width glyphs on this row.
    lui v0, 0x8006
    lw v0, 0x1070(v0)
    lui t1, 0x8006
    lw t1, 0x10A4(t1)
    lhu t0, 0(v0)
    lbu t1, 0(t1)
    lui s1, 0x8002
    divu t0, t1
    mflo t2
    mfhi t3

    ; legacy destination = 0x8002D000 + row*0x7E0 + column*7
    sll t4, t3, 3
    subu t4, t4, t3
    sll v0, t2, 6
    subu v0, v0, t2
    sll v0, v0, 5
    addu t4, t4, v0
    ori s1, s1, 0xD000
    addu s1, s1, t4

    ; Name-substitution glyphs keep their 14px advance, but they must inherit
    ; the reduction accumulated by half-width direct glyphs earlier on the
    ; same row.  Skipping this state load made the following direct glyphs
    ; overlap the unshifted surname/given-name records.
    nop
    move s2, zero

    ; The final word of the 0x8002D000..0x80030000 transient render buffer is
    ; outside the uploaded dialogue surface.  It stores:
    ;   bits 31..16 previous logical position
    ;   bits 15..8  previous row
    ;   bits 7..0   accumulated byte reduction for the row
    lui t5, 0x8003
    addiu t5, t5, -4
    lw t6, 0(t5)
    nop
    srl t7, t6, 16
    sltu v0, t7, t0
    beqz v0, @@reset_reduction
    nop
    srl t7, t6, 8
    andi t7, t7, 0x00FF
    bne t7, t2, @@reset_reduction
    nop
    andi s2, t6, 0x00FF
    b @@apply_reduction
    nop

@@reset_reduction:
    move s2, zero

@@apply_reduction:
    subu s1, s1, s2

@@draw:
    jal 0x80032434
    move a0, s1

    ; Preserve the original controller-icon 0x88 mask, now at the adjusted
    ; destination coordinate.
    addiu v0, zero, 1
    bne s3, v0, @@update_state
    nop
    addiu v0, zero, 0x13
    beq s0, v0, @@mask_icon
    addiu v0, zero, 0x18
    beq s0, v0, @@mask_icon
    addiu v0, zero, 0x1A
    beq s0, v0, @@mask_icon
    addiu v0, zero, 0x1B
    bne s0, v0, @@update_state
    nop

@@mask_icon:
    move a2, s1
    move a1, zero
@@mask_row:
    move v1, zero
@@mask_column:
    lbu v0, 0(a2)
    addiu v1, v1, 1
    ori v0, v0, 0x88
    sb v0, 0(a2)
    slti v0, v1, 14
    bnez v0, @@mask_column
    addiu a2, a2, 1
    addiu a1, a1, 1
    slti v0, a1, 14
    bnez v0, @@mask_row
    addiu a2, a2, 0x70

@@update_state:
    ; Names are never classified as half-width.  They still update the
    ; previous logical position while preserving the current reduction.
    beqz s3, @@store_state
    nop

    ; 0x046(space), 0x047(!), 0x04B..0x04D(() ,), 0x04F..0x050(. ?)
    addiu t0, zero, 0x46
    beq s0, t0, @@halfwidth
    addiu t0, zero, 0x47
    beq s0, t0, @@halfwidth
    addiu t0, s0, -0x4B
    sltiu v0, t0, 3
    bnez v0, @@halfwidth
    addiu t0, s0, -0x4F
    sltiu v0, t0, 2
    beqz v0, @@store_state
    nop

@@halfwidth:
    addiu s2, s2, 3

@@store_state:
    lui v0, 0x8006
    lw v0, 0x1070(v0)
    lui t1, 0x8006
    lw t1, 0x10A4(t1)
    lhu t0, 0(v0)
    lbu t1, 0(t1)
    nop
    divu t0, t1
    mflo t2
    sll t0, t0, 16
    sll t2, t2, 8
    or t0, t0, t2
    andi s2, s2, 0x00FF
    or t0, t0, s2
    lui t5, 0x8003
    sw t0, -4(t5)

@@return:
    lw ra, 0x2C(sp)
    lw s3, 0x1C(sp)
    lw s2, 0x20(sp)
    lw s1, 0x24(sp)
    lw s0, 0x28(sp)
    jr ra
    addiu sp, sp, 0x30

; Make unexpected growth a build error; sub_800329B8 begins here.
.if org() > 0x800329B8
    .error "half-width renderer exceeds sub_80032704"
.endif
.fill 0x800329B8-org(), 0x00

.close
