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
        respuesta = self._sesion.post(
            url,
            json={
                "chat_id": self._chat_id,
                "text": redactar(captura, veredicto),
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
        if respuesta.status_code != 200:
            # Sin la URL en el mensaje: lleva el token incrustado.
            raise EnvioFallido(f"Telegram respondió {respuesta.status_code}")
