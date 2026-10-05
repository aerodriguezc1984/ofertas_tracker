# tests/test_avisos.py
import json

import pytest

from avisos.archivo import NotificadorArchivo
from avisos.base import redactar
from avisos.telegram import EnvioFallido, NotificadorTelegram, TelegramMalConfigurado
from fuentes.base import Captura
from nucleo.evaluador import Veredicto

CAPTURA = Captura(
    tienda="paris", sku_externo="S1", titulo="Notebook Lenovo",
    url="https://www.paris.cl/n-S1.html", precio_internet=89990, precio_normal=129990,
)
VEREDICTO = Veredicto(regla="precio_maximo", precio=89990, motivo="por debajo de tu tope")


def test_el_mensaje_lleva_lo_imprescindible():
    texto = redactar(CAPTURA, VEREDICTO)
    assert "Notebook Lenovo" in texto
    assert "89.990" in texto          # formato chileno, con punto de miles
    assert "paris" in texto.lower()
    assert CAPTURA.url in texto


def test_el_notificador_de_archivo_escribe_una_linea_json(tmp_path):
    ruta = tmp_path / "alertas.jsonl"
    NotificadorArchivo(ruta).enviar(CAPTURA, VEREDICTO)
    NotificadorArchivo(ruta).enviar(CAPTURA, VEREDICTO)

    lineas = ruta.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 2
    registro = json.loads(lineas[0])
    assert registro["precio"] == 89990
    assert registro["url"] == CAPTURA.url


def test_telegram_sin_token_falla_al_construirse():
    """Mejor estallar al arrancar que a mitad del ciclo."""
    with pytest.raises(TelegramMalConfigurado):
        NotificadorTelegram(token="", chat_id="123")


def test_telegram_envia_el_mensaje():
    enviados = []

    class SesionFalsa:
        def post(self, url, json=None, timeout=None):
            enviados.append((url, json))

            class R:
                status_code = 200

            return R()

    NotificadorTelegram("secreto", "123", sesion=SesionFalsa()).enviar(CAPTURA, VEREDICTO)
    url, cuerpo = enviados[0]
    assert url.endswith("/sendMessage")
    assert cuerpo["chat_id"] == "123"
    assert "Notebook Lenovo" in cuerpo["text"]


def test_telegram_no_filtra_el_token_en_el_error():
    class SesionFalsa:
        def post(self, url, json=None, timeout=None):
            class R:
                status_code = 401

            return R()

    notificador = NotificadorTelegram("SECRETO-QUE-NO-DEBE-SALIR", "123", sesion=SesionFalsa())
    with pytest.raises(EnvioFallido) as error:
        notificador.enviar(CAPTURA, VEREDICTO)
    assert "SECRETO-QUE-NO-DEBE-SALIR" not in str(error.value)
