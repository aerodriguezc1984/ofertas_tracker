"""Notificador por Telegram. El token nunca aparece en logs ni en errores."""

import requests

from avisos.base import redactar
from fuentes.base import Captura
from nucleo.evaluador import Veredicto


class TelegramMalConfigurado(Exception):
    """Falta el token o el chat. Se detecta al arrancar, no a mitad del ciclo."""


class EnvioFallido(Exception):
    """Telegram rechazó el mensaje. El texto del error no lleva el token."""


class NotificadorTelegram:
    def __init__(self, token: str, chat_id: str, sesion=None) -> None:
        if not token or not chat_id:
            raise TelegramMalConfigurado(
                "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el .env"
            )
        self._token = token
        self._chat_id = chat_id
        self._sesion = sesion if sesion is not None else requests.Session()

    def enviar(self, captura: Captura, veredicto: Veredicto) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        cuerpo = {
            "chat_id": self._chat_id,
            "text": redactar(captura, veredicto),
            "disable_web_page_preview": False,
        }

        tipo_de_fallo = None
        try:
            respuesta = self._sesion.post(url, json=cuerpo, timeout=30)
        except Exception as error:
            tipo_de_fallo = type(error).__name__
        if tipo_de_fallo is not None:
            # El texto (y la excepción encadenada) de las excepciones de
            # requests incluye la URL, y la URL lleva el token incrustado.
            # Se relanza ya fuera del bloque except, cuando Python ya no
            # tiene una excepción "en curso" que encadenar: así el error
            # nuevo no lleva ni __cause__ ni __context__, y el original no
            # puede aparecer ni en un log ni en una traza.
            raise EnvioFallido(f"No se pudo contactar con Telegram ({tipo_de_fallo})")
        if respuesta.status_code != 200:
            # Sin la URL en el mensaje: lleva el token incrustado.
            raise EnvioFallido(f"Telegram respondió {respuesta.status_code}")
