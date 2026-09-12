"""
PicoRobotics.py  --  GrowBot auto-detecting servo driver.

Drop this on the Pico as  PicoRobotics.py . The programs on top all call:
    board = KitronikPicoRobotics()
    board.servoWrite(port, degrees)
    board.release(port)
...and don't care what's underneath. This file picks the driver at boot:

  * CARRIER BOARD (I2C / PCA9685 chip, e.g. Kitronik Robotics @0x6C,
    generic PCA9685 @0x40 on GP8/GP9) -> detected on the I2C bus, driven over I2C.
        [VERIFIED on the Kitronik Robotics Board 5329]
  * DIRECT-WIRE (no chip on the bus) -> servos driven straight off
    GP0 (left leg) / GP1 (right leg) / GP2 (left arm) / GP3 (right arm)
    with hardware PWM.
        [VERIFIED 2026-07-27 on the Waveshare Pico Servo Driver.]

Ports:  1 = left leg, 3 = right leg, 4 = left arm, 5 = right arm
(port 2 is the unused socket on the Kitronik board). CHANNEL_PORT maps
channel ids onto those ports. Pins are firmware truth, not body_config.

Requires channels.py on the chip (same directory).

ADVANCED override (skip auto-detect): set FORCE_DRIVER below, and edit the
I2C pins / addresses or PORT_TO_GPIO for an unusual board.
"""
import machine
import utime
from machine import Pin, PWM

from channels import (
    CHANNEL_PORT,
    GPIO_LEFT_ARM,
    GPIO_LEFT_LEG,
    GPIO_RIGHT_ARM,
    GPIO_RIGHT_LEG,
    PORT_TO_GPIO,
    SERVO_MAX_DEGREES,
    SERVO_MIN_DEGREES,
)

DRIVER_I2C = "i2c"
DRIVER_GPIO = "gpio"
FORCE_DRIVER = None

I2C_BUS_ID = 0
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9
I2C_FREQUENCY_HZ = 100000
KITRONIK_CHIP_ADDRESS = 0x6C
GENERIC_PCA9685_ADDRESS = 0x40
CHIP_ADDRESSES = (KITRONIK_CHIP_ADDRESS, GENERIC_PCA9685_ADDRESS)

SERVO_PWM_FREQUENCY_HZ = 50
PULSE_MINIMUM_MICROSECONDS = 500
PULSE_MAXIMUM_MICROSECONDS = 2500
PWM_DUTY_MAX = 65535
PERIOD_MICROSECONDS = 1_000_000 // SERVO_PWM_FREQUENCY_HZ

PCA9685_SERVO_REGISTER_BASE = 0x08
PCA9685_REGISTER_STRIDE = 4
PCA9685_PRESCALE_BYTES = b"\x79"
PCA9685_MODE1_WAKE_ALLCALL = b"\x01"
PCA9685_FULL_OFF_FLAG = 0x10
PCA9685_GENERAL_CALL_RESET = b"\x06"
PCA9685_PRESCALE_REGISTER = 0xfe
PCA9685_ALL_LED_REGISTERS = (0xfa, 0xfb, 0xfc, 0xfd)
PCA9685_MODE1_REGISTER = 0x00
PCA9685_DEGREES_TO_TICKS = 2.2755
PCA9685_TICKS_OFFSET = 102
I2C_SETTLE_MICROSECONDS = 500


def _clamp_servo_degrees(degrees):
    if degrees < SERVO_MIN_DEGREES:
        return SERVO_MIN_DEGREES
    if degrees > SERVO_MAX_DEGREES:
        return SERVO_MAX_DEGREES
    return degrees


class I2cServoBoard:
    def __init__(self, address):
        self.chip_address = address
        self.i2c = machine.I2C(
            I2C_BUS_ID,
            sda=Pin(I2C_SDA_PIN),
            scl=Pin(I2C_SCL_PIN),
            freq=I2C_FREQUENCY_HZ,
        )
        self.initPCA()

    def initPCA(self):
        self.i2c.writeto(0, PCA9685_GENERAL_CALL_RESET)
        self.i2c.writeto_mem(self.chip_address, PCA9685_PRESCALE_REGISTER, PCA9685_PRESCALE_BYTES)
        for register in PCA9685_ALL_LED_REGISTERS:
            self.i2c.writeto_mem(self.chip_address, register, b"\x00")
        self.i2c.writeto_mem(self.chip_address, PCA9685_MODE1_REGISTER, PCA9685_MODE1_WAKE_ALLCALL)
        utime.sleep_us(I2C_SETTLE_MICROSECONDS)

    def servoWrite(self, servo, degrees):
        degrees = _clamp_servo_degrees(degrees)
        if servo < 1 or servo > 8:
            raise Exception("INVALID SERVO NUMBER")
        register = PCA9685_SERVO_REGISTER_BASE + (servo - 1) * PCA9685_REGISTER_STRIDE
        ticks = int(degrees * PCA9685_DEGREES_TO_TICKS) + PCA9685_TICKS_OFFSET
        self.i2c.writeto_mem(self.chip_address, register, bytes([ticks & 0xFF]))
        self.i2c.writeto_mem(self.chip_address, register + 1, bytes([(ticks >> 8) & 0x01]))

    def release(self, servo):
        register = PCA9685_SERVO_REGISTER_BASE + (servo - 1) * PCA9685_REGISTER_STRIDE
        self.i2c.writeto_mem(self.chip_address, register + 1, bytes([PCA9685_FULL_OFF_FLAG]))


def duty_from_degrees(degrees):
    degrees = _clamp_servo_degrees(degrees)
    pulse_microseconds = (
        PULSE_MINIMUM_MICROSECONDS
        + (PULSE_MAXIMUM_MICROSECONDS - PULSE_MINIMUM_MICROSECONDS) * degrees / SERVO_MAX_DEGREES
    )
    return int(pulse_microseconds / PERIOD_MICROSECONDS * PWM_DUTY_MAX)


class GpioServoBoard:
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


def _detect_chip_address():
    try:
        bus = machine.I2C(
            I2C_BUS_ID,
            sda=Pin(I2C_SDA_PIN),
            scl=Pin(I2C_SCL_PIN),
            freq=I2C_FREQUENCY_HZ,
        )
        found = bus.scan()
        for address in CHIP_ADDRESSES:
            if address in found:
                return address
    except Exception:
        pass
    return None


def KitronikPicoRobotics():
    """Factory: I2C board driver if a servo chip is on the bus, else GPIO."""
    mode = FORCE_DRIVER
    address = None
    if mode is None:
        address = _detect_chip_address()
        mode = DRIVER_I2C if address is not None else DRIVER_GPIO
    elif mode == DRIVER_I2C:
        address = CHIP_ADDRESSES[0]
    if mode == DRIVER_I2C:
        print("PicoRobotics: I2C servo board detected @", hex(address))
        return I2cServoBoard(address)
    print(
        "PicoRobotics: no I2C chip -> direct-wire, GP%d/GP%d = legs, GP%d/GP%d = arms"
        % (GPIO_LEFT_LEG, GPIO_RIGHT_LEG, GPIO_LEFT_ARM, GPIO_RIGHT_ARM)
    )
    return GpioServoBoard()
