"""
PicoRobotics.py — BARE-PICO drop-in (NO Kitronik board needed).

Copy this onto the Pico AS  PicoRobotics.py  and the rest of the firmware
runs unchanged. Instead of the Kitronik I2C servo chip, it drives SG90/MG90
servos straight off GPIO using the RP2350 hardware PWM.

    board = KitronikPicoRobotics()
    board.servoWrite(port, degrees)
    board.release(port)

Requires channels.py on the chip (same directory).

WIRING — each servo has 3 wires (signal / power / ground):
    signal (orange/yellow) -> the GPIO in PORT_TO_GPIO
    power  (red)           -> the battery + rail (see POWER)
    ground (brown/black)   -> GND  (shared with the Pico)

POWER — SG90/MG90 are happy on a raw 1S LiPo (~3.7-4.2V). Servos pull current
from the BATTERY rail, never from a logic pin / 3V3. Always tie servo grounds
to Pico ground.
"""
from machine import Pin, PWM

from channels import (
    CHANNEL_PORT,
    PORT_TO_GPIO,
    SERVO_MAX_DEGREES,
    SERVO_MIN_DEGREES,
)

SERVO_PWM_FREQUENCY_HZ = 50
PULSE_MINIMUM_MICROSECONDS = 500
PULSE_MAXIMUM_MICROSECONDS = 2500
PWM_DUTY_MAX = 65535
PERIOD_MICROSECONDS = 1_000_000 // SERVO_PWM_FREQUENCY_HZ


def duty_from_degrees(degrees):
    if degrees < SERVO_MIN_DEGREES:
        degrees = SERVO_MIN_DEGREES
    elif degrees > SERVO_MAX_DEGREES:
        degrees = SERVO_MAX_DEGREES
    pulse_microseconds = (
        PULSE_MINIMUM_MICROSECONDS
        + (PULSE_MAXIMUM_MICROSECONDS - PULSE_MINIMUM_MICROSECONDS) * degrees / SERVO_MAX_DEGREES
    )
    return int(pulse_microseconds / PERIOD_MICROSECONDS * PWM_DUTY_MAX)


class KitronikPicoRobotics:
    def __init__(self):
        self.pwm = {}
        for port, gpio_pin in PORT_TO_GPIO.items():
            pulse = PWM(Pin(gpio_pin))
            pulse.freq(SERVO_PWM_FREQUENCY_HZ)
            pulse.duty_u16(0)
            self.pwm[port] = pulse

    def servoWrite(self, port, degrees):
        pulse = self.pwm.get(port)
        if pulse:
            pulse.duty_u16(duty_from_degrees(degrees))

    def release(self, port):
        pulse = self.pwm.get(port)
        if pulse:
            pulse.duty_u16(0)
