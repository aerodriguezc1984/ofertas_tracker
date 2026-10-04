"""Del HTML de una ficha a una Captura, leyendo el JSON-LD de schema.org.

Es el motor genérico: cualquier tienda que publique un bloque
`<script type="application/ld+json">` con un Product se lee con este código, sin
escribir selectores para cada sitio.
"""

import json
import re

from fuentes.base import Captura

_BLOQUE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def bloques_ld_json(html: str) -> list[dict]:
    """Todos los objetos JSON-LD de la página. Los ilegibles se descartan."""
    objetos: list[dict] = []
    for crudo in _BLOQUE.findall(html):
        try:
            dato = json.loads(crudo.strip())
        except json.JSONDecodeError:
            continue
        for item in dato if isinstance(dato, list) else [dato]:
            if isinstance(item, dict):
                objetos.append(item)
    return objetos


def _a_entero(valor) -> int | None:
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
    """La Captura de la ficha, o None si la página no da un precio utilizable."""
    for objeto in bloques_ld_json(html):
        if not _tipo_es(objeto, "Product"):
            continue

        ofertas = objeto.get("offers") or {}
        if isinstance(ofertas, list):
            ofertas = ofertas[0] if ofertas else {}

        precio = _a_entero(ofertas.get("price"))
        if precio is None:
            return None

        imagen = objeto.get("image")
        if isinstance(imagen, list):
            imagen = imagen[0] if imagen else None

        disponibilidad = str(ofertas.get("availability") or "")
        # Cuando la tienda no declara stock, se asume disponible: lo contrario
        # silenciaría todas las alertas de las tiendas que no publican el dato.
        disponible = "outofstock" not in disponibilidad.lower().replace("/", "")

        return Captura(
            tienda=tienda,
            sku_externo=str(objeto.get("sku") or "").strip(),
            titulo=str(objeto.get("name") or "").strip(),
            url=url,
            precio_internet=precio,
            precio_normal=_a_entero(objeto.get("listPrice")),
            disponible=disponible,
            imagen_url=imagen if isinstance(imagen, str) else None,
            ean=objeto.get("gtin13") or objeto.get("gtin14") or objeto.get("gtin"),
        )
    return None
