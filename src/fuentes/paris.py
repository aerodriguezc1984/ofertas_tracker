"""Fuente de paris.cl: se lee raspando el HTML.

La ficha publica un bloque JSON-LD con nombre, SKU y precio, así que el trabajo
real lo hace el normalizador genérico y el andamiaje lo hace la fuente base.
Aquí solo vive lo propio de Paris: la forma de su URL de búsqueda y la de sus
enlaces a ficha.
"""

import re
from urllib.parse import urlencode

from fuentes.base import Candidato, Captura, Referencia
from fuentes.jsonld import FuenteJsonLd
from nucleo.normalizador import a_captura

# Las fichas de Paris son rutas del tipo /slug-con-guiones-SKU.html
_ENLACE_FICHA = re.compile(r'href="(/[a-z0-9][a-z0-9\-]{8,90}\.html)"', re.IGNORECASE)


class Paris(FuenteJsonLd):
    nombre = "paris"
    BASE = "https://www.paris.cl"

    def url_de_busqueda(self, termino: str) -> str:
        return f"{self.BASE}/search?{urlencode({'q': termino})}"

    def candidatos(self, html: str) -> list[Candidato]:
        """Paris anuncia enlaces, no datos: hay que seguir cada ficha."""
        return [
            Candidato(referencia=Referencia(tienda=self.nombre, url=self.BASE + ruta))
            for ruta in _ENLACE_FICHA.findall(html)
        ]

    def captura_de_ficha(self, html: str, url: str) -> Captura | None:
        return a_captura(html, url, self.nombre)
