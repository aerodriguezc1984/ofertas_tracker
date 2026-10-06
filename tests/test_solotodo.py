import json
from pathlib import Path

import pytest

from fuentes.solotodo import captura_de_entidad, identificador_de_tienda

FIXTURES = Path(__file__).parent / "fixtures"
ENTIDADES = json.loads((FIXTURES / "solotodo_entidades.json").read_text(encoding="utf-8"))

TIENDAS = {30: "AbcDin", 9: "Falabella", 77: "PC Factory"}
EXCLUIDAS = {"paris", "falabella"}


@pytest.mark.parametrize(
    "nombre, esperado",
    [("AbcDin", "abcdin"), ("PC Factory", "pc-factory"), ("Tecno Saga", "tecno-saga")],
)
def test_el_identificador_de_tienda_se_normaliza(nombre, esperado):
    assert identificador_de_tienda(nombre) == esperado


def test_una_entidad_activa_da_su_captura():
    c = captura_de_entidad(ENTIDADES[0], TIENDAS, EXCLUIDAS)
    assert c is not None
    assert c.tienda == "abcdin"          # la tienda real, no «solotodo»
    assert c.sku_externo == "AD-100"
    assert c.url == "https://www.abc.cl/notebook-AD-100"
    assert c.precio_internet == 573990   # offer_price
    assert c.precio_normal == 587990     # normal_price
    assert c.precio_tarjeta is None      # SoloTodo no lo publica
    assert c.tarjeta is None
    assert c.disponible is True
    assert c.ean == "7801234567890"
    assert c.producto_solotodo == 43835
    assert c.precios_etiquetados is True


def test_los_precios_con_decimales_llegan_enteros():
    c = captura_de_entidad(ENTIDADES[0], TIENDAS, EXCLUIDAS)
    assert isinstance(c.precio_internet, int)
    assert isinstance(c.precio_normal, int)


def test_una_entidad_sin_precio_activo_se_descarta():
    assert captura_de_entidad(ENTIDADES[1], TIENDAS, EXCLUIDAS) is None


def test_una_tienda_que_cubrimos_en_directo_se_descarta():
    """Si no, el mismo producto recibiría filas alternas de dos fuentes que
    discrepan en la tarjeta, y el histórico crecería una fila por ciclo."""
    assert captura_de_entidad(ENTIDADES[2], TIENDAS, EXCLUIDAS) is None


def test_una_tienda_desconocida_se_descarta():
    """Sin nombre de tienda no hay identidad, y una inventada mezcla productos."""
    assert captura_de_entidad(ENTIDADES[3], TIENDAS, EXCLUIDAS) is None


def test_un_ean_ausente_llega_como_none_y_no_como_texto():
    entidad = dict(ENTIDADES[0], ean=None)
    c = captura_de_entidad(entidad, TIENDAS, EXCLUIDAS)
    assert c.ean is None


def test_una_entidad_sin_producto_normalizado_no_estalla():
    entidad = dict(ENTIDADES[0], product=None)
    c = captura_de_entidad(entidad, TIENDAS, EXCLUIDAS)
    assert c is not None and c.producto_solotodo is None


@pytest.mark.parametrize(
    "roto",
    [
        {"active_registry": {"is_available": True, "normal_price": "587990.00",
                             "offer_price": None}},
        {"sku": ""},
        {"name": ""},
        {"external_url": ""},
    ],
)
def test_una_entidad_incompleta_se_descarta(roto):
    """Activa y de una tienda que sí seguimos, pero le falta lo imprescindible.

    Es la única rama de descarte que las otras pruebas no alcanzan: las demás
    entidades de la fixture se paran antes, en el registro activo, la exclusión
    o la tienda desconocida.
    """
    entidad = dict(ENTIDADES[0], **roto)
    assert captura_de_entidad(entidad, TIENDAS, EXCLUIDAS) is None
