"""Fuente de api.solotodo.com.

SoloTodo no es una tienda sino un agregador con API REST pública: cubre cientos
de tiendas chilenas y, además del precio, da el identificador del mismo artículo
en todas ellas.

No hereda de `FuenteJsonLd` porque no lee HTML. `Fuente` es un protocolo, no una
jerarquía, y esta fuente lo cumple por su cuenta.
"""

import json
import logging
import re
import unicodedata
from urllib.parse import urlencode

from fuentes.base import Captura, Referencia, Transporte
from fuentes.transporte import TiendaBloqueada
from nucleo.comparacion import OfertaAjena
from nucleo.normalizador import a_entero

registro = logging.getLogger(__name__)

_NO_ALFANUM = re.compile(r"[^a-z0-9]+")


def identificador_de_tienda(nombre: str) -> str:
    """`AbcDin` -> `abcdin`; `PC Factory` -> `pc-factory`.

    El identificador sale del nombre y no del número que SoloTodo le da, para
    que la configuración se pueda leer. El precio es que un cambio de nombre en
    su catálogo duplicaría los productos de esa tienda; está asumido en la spec.
    """
    sin_acentos = (
        unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii")
    )
    return _NO_ALFANUM.sub("-", sin_acentos.lower()).strip("-")


def captura_de_entidad(
    entidad: dict, tiendas: dict[int, str], excluidas: set[str]
) -> Captura | None:
    """La Captura de una entidad, o None si no hay nada utilizable que guardar.

    `tienda` es la tienda REAL: el producto está en AbcDin, y SoloTodo es solo
    quien nos lo cuenta.

    `excluidas` debe traer identificadores ya normalizados, en la misma forma
    que devuelve `identificador_de_tienda` (p. ej. `"pc-factory"`), no nombres
    de tienda en crudo: si no, la comparación nunca coincide y una tienda que
    ya cubrimos en directo deja de excluirse sin que nada avise.
    """
    registro_activo = entidad.get("active_registry")
    if not registro_activo:
        return None   # la tienda ya no lo ofrece

    nombre_tienda = tiendas.get(entidad.get("store"))
    if nombre_tienda is None:
        registro.warning(
            "solotodo: entidad %s de una tienda desconocida (%s)",
            entidad.get("id"),
            entidad.get("store"),
        )
        return None

    tienda = identificador_de_tienda(nombre_tienda)
    if tienda in excluidas:
        return None   # la cubrimos en directo, con más precisión

    interno = a_entero(registro_activo.get("offer_price"))
    sku = str(entidad.get("sku") or "").strip()
    titulo = str(entidad.get("name") or "").strip()
    url = str(entidad.get("external_url") or "").strip()
    # `tienda` entra en la misma guarda que sku/titulo/url: un nombre de tienda
    # sin ningún carácter ASCII alfanumérico normaliza a "", y ese "" nunca
    # coincidiría con `excluidas` y encima mezclaría en una misma identidad
    # (tienda, sku_externo) a dos tiendas distintas que degeneraran igual.
    if interno is None or not sku or not titulo or not url or not tienda:
        registro.warning("solotodo: entidad %s incompleta", entidad.get("id"))
        return None

    producto = entidad.get("product") or {}

    return Captura(
        tienda=tienda,
        sku_externo=sku,
        titulo=titulo,
        url=url,
        precio_internet=interno,
        precio_normal=a_entero(registro_activo.get("normal_price")),
        precio_tarjeta=None,   # SoloTodo no publica precios con tarjeta
        tarjeta=None,
        disponible=bool(registro_activo.get("is_available")),
        ean=str(entidad["ean"]) if entidad.get("ean") else None,
        producto_solotodo=producto.get("id") if isinstance(producto, dict) else None,
    )


class SoloTodo:
    nombre = "solotodo"
    BASE = "https://api.solotodo.com"

    def __init__(self, transporte: Transporte, excluidas=()) -> None:
        self._traer = transporte
        self._excluidas = {identificador_de_tienda(t) for t in excluidas}
        self._tiendas: dict[int, str] | None = None

    def _catalogo(self) -> dict[int, str] | None:
        """Los nombres de las tiendas, pedidos una sola vez.

        Se piden de forma perezosa: un ciclo que no use esta fuente no gasta
        ninguna petición. Devuelve None si la API no responde, y entonces no se
        puede construir la identidad de ninguna captura.
        """
        if self._tiendas is None:
            try:
                crudo = self._traer(f"{self.BASE}/stores/")
            except TiendaBloqueada as error:
                registro.warning("solotodo: no se pudo leer el catálogo (%s)", error)
                return None
            tiendas = {t["id"]: t["name"] for t in json.loads(crudo)}
            if not tiendas:
                # Un catálogo vacío no es un éxito: cachearlo dejaría cada
                # entidad cayendo en «tienda desconocida» el resto del ciclo,
                # apuntando al sitio equivocado (el catálogo, no las
                # entidades). Se trata como el fallo de red: sin caché, para
                # que se reintente en la próxima llamada.
                registro.warning("solotodo: el catálogo de tiendas vino vacío")
                return None
            self._tiendas = tiendas
        return self._tiendas

    def buscar(
        self, termino: str | None, limite: int, categoria: int | None = None
    ) -> list[Captura]:
        """Por palabra clave, por categoría, o por las dos.

        La palabra clave de este agregador NO acota: `search=notebook` devuelve
        8.167 entidades, y las primeras son discos, ratones e impresoras —casa
        por cosas que no son el nombre del producto—. La categoría sí: filtra de
        verdad, y una categoría inexistente devuelve 400 en vez de ignorarse, o
        sea que una errata en la configuración falla ruidosamente.
        """
        tiendas = self._catalogo()
        if tiendas is None:
            return []

        parametros: dict[str, object] = {}
        if termino:
            parametros["search"] = termino
        if categoria is not None:
            parametros["categories"] = categoria
        if not parametros:
            registro.warning("solotodo: una búsqueda sin término ni categoría")
            return []
        parametros["is_active"] = "true"
        consulta = urlencode(parametros)
        url = f"{self.BASE}/entities/?{consulta}"
        try:
            datos = json.loads(self._traer(url))
        except TiendaBloqueada as error:
            registro.warning(
                "solotodo: búsqueda bloqueada (término %r, categoría %s): %s",
                termino, categoria, error,
            )
            return []

        capturas: list[Captura] = []
        # El límite cuenta capturas ÚTILES, no entidades visitadas: la página de
        # resultados ya está descargada entera, así que recorrerla de más no
        # cuesta una petición extra. En `FuenteJsonLd`, en cambio, cada ficha
        # cuesta su propia petición y por eso ahí el corte es previo a pedirla.
        for entidad in datos.get("results") or []:
            if len(capturas) >= limite:
                break
            captura = captura_de_entidad(entidad, tiendas, self._excluidas)
            if captura is not None:
                capturas.append(captura)
        return capturas

    def obtener(self, referencias: list[Referencia]) -> list[Captura]:
        tiendas = self._catalogo()
        if tiendas is None:
            return []

        # Aquí la identidad es el id de entidad que ya va en la URL (p. ej.
        # `.../entities/1379496/`), así que `Referencia.sku_externo` se ignora
        # a propósito; Paris y Falabella sí lo honran porque su URL no lo trae.
        capturas: list[Captura] = []
        for referencia in referencias:
            try:
                entidad = json.loads(self._traer(referencia.url))
            except TiendaBloqueada as error:
                registro.warning(
                    "solotodo: no se pudo leer %s (%s)", referencia.url, error
                )
                continue
            captura = captura_de_entidad(entidad, tiendas, self._excluidas)
            if captura is None:
                registro.warning(
                    "solotodo: sin datos utilizables en %s", referencia.url
                )
                continue
            capturas.append(captura)
        return capturas

    def identidad_de(self, tienda: str, sku: str) -> int | None:
        """El id de producto que el agregador da a (tienda, sku), o None.

        No basta con que la búsqueda devuelva un único resultado: se exige que
        el `sku` de la entidad coincida con el nuestro. Un precio equivocado
        contamina un ciclo; una identidad equivocada contamina todas las
        comparaciones futuras de esa fila.
        """
        tiendas = self._catalogo()
        if tiendas is None:
            return None

        numericos = [
            identificador
            for identificador, nombre in tiendas.items()
            if identificador_de_tienda(nombre) == tienda
        ]
        if not numericos:
            # Una tienda que el agregador no cubre. No es un fallo: hay tiendas
            # nuestras que simplemente no están ahí.
            registro.warning("solotodo: no cubre la tienda %r", tienda)
            return None

        consulta = urlencode({"stores": numericos[0], "search": sku})
        url = f"{self.BASE}/entities/?{consulta}"
        try:
            datos = json.loads(self._traer(url))
        except TiendaBloqueada as error:
            registro.warning(
                "solotodo: identidad bloqueada para %s/%s (%s)", tienda, sku, error
            )
            return None

        for entidad in datos.get("results") or []:
            if str(entidad.get("sku") or "").strip() != sku:
                continue
            producto = entidad.get("product") or {}
            identificador = producto.get("id") if isinstance(producto, dict) else None
            if isinstance(identificador, int):
                return identificador

        registro.warning("solotodo: ninguna entidad de %r con el sku %r", tienda, sku)
        return None

    def ofertas_de(self, producto_solotodo: int) -> list[OfertaAjena]:
        """El precio del mismo artículo en todas las tiendas, en una petición.

        Devuelve también las agotadas: descartarlas es decisión del núcleo, que
        es quien conoce las reglas. Aquí solo se traduce.
        """
        tiendas = self._catalogo()
        if tiendas is None:
            return []

        url = f"{self.BASE}/products/{int(producto_solotodo)}/entities/"
        try:
            datos = json.loads(self._traer(url))
        except TiendaBloqueada as error:
            registro.warning(
                "solotodo: ofertas bloqueadas para el producto %s (%s)",
                producto_solotodo, error,
            )
            return []

        ofertas: list[OfertaAjena] = []
        for entidad in datos if isinstance(datos, list) else []:
            activo = entidad.get("active_registry")
            if not isinstance(activo, dict):
                continue
            precio = a_entero(activo.get("offer_price"))
            if precio is None or precio <= 0:
                continue
            nombre = tiendas.get(entidad.get("store"))
            if nombre is None:
                continue
            enlace = str(entidad.get("external_url") or "").strip()
            if not enlace:
                continue
            ofertas.append(
                OfertaAjena(
                    tienda=identificador_de_tienda(nombre),
                    precio=precio,
                    url=enlace,
                    disponible=bool(activo.get("is_available")),
                )
            )
        return ofertas
