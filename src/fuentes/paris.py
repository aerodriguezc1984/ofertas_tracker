"""Fuente de paris.cl: se lee raspando el HTML.

La ficha publica un bloque JSON-LD con nombre, SKU y precio, así que el trabajo
real lo hace el normalizador genérico. Aquí solo vive lo propio de Paris: la
forma de su URL de búsqueda y la de sus enlaces a ficha.
"""

import logging
import re
from urllib.parse import urlencode

from fuentes.base import Captura, Referencia, Transporte
from fuentes.transporte import TiendaBloqueada
from nucleo.normalizador import a_captura

registro = logging.getLogger(__name__)

# Las fichas de Paris son rutas del tipo /slug-con-guiones-SKU.html
_ENLACE_FICHA = re.compile(r'href="(/[a-z0-9][a-z0-9\-]{8,90}\.html)"', re.IGNORECASE)


class Paris:
    nombre = "paris"
    BASE = "https://www.paris.cl"

    def __init__(self, transporte: Transporte) -> None:
        self._traer = transporte

    def obtener(self, referencias: list[Referencia]) -> list[Captura]:
        capturas: list[Captura] = []
        for referencia in referencias:
            try:
                html = self._traer(referencia.url)
            except TiendaBloqueada as error:
                registro.warning("paris: no se pudo leer %s (%s)", referencia.url, error)
                continue

            captura = a_captura(html, referencia.url, self.nombre)
            if captura is None:
                registro.warning("paris: sin datos utilizables en %s", referencia.url)
                continue
            capturas.append(captura)
        return capturas

    def buscar(self, termino: str, limite: int) -> list[Captura]:
        url = f"{self.BASE}/search?{urlencode({'q': termino})}"
        try:
            html = self._traer(url)
        except TiendaBloqueada as error:
            registro.warning("paris: búsqueda bloqueada para %r (%s)", termino, error)
            return []

        vistas: list[str] = []
        for ruta in _ENLACE_FICHA.findall(html):
            completa = self.BASE + ruta
            if completa not in vistas:
                vistas.append(completa)

        referencias = [Referencia(tienda=self.nombre, url=u) for u in vistas[:limite]]
        return self.obtener(referencias)
