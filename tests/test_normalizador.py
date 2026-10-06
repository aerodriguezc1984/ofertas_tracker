from pathlib import Path

import pytest

from nucleo.normalizador import a_captura, a_entero, bloques_ld_json, productos_ld_json

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.paris.cl/home-panel-monaco-MK2GCAHDUR.html"


def leer(nombre):
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def test_encuentra_todos_los_bloques():
    assert len(bloques_ld_json(leer("paris_ficha.html"))) == 2


def test_extrae_la_captura_de_una_ficha_real():
    c = a_captura(leer("paris_ficha.html"), URL, "paris")
    assert c is not None
    assert c.tienda == "paris"
    assert c.sku_externo == "MK2GCAHDUR"
    assert c.titulo == "Home Panel Mónaco Tv 55 1 6 castaño off White"
    assert c.precio_internet == 229990
    assert isinstance(c.precio_internet, int)
    assert c.url == URL
    assert c.imagen_url == "https://cdn.paris.cl/monaco.jpg"
    assert c.disponible is True


def test_sin_precio_no_hay_captura():
    """Devolver un cero sería inventarse una oferta."""
    assert a_captura(leer("paris_ficha_sin_precio.html"), URL, "paris") is None


def test_sin_bloque_de_producto_no_hay_captura():
    html = '<html><script type="application/ld+json">{"@type":"WebPage"}</script></html>'
    assert a_captura(html, URL, "paris") is None


def test_el_json_ilegible_no_estalla():
    html = '<html><script type="application/ld+json">{esto no es json</script></html>'
    assert bloques_ld_json(html) == []


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("229990", 229990),
        ('"229990"', 229990),
        ('"229990.00"', 229990),
        ('"229.990"', 229990),
    ],
)
def test_el_precio_siempre_acaba_en_entero(crudo, esperado):
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X","sku":"S",'
        f'"offers":{{"price":{crudo},"priceCurrency":"CLP"}}}}'
        "</script>"
    )
    c = a_captura(html, URL, "paris")
    assert c is not None and c.precio_internet == esperado


def test_sin_sku_no_hay_captura():
    """Sin identidad utilizable, mezclaría el histórico de dos productos distintos."""
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X",'
        '"offers":{"price":1000}}'
        "</script>"
    )
    assert a_captura(html, URL, "paris") is None


def test_un_bloque_sin_precio_no_tapa_al_siguiente_bloque_valido():
    """Varios JSON-LD por página (Falabella, abc.cl): uno inservible no esconde al resto."""
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Sin oferta"}'
        "</script>"
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"Con oferta","sku":"S2",'
        '"offers":{"price":1000}}'
        "</script>"
    )
    c = a_captura(html, URL, "paris")
    assert c is not None
    assert c.sku_externo == "S2"
    assert c.titulo == "Con oferta"


def test_agotado_segun_availability():
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X","sku":"S",'
        '"offers":{"price":1000,"availability":"https://schema.org/OutOfStock"}}'
        "</script>"
    )
    c = a_captura(html, URL, "paris")
    assert c is not None and c.disponible is False


ESCAPADO = (
    '<script type="application/ld+json">'
    "{&quot;@type&quot;:&quot;Product&quot;,&quot;name&quot;:&quot;Escapado&quot;,"
    "&quot;sku&quot;:&quot;E1&quot;,&quot;offers&quot;:{&quot;price&quot;:&quot;1000&quot;}}"
    "</script>"
)

# Bloque VÁLIDO cuyo texto contiene una entidad: desescaparlo lo rompería,
# porque `&quot;` se convertiría en una comilla real dentro de la cadena.
CON_ENTIDAD = (
    '<script type="application/ld+json">'
    '{"@type":"Product","name":"Monitor 27&quot; 4K","sku":"M1",'
    '"offers":{"price":"1000"}}'
    "</script>"
)

LISTA = (
    '<script type="application/ld+json">'
    '{"@type":"ItemList","itemListElement":['
    '{"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Uno","sku":"U1"}},'
    '{"@type":"ListItem","position":2,"item":{"@type":"Product","name":"Dos","sku":"D1"}}'
    "]}</script>"
)


def test_un_bloque_escapado_con_entidades_se_recupera():
    c = a_captura(ESCAPADO, "https://t.cl/e.html", "tienda")
    assert c is not None and c.sku_externo == "E1"


def test_un_bloque_valido_con_entidades_no_se_rompe():
    """Desescapar a ciegas convertiría `&quot;` en comilla y partiría el JSON."""
    c = a_captura(CON_ENTIDAD, "https://t.cl/m.html", "tienda")
    assert c is not None
    assert c.titulo == 'Monitor 27" 4K'


def test_productos_ld_json_encuentra_los_de_un_itemlist():
    assert [p["sku"] for p in productos_ld_json(LISTA)] == ["U1", "D1"]


def test_productos_ld_json_encuentra_los_de_primer_nivel():
    assert [p["sku"] for p in productos_ld_json(CON_ENTIDAD)] == ["M1"]


def test_un_ean_que_vale_null_se_descarta():
    """Falabella publica literalmente la cadena "null" cuando no tiene gtin."""
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X","sku":"S1","gtin13":"null",'
        '"offers":{"price":"1000"}}'
        "</script>"
    )
    c = a_captura(html, "https://t.cl/x.html", "tienda")
    assert c is not None and c.ean is None


def test_a_entero_es_publica():
    assert a_entero("229.990") == 229990


def test_una_lista_de_relacionados_no_suplanta_al_producto_de_la_ficha():
    """En una ficha, un `ItemList` solo puede ser un carrusel de recomendados.

    Va antes que el producto real a propósito: si ganara el primero, se
    guardaría otro producto bajo la URL vigilada, y su precio entraría en el
    mínimo histórico para siempre.
    """
    html = (
        '<script type="application/ld+json">'
        '{"@type":"ItemList","itemListElement":[{"@type":"ListItem","item":'
        '{"@type":"Product","name":"Relacionado barato","sku":"OTRO-999",'
        '"offers":{"price":"9990"}}}]}'
        "</script>"
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"El vigilado","sku":"MK2GCAHDUR",'
        '"offers":{"price":"229990"}}'
        "</script>"
    )

    c = a_captura(html, "https://t.cl/vigilado.html", "tienda")

    assert c is not None
    assert c.sku_externo == "MK2GCAHDUR"
    assert c.precio_internet == 229990
