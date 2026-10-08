"""Fuente de falabella.com.

Dos cosas la separan de Paris, y las dos están aquí y no en la capa genérica:
su búsqueda devuelve los productos dentro de un `ItemList` —una petición en vez
de una por resultado—, y sus precios vienen sin etiquetar, así que cuál es el de
tarjeta se infiere del orden y se confirma después contra la ficha.
"""

import html as htmlmod
import re
from dataclasses import replace
from urllib.parse import urlencode

from fuentes.base import Candidato, Captura, Referencia
from fuentes.jsonld import FuenteJsonLd
from nucleo.normalizador import a_entero, captura_de_objeto, productos_ld_json, texto

# Las fichas son /falabella-cl/product/<id>/<slug>/<id>
_SKU_EN_URL = re.compile(r"/product/(\d+)/")

# Dentro del JSON incrustado de la ficha, cada precio dice de qué tipo es.
# `eventPrice` es el mismo precio que `internetPrice` —el que paga cualquiera—
# pero etiquetado así mientras dura una promoción. Los dos no conviven: la ficha
# trae uno o el otro.
_PRECIO_ETIQUETADO = re.compile(
    r'"type":"(cmrPrice|internetPrice|eventPrice|normalPrice)","price":\["([\d.]+)"\]'
)

# El bloque de precios de un producto va seguido de sus identificadores. Se
# aceptan los dos porque `sellerSkuId` no siempre es un sku: en las fichas de
# vendedor trae el nombre del artículo ("MacBook Air 2017 i5 128G Silver").
_ANCLA = '"(?:offeringId|sellerSkuId)":"{sku}"' 


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

        titulo = texto(producto.get("name"))
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
        """El JSON-LD da título y stock; el JSON incrustado, los tres precios.

        El bloque JSON-LD llega VÁLIDO y desescaparlo lo rompería: su nombre
        lleva un `&quot;` dentro de la cadena. Por eso se analiza el HTML crudo.

        El desescapado que sí se aplica abajo es defensivo, no imprescindible:
        hoy la carga de precios de la ficha llega sin escapar y el patrón casa
        igual con o sin él. Se mantiene porque Falabella sí escapa el JSON-LD de
        su página de búsqueda, y una página que cambiara de criterio dejaría de
        capturarse en silencio.

        El sku se fuerza al id de la URL, que es como se descubrió el producto
        en la búsqueda. El del JSON-LD no sirve: ver `_bloque_de_esta_ficha`.
        """
        esperado = self._sku_de(url)
        if esperado is None:
            return None

        objeto = self._bloque_de_esta_ficha(html, url)
        if objeto is None:
            return None

        base = captura_de_objeto(objeto, url, self.nombre)
        if base is None:
            return None

        # Dos candidatos: el id de la URL y el sku que declara el JSON-LD. En las
        # fichas con variantes el bloque lleva el primero; en las de vendedor,
        # donde no hay un bloque por variante, lleva el segundo.
        etiquetados = self._precios_anclados(
            htmlmod.unescape(html), (esperado, base.sku_externo)
        )
        internet = etiquetados.get("internetPrice") or etiquetados.get("eventPrice")
        if internet is None:
            return None

        tarjeta = etiquetados.get("cmrPrice")
        return replace(
            base,
            sku_externo=esperado,
            precio_internet=internet,
            precio_normal=etiquetados.get("normalPrice"),
            precio_tarjeta=tarjeta,
            tarjeta=self.TARJETA if tarjeta is not None else None,
            precios_etiquetados=True,
        )

    @staticmethod
    def _bloque_de_esta_ficha(html: str, url: str) -> dict | None:
        """El bloque JSON-LD que dice pertenecer a ESTA ficha.

        No vale quedarse con el primer Product de la página: los carruseles
        publican los suyos, y usar uno guardaría el precio de otro artículo bajo
        la URL vigilada. No falla: miente.

        Y tampoco vale comparar el sku, que es lo que se hacía antes. Falabella
        publica en la ficha la **variante por defecto**, cuyo sku no es el id
        que va en la URL: `/product/80725439/...` declara `sku: 80725441`. Esa
        comparación empezó a rechazar todas las fichas de productos con
        variantes, y con ellas la confirmación de precios de la tienda entera.

        Lo que sí identifica al bloque es su `@id`: vale la URL pedida, a veces
        con la variante añadida al final.
        """
        pedida = url.rstrip("/")
        for objeto in productos_ld_json(html, incluir_listas=False):
            suyo = str(objeto.get("@id") or objeto.get("url") or "").rstrip("/")
            if suyo.startswith(pedida):
                return objeto
        return None

    @staticmethod
    def _precios_anclados(texto: str, skus: tuple[str, ...]) -> dict[str, int]:
        """Los precios DEL producto, no los del carrusel de al lado.

        Una ficha trae varias listas `prices`. Buscar hacia delante desde la
        primera captura la de una promoción, que es de otro producto. Así que
        se ancla al identificador que toca y se retrocede hasta el `"prices":[`
        más cercano: esa es la lista del producto.

        Los `skus` se prueban EN ORDEN, agotando cada uno antes de pasar al
        siguiente: en una ficha con variantes todas llevan su propio bloque, y
        el que vale es el de la variante que el usuario vigila —el id de su
        URL—, no el que la página traiga primero.
        """
        for sku in skus:
            if not sku:
                continue
            ancla = _ANCLA.format(sku=re.escape(sku))
            for encontrado in re.finditer(ancla, texto):
                inicio = texto.rfind('"prices":[', 0, encontrado.start())
                if inicio == -1:
                    continue
                pares = _PRECIO_ETIQUETADO.findall(texto[inicio : encontrado.start()])
                if pares:
                    return {
                        tipo: valor
                        for tipo, valor in ((t, a_entero(v)) for t, v in pares)
                        if valor is not None
                    }
        return {}
