"""Andamiaje común de las fuentes que leen JSON-LD.

Lo que se repite de tienda a tienda no es el patrón de enlace sino el bucle: el
salto ante una tienda bloqueada, el descarte de lo que no da datos utilizables,
el deduplicado por URL conservando el orden y el corte por límite. Eso vive
aquí; cada tienda aporta tres ganchos.

No es una jerarquía obligatoria. `Fuente` sigue siendo el protocolo que define
una fuente, y una tienda que no encaje en este molde puede implementarlo por su
cuenta en vez de torcer la base para que quepa.
"""

import logging

from fuentes.base import Candidato, Captura, Referencia, Transporte
from fuentes.transporte import TiendaBloqueada

registro = logging.getLogger(__name__)


class FuenteJsonLd:
    nombre: str = ""
    BASE: str = ""

    def __init__(self, transporte: Transporte) -> None:
        self._traer = transporte

    # --- Los tres ganchos que cada tienda implementa ---

    def url_de_busqueda(self, termino: str) -> str:
        raise NotImplementedError

    def candidatos(self, html: str) -> list[Candidato]:
        """Los productos que anuncia una página de resultados.

        Devuelve todos los que encuentre, en orden y sin deduplicar: de eso se
        encarga `buscar`.
        """
        raise NotImplementedError

    def captura_de_ficha(self, html: str, url: str) -> Captura | None:
        raise NotImplementedError

    # --- Lo común, que ninguna tienda reescribe ---

    def obtener(self, referencias: list[Referencia]) -> list[Captura]:
        capturas: list[Captura] = []
        for referencia in referencias:
            try:
                html = self._traer(referencia.url)
            except TiendaBloqueada as error:
                registro.warning(
                    "%s: no se pudo leer %s (%s)", self.nombre, referencia.url, error
                )
                continue

            captura = self.captura_de_ficha(html, referencia.url)
            if captura is None:
                registro.warning(
                    "%s: sin datos utilizables en %s", self.nombre, referencia.url
                )
                continue
            capturas.append(captura)
        return capturas

    def buscar(self, termino: str, limite: int) -> list[Captura]:
        url = self.url_de_busqueda(termino)
        try:
            html = self._traer(url)
        except TiendaBloqueada as error:
            registro.warning(
                "%s: búsqueda bloqueada para %r (%s)", self.nombre, termino, error
            )
            return []

        vistos: list[str] = []
        elegidos: list[Candidato] = []
        for candidato in self.candidatos(html):
            # El corte va ANTES de aceptar nada: con `limite=0` no se elige
            # ninguno, igual que el antiguo `vistas[:limite]`.
            if len(elegidos) >= limite:
                break
            if candidato.referencia.url in vistos:
                continue
            vistos.append(candidato.referencia.url)
            elegidos.append(candidato)

        # El corte por límite sucede ANTES de pedir ninguna ficha: es lo que
        # hace barata una búsqueda en una tienda que trae 56 productos de golpe.
        capturas: list[Captura] = []
        for candidato in elegidos:
            if candidato.captura is not None:
                capturas.append(candidato.captura)
            else:
                capturas.extend(self.obtener([candidato.referencia]))
        return capturas
