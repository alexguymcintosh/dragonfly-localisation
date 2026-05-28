cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(pico_mavlink_bridge C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

pico_sdk_init()

add_executable(pico_mavlink_bridge main.c)

target_link_libraries(pico_mavlink_bridge
    pico_stdlib
    hardware_uart
)

# UART0 is the MAVLink payload link to the Pixhawk -- absolutely must NOT
# carry stdio. Only USB CDC gets stdio.
pico_enable_stdio_usb(pico_mavlink_bridge 1)
pico_enable_stdio_uart(pico_mavlink_bridge 0)

pico_add_extra_outputs(pico_mavlink_bridge)
