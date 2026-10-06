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


from fuentes.base import Referencia
from fuentes.solotodo import SoloTodo
from fuentes.transporte import TiendaBloqueada

CATALOGO = json.dumps([{"id": 30, "name": "AbcDin"}, {"id": 9, "name": "Falabella"}])
BUSQUEDA = json.dumps({"count": 2, "results": [ENTIDADES[0], ENTIDADES[2]]})


def transporte_de(mapa):
    pedidas = []

    def traer(url):
        pedidas.append(url)
        if url not in mapa:
            raise TiendaBloqueada(f"sin respuesta para {url}")
        return mapa[url]

    return traer, pedidas


def test_la_busqueda_pide_el_catalogo_una_vez_y_luego_no():
    """El catálogo de tiendas no cambia dentro de un ciclo."""
    traer, pedidas = transporte_de({
        "https://api.solotodo.com/stores/": CATALOGO,
        "https://api.solotodo.com/entities/?search=notebook&is_active=true": BUSQUEDA,
    })
    fuente = SoloTodo(traer, excluidas=["paris", "falabella"])

    fuente.buscar("notebook", limite=5)
    fuente.buscar("notebook", limite=5)

    assert pedidas.count("https://api.solotodo.com/stores/") == 1


def test_la_busqueda_descarta_las_tiendas_excluidas():
    traer, _ = transporte_de({
        "https://api.solotodo.com/stores/": CATALOGO,
        "https://api.solotodo.com/entities/?search=notebook&is_active=true": BUSQUEDA,
    })
    capturas = SoloTodo(traer, excluidas=["paris", "falabella"]).buscar("notebook", limite=5)

    assert [c.tienda for c in capturas] == ["abcdin"]


def test_la_busqueda_respeta_el_limite():
    muchas = json.dumps({"count": 2, "results": [ENTIDADES[0], ENTIDADES[0]]})
    traer, _ = transporte_de({
        "https://api.solotodo.com/stores/": CATALOGO,
        "https://api.solotodo.com/entities/?search=notebook&is_active=true": muchas,
    })
    assert len(SoloTodo(traer).buscar("notebook", limite=1)) == 1


def test_el_termino_se_codifica():
    traer, pedidas = transporte_de({"https://api.solotodo.com/stores/": CATALOGO})
    SoloTodo(traer).buscar("notebook 16 gb", limite=5)
    assert pedidas[-1] == (
        "https://api.solotodo.com/entities/?search=notebook+16+gb&is_active=true"
    )


def test_un_catalogo_inalcanzable_deja_la_busqueda_en_vacio():
    traer, _ = transporte_de({})   # ni siquiera el catálogo responde
    assert SoloTodo(traer).buscar("notebook", limite=5) == []


def test_una_busqueda_bloqueada_devuelve_vacio():
    traer, _ = transporte_de({"https://api.solotodo.com/stores/": CATALOGO})
    assert SoloTodo(traer).buscar("notebook", limite=5) == []


def test_obtener_pide_cada_entidad_y_una_caida_no_tumba_las_demas():
    traer, pedidas = transporte_de({
        "https://api.solotodo.com/stores/": CATALOGO,
        "https://api.solotodo.com/entities/1379496/": json.dumps(ENTIDADES[0]),
    })
    capturas = SoloTodo(traer).obtener([
        Referencia("abcdin", "https://api.solotodo.com/entities/999999/"),
        Referencia("abcdin", "https://api.solotodo.com/entities/1379496/"),
    ])
    assert len(capturas) == 1
    assert capturas[0].sku_externo == "AD-100"


def test_un_catalogo_que_falla_se_reintenta_en_la_llamada_siguiente():
    """Cachear el fallo dejaría la fuente muda el resto del ciclo.

    `_catalogo` solo guarda el catálogo cuando lo consigue, así que un tropiezo
    cuesta una petición perdida y no la fuente entera.
    """
    intentos = []

    def traer(url):
        if url == "https://api.solotodo.com/stores/":
            intentos.append(url)
            if len(intentos) == 1:
                raise TiendaBloqueada("503 la primera vez")
            return CATALOGO
        return BUSQUEDA

    fuente = SoloTodo(traer, excluidas=["paris", "falabella"])

    assert fuente.buscar("notebook", limite=5) == []          # el catálogo falló
    assert [c.tienda for c in fuente.buscar("notebook", limite=5)] == ["abcdin"]
    assert len(intentos) == 2                                  # sí se reintentó
