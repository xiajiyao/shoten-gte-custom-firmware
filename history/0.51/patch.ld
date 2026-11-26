ENTRY(patch_reset_entry)
MEMORY { PATCH (rx) : ORIGIN = 0x08024000, LENGTH = 0x18000 }
SECTIONS {
  .text : { KEEP(*(.patch_entries)) *(.text*) *(.rodata*) } > PATCH
  /DISCARD/ : { *(.comment*) *(.ARM.exidx*) *(.ARM.extab*) *(.eh_frame*) }
  .data : { *(.data*) } > PATCH
  .bss : { *(.bss*) *(COMMON) } > PATCH
  ASSERT(SIZEOF(.data) == 0, "patch must not contain initialised writable data")
  ASSERT(SIZEOF(.bss) == 0, "patch uses only its explicit reserved RAM area")
}
