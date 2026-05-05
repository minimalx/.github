#include <stdio.h>
#include "app_bootloader_interface.h"

int main(void) {
    printf("MAIN_APP_START=0x%08X\n", EXEC_APP_START_ADDR);
    printf("MAIN_APP_END=0x%08X\n",   EXEC_APP_START_ADDR + APP_FLASH_SIZE);
    printf("MAIN_SIG_START=0x%08X\n", APP_SIG_START_ADDR);
    printf("MAIN_SIG_END=0x%08X\n",   APP_SIG_END_ADDR);
    printf("MAIN_CRC_ADDR=0x%08X\n",  APP_CRC_ADDR);
    printf("BL_APP_START=0x%08X\n",   BOOTLOADER_START_ADDR);
    printf("BL_APP_END=0x%08X\n",     BOOTLOADER_START_ADDR + BOOT_FLASH_SIZE);
    printf("BL_SIG_START=0x%08X\n",   BOOT_SIG_START_ADDR);
    printf("BL_SIG_END=0x%08X\n",     BOOT_SIG_END_ADDR);
    printf("BL_CRC_ADDR=0x%08X\n",    BOOT_CRC_ADDR);
    return 0;
}
