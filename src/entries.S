.syntax unified
.cpu cortex-m4
.thumb
.section .patch_entries,"ax",%progbits
.balign 4
.global patch_reset_entry
.thumb_func
patch_reset_entry:
  ldr r0, =0x20001000
  ldr r2, =0x20001800
  movs r1, #0
1:
  str r1, [r0], #4
  cmp r0, r2
  blo 1b
  ldr r0, =0x08020269
  bx r0

.balign 4
.global patch_dispatch_entry
.thumb_func
patch_dispatch_entry:
  push {r0-r3,r12,lr}
  bl patch_dispatch
  cmp r0, #0
  beq 2f
  pop {r0-r3,r12,pc}
2:
  pop {r0-r3,r12,lr}
  /* The eight replaced bytes, with the PC-relative load made explicit. */
  push {r3-r7,lr}
  ldr r0, =0x20000590
  ldrb r7, [r0,#5]
  ldrb r6, [r0,#6]
  ldr r12, =0x08020b6d
  bx r12

.balign 4
.global patch_prepare_entry
.thumb_func
patch_prepare_entry:
  push {r0-r3,r12,lr}
  bl patch_prepare
  cmp r0, #0
  beq 3f
  pop {r0-r3,r12,pc}
3:
  pop {r0-r3,r12,lr}
  push {r3-r5,lr}
  mov r4, r0
  mov r5, r1
  cmp r4, #11
  ldr r12, =0x080221bd
  bx r12

.balign 4
.global patch_motion_poll_entry
.thumb_func
patch_motion_poll_entry:
  push {r0-r3,r12,lr}
  bl patch_motion_poll
  pop {r0-r3,r12,lr}
  /* Replay the stock motor-poll entry, preserving its branch condition. */
  push {r4,lr}
  ldr r0, =0x20000442
  ldrb r0, [r0]
  cmp r0, #0
  ldr r12, =0x08021c9d
  bx r12
.ltorg
