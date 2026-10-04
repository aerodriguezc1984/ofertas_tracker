from pathlib import Path

import pytest

from nucleo.normalizador import a_captura, bloques_ld_json

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


def test_agotado_segun_availability():
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X","sku":"S",'
        '"offers":{"price":1000,"availability":"https://schema.org/OutOfStock"}}'
        "</script>"
    )
    c = a_captura(html, URL, "paris")
    assert c is not None and c.disponible is False
