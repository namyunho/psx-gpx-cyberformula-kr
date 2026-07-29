.psx
.open "unit40.bin", 0x80098000

; Unit 40 has a verified zero-filled range at 0x800A09BC..0x800A1800.
; These helpers expand only the Japanese-script player-name form.  The
; Roman-name form keeps the original slot positions and update routine.

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

; The original prompt display frames are 44 pixels wide
; (3 * 14-pixel glyphs + 2).  Widen both to 58 pixels and move only the
; surname frame 14 pixels left so the 4+4 fields remain separated.
.org 0x8009EA22
    .db 58
.org 0x8009EA24
    .dh 10
.org 0x8009EA3A
    .db 58

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

    lui     $v1, 0x8006
    lw      $v1, 0x0FD4($v1)
    nop
    lw      $v1, 0($v1)
    nop
    sltiu   $v1, $v1, 10
    beqz    $v1, select_roman_slot_position
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
    lui     $t0, 0x8006
    lw      $t0, 0x0FD4($t0)
    nop
    lw      $t0, 0($t0)
    nop
    sltiu   $t0, $t0, 10
    bnez    $t0, update_japanese_name_slot
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
    .dh 150, 164, 178, 192
    .dh 216, 230, 244, 258

.close
