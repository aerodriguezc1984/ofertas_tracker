import pytest
import requests

from fuentes.transporte import TiendaBloqueada, crear_transporte


class RespuestaFalsa:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class SesionFalsa:
    """Devuelve las respuestas programadas, una por llamada, y apunta las URLs."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def test_devuelve_el_cuerpo_cuando_responde_bien():
    sesion = SesionFalsa([RespuestaFalsa(200, "<html>ok</html>")])
    traer = crear_transporte(sesion=sesion, pausa=None, dormir=lambda _: None)
    assert traer("https://www.paris.cl/x.html") == "<html>ok</html>"


def test_reintenta_ante_un_500_y_acaba_bien():
    sesion = SesionFalsa([RespuestaFalsa(500), RespuestaFalsa(200, "ok")])
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=lambda _: None)
    assert traer("https://www.paris.cl/x.html") == "ok"
    assert len(sesion.urls) == 2


def test_agotados_los_reintentos_avisa_de_bloqueo():
    sesion = SesionFalsa([RespuestaFalsa(429)] * 3)
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=lambda _: None)
    with pytest.raises(TiendaBloqueada):
        traer("https://www.paris.cl/x.html")


def test_un_404_no_se_reintenta():
    """Un recurso que no existe no mejora por insistir."""
    sesion = SesionFalsa([RespuestaFalsa(404)])
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=lambda _: None)
    with pytest.raises(TiendaBloqueada):
        traer("https://www.paris.cl/x.html")
    assert len(sesion.urls) == 1


def test_un_error_de_red_se_reintenta_y_no_pierde_lo_ya_obtenido():
    """La spec: fallo de red se reintenta según configuración, no se propaga crudo."""
    sesion = SesionFalsa(
        [requests.ConnectionError("sin conexión"), requests.ConnectionError("sin conexión"),
         RespuestaFalsa(200, "ok")]
    )
    esperas = []
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=esperas.append)
    assert traer("https://www.paris.cl/x.html") == "ok"
    assert len(esperas) == 2


def test_la_espera_crece_entre_intentos():
    esperas = []
    sesion = SesionFalsa(
        [RespuestaFalsa(500), RespuestaFalsa(500), RespuestaFalsa(200, "ok")]
    )
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=esperas.append)
    traer("https://www.paris.cl/x.html")
    assert len(esperas) == 2
    assert esperas[1] > esperas[0]
