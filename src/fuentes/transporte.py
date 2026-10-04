"""El transporte HTTP real: una función URL -> texto, con reintentos.

Se aísla aquí para que las fuentes sean probables sin red y para que el ritmo
lento y la cabecera honesta estén en un solo sitio.
"""

import logging
import random
import time

import requests

from fuentes.base import Transporte

registro = logging.getLogger(__name__)

# Identificarse de verdad: ni suplantamos un navegador ni rotamos agentes.
AGENTE = "rastreador-ofertas-personal/0.1 (uso personal, ritmo bajo)"

REINTENTABLES = {429, 500, 502, 503, 504}


class TiendaBloqueada(Exception):
    """La tienda no quiere darnos la página. Se registra y se sigue con otras."""


def crear_transporte(
    sesion=None,
    reintentos: int = 3,
    pausa: tuple[float, float] | None = (2.0, 5.0),
    dormir=time.sleep,
) -> Transporte:
    sesion = sesion if sesion is not None else requests.Session()

    def traer(url: str) -> str:
        if pausa:
            dormir(random.uniform(*pausa))

        for intento in range(1, reintentos + 1):
            respuesta = sesion.get(
                url,
                headers={"User-Agent": AGENTE, "Accept-Language": "es-CL,es;q=0.9"},
                timeout=30,
            )
            if respuesta.status_code == 200:
                return respuesta.text

            if respuesta.status_code not in REINTENTABLES:
                raise TiendaBloqueada(f"{url} respondió {respuesta.status_code}")

            if intento < reintentos:
                espera = 2.0**intento
                registro.warning(
                    "%s respondió %s; reintento %s de %s en %.0f s",
                    url, respuesta.status_code, intento, reintentos, espera,
                )
                dormir(espera)

        raise TiendaBloqueada(f"{url} agotó los {reintentos} intentos")

    return traer
