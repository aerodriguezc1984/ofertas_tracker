"""Del HTML de una ficha a una Captura, leyendo el JSON-LD de schema.org.

Es el motor genérico: cualquier tienda que publique un bloque
`<script type="application/ld+json">` con un Product se lee con este código, sin
escribir selectores para cada sitio.
"""

import html as htmlmod
import json
import re

from fuentes.base import Captura

_BLOQUE = re.compile(
    r"""<script[^>]*type=["']?application/ld\+json["']?[^>]*>(.*?)</script>""",
    re.DOTALL | re.IGNORECASE,
)


def bloques_ld_json(html: str) -> list[dict]:
    """Todos los objetos JSON-LD de la página. Los ilegibles se descartan."""
    objetos: list[dict] = []
    for crudo in _BLOQUE.findall(html):
        texto = crudo.strip()
        try:
            dato = json.loads(texto)
        except json.JSONDecodeError:
            # Algunas tiendas sirven el bloque escapado con entidades (&quot;).
            # Se desescapa SOLO si el texto literal no era JSON: hacerlo a
            # ciegas rompería un bloque válido cuyo contenido lleve `&quot;`
            # dentro de una cadena, que es lo que publica Falabella.
            try:
                dato = json.loads(htmlmod.unescape(texto))
            except json.JSONDecodeError:
                continue
        for item in dato if isinstance(dato, list) else [dato]:
            if isinstance(item, dict):
                objetos.append(item)
    return objetos


def productos_ld_json(html: str) -> list[dict]:
    """Los `Product` de la página: los de primer nivel y los de un `ItemList`."""
    productos: list[dict] = []
    for objeto in bloques_ld_json(html):
        if _tipo_es(objeto, "Product"):
            productos.append(objeto)
            continue
        if not _tipo_es(objeto, "ItemList"):
            continue
        for elemento in objeto.get("itemListElement") or []:
            if not isinstance(elemento, dict):
                continue
            item = elemento.get("item") if _tipo_es(elemento, "ListItem") else elemento
            if isinstance(item, dict) and _tipo_es(item, "Product"):
                productos.append(item)
    return productos


def _texto(valor) -> str:
    """Un campo de texto del JSON-LD, con sus entidades HTML resueltas.

    El bloque entero no se desescapa (rompería el JSON), pero el contenido de
    un campo sí puede traerlas: Falabella publica `Monitor 27&quot; 4K`.
    """
    return htmlmod.unescape(str(valor or "")).strip()


def a_entero(valor) -> int | None:
    """Pasa el precio a pesos enteros, o None si no hay nada utilizable.

    Las tiendas escriben el precio de todas las formas imaginables: número,
    cadena, con separador de miles. El peso chileno no tiene decimales, así que
    un punto o una coma son separadores de miles salvo que dejen exactamente dos
    cifras detrás, en cuyo caso son decimales y se redondean.
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return int(round(valor))

    texto = str(valor).strip()
    if not texto:
        return None
    if re.fullmatch(r"\d+[.,]\d{2}", texto):       # 229990.00 -> decimales
        return int(round(float(texto.replace(",", "."))))
    solo_digitos = re.sub(r"[^\d]", "", texto)      # 229.990 -> miles
    return int(solo_digitos) if solo_digitos else None


def _tipo_es(objeto: dict, tipo: str) -> bool:
    valor = objeto.get("@type")
    if isinstance(valor, list):
        return tipo in valor
    return valor == tipo


def a_captura(html: str, url: str, tienda: str) -> Captura | None:
    """La Captura de la ficha, o None si ningún bloque da precio y sku utilizables.

    Una página puede traer varios bloques JSON-LD (Falabella, abc.cl publican
    varios Product); que uno no sirva no debe esconder al siguiente, así que un
    bloque inservible se salta con `continue`, nunca con `return`.
    """
    for objeto in productos_ld_json(html):
        ofertas = objeto.get("offers") or {}
        if isinstance(ofertas, list):
            ofertas = ofertas[0] if ofertas else {}

        precio = a_entero(ofertas.get("price"))
        if precio is None:
            continue

        sku = _texto(objeto.get("sku"))
        if not sku:
            # La identidad del producto es (tienda, sku_externo). Sin sku, dos
            # productos distintos colapsarían en la misma fila: tan inventado
            # como un precio en cero.
            continue

        imagen = objeto.get("image")
        if isinstance(imagen, list):
            imagen = imagen[0] if imagen else None

        disponibilidad = str(ofertas.get("availability") or "")
        # Cuando la tienda no declara stock, se asume disponible: lo contrario
        # silenciaría todas las alertas de las tiendas que no publican el dato.
        disponible = "outofstock" not in disponibilidad.lower().replace("/", "")

        # Algunas tiendas publican la cadena "null" en vez de omitir el campo.
        ean = _texto(objeto.get("gtin13") or objeto.get("gtin14") or objeto.get("gtin"))
        if ean.lower() in ("", "null", "none"):
            ean = None

        return Captura(
            tienda=tienda,
            sku_externo=sku,
            titulo=_texto(objeto.get("name")),
            url=url,
            precio_internet=precio,
            precio_normal=a_entero(objeto.get("listPrice")),
            disponible=disponible,
            imagen_url=imagen if isinstance(imagen, str) else None,
            ean=ean,
        )
    return None
