.psx
.open "unit40.bin", 0x80098000

; Unit 40 has a verified zero-filled range at 0x800A09BC..0x800A1800.
; These helpers expand only the Japanese-script player-name form.  The
; Roman-name form keeps the original slot positions and update routine.

; The original completion path reuses the completed given-name length (3)
; as the name-menu state number (3).  Once the field grows to four glyphs,
; keep the capacity comparison at four but restore state 3 explicitly.
.org 0x8009A574
    addiu   $v1, $zero, 3

; Returning from the final confirmation reconstructs the original full
; surname length as three.  Restore the expanded four-glyph length so the
; prompt/highlighter resumes on the rightmost given-name slot.
.org 0x80098370
    addiu   $v0, $zero, 4

.org 0x8009B594
    addiu   $v1, $zero, 0x0088
    j       create_japanese_slots_b
    sh      $v1, 0x1B00($v0)

.org 0x8009C138
    addiu   $v1, $zero, 0x0088
    j       create_japanese_slots_c
    sh      $v1, 0x1B00($v0)

.org 0x8009B68C
    lw      $a0, 0x1214($s0)
    jal     destroy_japanese_extra_slots
    nop
    j       0x8009B7DC
    lui     $v0, 0x8006
    nop
    nop
    nop

.org 0x8009D1A8
    j       update_name_slot
    nop

.org 0x8009DCDC
    jal     select_name_slot_position
    nop
    nop
    nop
    nop

; The original prompt and final-confirmation name frames are 44 pixels wide
; (3 * 14-pixel glyphs + 2).  Widen all eight consumers to 58 pixels.  Move
; the final-confirmation fields from the same x position as the Roman-name
; field so they do not cover the label at the left.  Keep a six-pixel gap.
.org 0x8009E932
    .db 58
.org 0x8009E934
    .dh 20
.org 0x8009E93E
    .db 58
.org 0x8009E940
    .dh 84

.org 0x8009E992
    .db 58
.org 0x8009E994
    .dh 20
.org 0x8009E99E
    .db 58
.org 0x8009E9A0
    .dh 84

.org 0x8009E9F2
    .db 58
.org 0x8009E9F4
    .dh 20
.org 0x8009E9FE
    .db 58
.org 0x8009EA00
    .dh 84

.org 0x8009EA22
    .db 58
.org 0x8009EA24
    .dh 13
.org 0x8009EA3A
    .db 58
.org 0x8009EA3C
    .dh 77

.org 0x800A09BC
create_japanese_slots_b:
    sh      $v1, 0x1B80($v0)
    addiu   $v1, $zero, 0x008F
    sh      $v1, 0x2080($v0)
    sh      $v1, 0x2100($v0)
    j       0x8009B5A0
    nop

.org 0x800A09D4
create_japanese_slots_c:
    sh      $v1, 0x1B80($v0)
    addiu   $v1, $zero, 0x008F
    sh      $v1, 0x2080($v0)
    sh      $v1, 0x2100($v0)
    j       0x8009C144
    nop

.org 0x800A09EC
destroy_japanese_extra_slots:
    addiu   $sp, $sp, -0x18
    sw      $ra, 0x14($sp)
    sw      $s0, 0x10($sp)
    move    $s0, $a0

    jal     0x80038BE4
    addiu   $a0, $s0, 0x1B00
    jal     0x80038BE4
    addiu   $a0, $s0, 0x1B80
    jal     0x80038BE4
    addiu   $a0, $s0, 0x2080
    jal     0x80038BE4
    addiu   $a0, $s0, 0x2100

    lw      $ra, 0x14($sp)
    lw      $s0, 0x10($sp)
    jr      $ra
    addiu   $sp, $sp, 0x18

.org 0x800A0A2C
select_name_slot_position:
    lui     $v0, 0x8006
    lhu     $v0, 0x1024($v0)
    nop
    addiu   $v0, $v0, -0x30
    sll     $v0, $v0, 1

    ; State 16 is the shared confirmation-return animation.  The persistent
    ; input-kind byte, not the transient state number, tells Japanese 4+4
    ; input from the untouched Roman-name form while that animation runs.
    lui     $v1, 0x8006
    lw      $v1, 0x11F8($v1)
    nop
    lbu     $v1, 0($v1)
    nop
    addiu   $t0, $zero, 2
    bne     $v1, $t0, select_roman_slot_position
    nop

    lui     $v1, 0x800A
    addiu   $v1, $v1, 0x0B80
    jr      $ra
    addu    $v0, $v0, $v1

select_roman_slot_position:
    lui     $v1, 0x800A
    addiu   $v1, $v1, 0x0954
    jr      $ra
    addu    $v0, $v0, $v1

.org 0x800A0A80
update_name_slot:
    ; Use the persistent input kind for the same reason as the position
    ; selector above.  A state<10 test misclassified the state-16 return
    ; animation as Roman input and left its prompt on the wrong slot.
    lui     $t0, 0x8006
    lw      $t0, 0x11F8($t0)
    nop
    lbu     $t0, 0($t0)
    nop
    addiu   $t1, $zero, 2
    beq     $t0, $t1, update_japanese_name_slot
    nop

    ; Recreate the overwritten first instruction and resume the original
    ; 10-slot Roman-name highlighter at 0x8009D1AC.
    lui     $v0, 0x8006
    j       0x8009D1AC
    nop

update_japanese_name_slot:
    lui     $v0, 0x8006
    lhu     $v0, 0x1024($v0)
    nop
    addiu   $v0, $v0, -0x30

    lui     $v1, 0x8006
    lw      $v1, 0x1164($v1)
    nop
    lbu     $v1, 0($v1)
    nop
    sltiu   $t0, $v1, 4
    bnez    $t0, compare_japanese_name_slot
    nop

    lui     $v1, 0x8006
    lw      $v1, 0x1180($v1)
    nop
    lbu     $v1, 0($v1)
    nop
    sltiu   $t0, $v1, 4
    bnez    $t0, given_name_slot_in_range
    nop
    addiu   $v1, $zero, 3

given_name_slot_in_range:
    addiu   $v1, $v1, 4

compare_japanese_name_slot:
    bne     $v0, $v1, store_name_slot_frame
    addiu   $t0, $zero, 0x20
    addiu   $t0, $zero, 0x21

store_name_slot_frame:
    lui     $v0, 0x8006
    lw      $v1, 0x115C($v0)
    jr      $ra
    sb      $t0, 0x24($v1)

.org 0x800A0B80
japanese_name_slot_positions:
    .dh 153, 167, 181, 195
    .dh 214, 228, 242, 256

.close
