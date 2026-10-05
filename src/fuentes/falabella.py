"""Fuente de falabella.com.

Dos cosas la separan de Paris, y las dos están aquí y no en la capa genérica:
su búsqueda devuelve los productos dentro de un `ItemList` —una petición en vez
de una por resultado—, y sus precios vienen sin etiquetar, así que cuál es el de
tarjeta se infiere del orden y se confirma después contra la ficha.
"""

import re
from urllib.parse import urlencode

from fuentes.base import Candidato, Captura, Referencia
from fuentes.jsonld import FuenteJsonLd
from nucleo.normalizador import a_entero, productos_ld_json

# Las fichas son /falabella-cl/product/<id>/<slug>/<id>
_SKU_EN_URL = re.compile(r"/product/(\d+)/")


class Falabella(FuenteJsonLd):
    nombre = "falabella"
    BASE = "https://www.falabella.com/falabella-cl"
    TARJETA = "CMR"

    def url_de_busqueda(self, termino: str) -> str:
        return f"{self.BASE}/search?{urlencode({'Ntt': termino})}"

    def candidatos(self, html: str) -> list[Candidato]:
        candidatos: list[Candidato] = []
        for producto in productos_ld_json(html):
            url = str(producto.get("url") or "").strip()
            sku = self._sku_de(url)
            if not sku:
                continue
            captura = self._captura_inferida(producto, url, sku)
            if captura is None:
                continue
            candidatos.append(
                Candidato(
                    referencia=Referencia(tienda=self.nombre, url=url, sku_externo=sku),
                    captura=captura,
                )
            )
        return candidatos

    @staticmethod
    def _sku_de(url: str) -> str | None:
        encontrado = _SKU_EN_URL.search(url)
        return encontrado.group(1) if encontrado else None

    def _captura_inferida(self, producto: dict, url: str, sku: str) -> Captura | None:
        """Qué precio es cuál, deducido del orden en que vienen.

        La búsqueda lista las ofertas sin decir cuál es cuál. Ordenadas de
        menor a mayor: con tres, la más barata es la de tarjeta y la más cara
        la tachada; con dos, no hay precio de tarjeta; con una, es el único
        precio y no hay nada tachado. La captura sale marcada como NO
        etiquetada y el orquestador la confirma antes de alertar.
        """
        ofertas = producto.get("offers") or []
        if isinstance(ofertas, dict):
            ofertas = [ofertas]
        precios = sorted(
            p
            for p in (a_entero(o.get("price")) for o in ofertas if isinstance(o, dict))
            if p is not None
        )

        if len(precios) >= 3:
            tarjeta, internet, normal = precios[0], precios[1], precios[-1]
        elif len(precios) == 2:
            tarjeta, internet, normal = None, precios[0], precios[1]
        elif len(precios) == 1:
            tarjeta, internet, normal = None, precios[0], None
        else:
            return None

        titulo = str(producto.get("name") or "").strip()
        if not titulo:
            return None

        imagen = producto.get("image")
        if isinstance(imagen, list):
            imagen = imagen[0] if imagen else None

        return Captura(
            tienda=self.nombre,
            sku_externo=sku,
            titulo=titulo,
            url=url,
            precio_internet=internet,
            precio_normal=normal,
            precio_tarjeta=tarjeta,
            tarjeta=self.TARJETA if tarjeta is not None else None,
            imagen_url=imagen if isinstance(imagen, str) else None,
            precios_etiquetados=False,
        )

    def captura_de_ficha(self, html: str, url: str) -> Captura | None:
        raise NotImplementedError("llega en la Tarea 5")
