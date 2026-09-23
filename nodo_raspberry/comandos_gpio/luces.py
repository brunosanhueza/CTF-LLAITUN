import logging

logger = logging.getLogger(__name__)

LED_NORMAL_PIN = 17
LED_ALERTA_PIN = 27
LED_OVERFLOW_PIN = 22

_led_normal = None
_led_alerta = None
_led_overflow = None
GPIO_ACTIVO = False

try:
    from gpiozero import LED
    _led_normal = LED(LED_NORMAL_PIN)
    _led_alerta = LED(LED_ALERTA_PIN)
    _led_overflow = LED(LED_OVERFLOW_PIN)
    GPIO_ACTIVO = True
except Exception:
    GPIO_ACTIVO = False


def actualizar_luces(estado: str):
    if not GPIO_ACTIVO:
        return

    try:
        if estado == "NORMAL" or estado == "LLENANDO":
            if _led_normal: _led_normal.on()
            if _led_alerta: _led_alerta.off()
            if _led_overflow: _led_overflow.off()
        elif estado == "LIMITE_ALCANZADO" or estado == "OVERRIDE_ACTIVO":
            if _led_normal: _led_normal.off()
            if _led_alerta: _led_alerta.on()
            if _led_overflow: _led_overflow.off()
        elif estado == "INUNDACION_CRITICA":
            if _led_normal: _led_normal.off()
            if _led_alerta: _led_alerta.off()
            if _led_overflow: _led_overflow.on()
    except Exception as e:
        logger.error(f"Error luces: {e}")
