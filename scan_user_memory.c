#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        printf("Usage: %s <pid>\n", argv[0]);
        return 1;
    }
    pid_t pid = atoi(argv[1]);
    mach_port_t task = 0;
    kern_return_t kr = task_for_pid(mach_task_self(), pid, &task);
    if (kr != KERN_SUCCESS) {
        printf("task_for_pid failed: %d\n", kr);
        return 1;
    }
    printf("[+] Successfully attached to task port: %d\n", task);

    mach_vm_address_t address = 0;
    mach_vm_size_t size = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object_name;

    const char *target_utf8 = "叶诗雅";
    size_t target_len = strlen(target_utf8);

    int found_count = 0;

    while (1) {
        kr = mach_vm_region(task, &address, &size, VM_REGION_BASIC_INFO_64,
                            (vm_region_info_t)&info, &count, &object_name);
        if (kr != KERN_SUCCESS) break;

        if ((info.protection & VM_PROT_READ) && !(info.protection & VM_PROT_EXECUTE)) {
            mach_vm_size_t chunk_sz = 4 * 1024 * 1024;
            for (mach_vm_address_t offset = 0; offset < size; offset += chunk_sz) {
                mach_vm_size_t read_sz = (size - offset < chunk_sz) ? (size - offset) : chunk_sz;
                vm_offset_t buffer = 0;
                mach_msg_type_number_t bytes_read = 0;

                kr = mach_vm_read(task, address + offset, read_sz, &buffer, &bytes_read);
                if (kr == KERN_SUCCESS && bytes_read >= target_len) {
                    unsigned char *buf = (unsigned char *)buffer;
                    for (mach_msg_type_number_t i = 0; i <= bytes_read - target_len; i++) {
                        if (memcmp(buf + i, target_utf8, target_len) == 0 ||
                            (i <= bytes_read - 7 && memcmp(buf + i, "Sabrina", 7) == 0)) {
                            found_count++;
                            printf("\n🎉 [MATCH #%d] Found at 0x%llx:\n", found_count, address + offset + i);
                            
                            // Print surrounding 256 bytes in hex and ascii
                            size_t start = (i > 128) ? (i - 128) : 0;
                            size_t end = (i + 256 < bytes_read) ? (i + 256) : bytes_read;
                            
                            printf("--- Context (ASCII) ---\n");
                            for (size_t k = start; k < end; k++) {
                                unsigned char c = buf[k];
                                if (c >= 32 && c <= 126) putchar(c);
                                else if (c >= 0x80) putchar(c);
                                else putchar(' ');
                            }
                            printf("\n-----------------------\n");
                        }
                    }
                    vm_deallocate(mach_task_self(), buffer, bytes_read);
                }
            }
        }
        address += size;
    }

    printf("\nTotal occurrences found in memory: %d\n", found_count);
    return 0;
}
