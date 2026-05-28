// Transparent UART <-> USB CDC byte bridge for the Dragonfly localisation
// module. UART0 (GP0 TX, GP1 RX) talks to the Pixhawk TELEM2 port; USB CDC
// talks to the host computer running mavros. No parsing -- raw MAVLink2
// bytes are passed through in both directions.
//
// Pixhawk TELEM2 pin 2 (TX) -> Pico GP1 (UART0 RX)
// Pixhawk TELEM2 pin 3 (RX) -> Pico GP0 (UART0 TX)
// Pixhawk TELEM2 pin 6 (GND) -> Pico GND
// Pixhawk TELEM2 pin 1 (5V) -- leave unconnected, Pico is USB-powered.

#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/uart.h"

#define UART_ID        uart0
#define UART_BAUD      115200
#define UART_TX_PIN    0   // GP0 -> Pixhawk TELEM2 pin 3 (FC RX)
#define UART_RX_PIN    1   // GP1 -> Pixhawk TELEM2 pin 2 (FC TX)
#define LED_PIN        PICO_DEFAULT_LED_PIN
#define BLINK_MS       500

int main(void) {
    stdio_init_all();

    uart_init(UART_ID, UART_BAUD);
    gpio_set_function(UART_TX_PIN, GPIO_FUNC_UART);
    gpio_set_function(UART_RX_PIN, GPIO_FUNC_UART);
    uart_set_format(UART_ID, 8, 1, UART_PARITY_NONE);
    uart_set_hw_flow(UART_ID, false, false);
    uart_set_fifo_enabled(UART_ID, true);

    setvbuf(stdout, NULL, _IONBF, 0);

    gpio_init(LED_PIN);
    gpio_set_dir(LED_PIN, GPIO_OUT);
    absolute_time_t next_blink = make_timeout_time_ms(BLINK_MS);
    bool led_state = false;

    while (true) {
        while (uart_is_readable(UART_ID)) {
            putchar_raw(uart_getc(UART_ID));
        }

        int c;
        while ((c = getchar_timeout_us(0)) != PICO_ERROR_TIMEOUT) {
            uart_putc_raw(UART_ID, (uint8_t)c);
        }

        if (time_reached(next_blink)) {
            led_state = !led_state;
            gpio_put(LED_PIN, led_state);
            next_blink = make_timeout_time_ms(BLINK_MS);
        }
    }
}
