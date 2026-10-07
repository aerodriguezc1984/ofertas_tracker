"""La decisión de «está más barato en otra parte», sin red y sin base."""

import pytest

from nucleo.comparacion import (
    OfertaAjena,
    ReglasComparacion,
    mejor_oferta,
)

REGLAS = ReglasComparacion(caida_minima_pct=10.0, ahorro_minimo_pesos=10000)


def oferta(tienda="winpy", precio=80000, disponible=True):
    return OfertaAjena(
        tienda=tienda, precio=precio, url=f"https://{tienda}.cl/x", disponible=disponible
    )


def test_una_oferta_que_cumple_los_dos_umbrales_gana():
    veredicto = mejor_oferta(100000, "paris", [oferta(precio=80000)], REGLAS)
    assert veredicto is not None
    assert veredicto.oferta.tienda == "winpy"
    assert veredicto.ahorro == 20000
    assert round(veredicto.porcentaje) == 20


def test_sin_ofertas_no_hay_veredicto():
    assert mejor_oferta(100000, "paris", [], REGLAS) is None


def test_una_oferta_mas_cara_no_cuenta():
    assert mejor_oferta(100000, "paris", [oferta(precio=120000)], REGLAS) is None


def test_una_oferta_agotada_no_cuenta():
    """Un precio más bajo de algo que no se puede comprar es ruido."""
    assert mejor_oferta(100000, "paris", [oferta(precio=50000, disponible=False)], REGLAS) is None


def test_cumplir_el_porcentaje_sin_el_ahorro_no_basta():
    """Un 20 % de un producto barato son 800 pesos: no mueve ninguna decisión."""
    assert mejor_oferta(4000, "paris", [oferta(precio=3200)], REGLAS) is None


def test_cumplir_el_ahorro_sin_el_porcentaje_no_basta():
    """15.000 pesos sobre 900.000 es un 1,7 %: tampoco."""
    assert mejor_oferta(900000, "paris", [oferta(precio=885000)], REGLAS) is None


def test_justo_en_los_dos_umbrales_avisa():
    """Los umbrales son inclusivos: 10 % exacto y 10.000 pesos exactos."""
    veredicto = mejor_oferta(100000, "paris", [oferta(precio=90000)], REGLAS)
    assert veredicto is not None
    assert veredicto.ahorro == 10000


def test_se_queda_con_la_mas_barata_de_varias():
    ofertas = [oferta("winpy", 85000), oferta("spdigital", 70000), oferta("wei", 78000)]
    veredicto = mejor_oferta(100000, "paris", ofertas, REGLAS)
    assert veredicto.oferta.tienda == "spdigital"


def test_un_empate_se_resuelve_siempre_igual():
    """Dos tiendas al mismo precio no pueden dar un aviso distinto en cada ciclo."""
    ofertas = [oferta("winpy", 70000), oferta("spdigital", 70000)]
    primero = mejor_oferta(100000, "paris", ofertas, REGLAS)
    segundo = mejor_oferta(100000, "paris", list(reversed(ofertas)), REGLAS)
    assert primero.oferta.tienda == segundo.oferta.tienda == "spdigital"


# --- Review Focus 2: la oferta de nuestra propia tienda ---
def test_nuestra_propia_tienda_no_compite_consigo_misma():
    """El producto ES una entidad de SoloTodo, así que sale en su propia lista."""
    ofertas = [oferta("paris", 70000), oferta("winpy", 95000)]
    # La de Paris es la más barata, pero somos Paris: la única candidata real
    # es la de Winpy, que no llega a los umbrales.
    assert mejor_oferta(100000, "paris", ofertas, REGLAS) is None


# --- Review Focus 1: nuestro precio a cero ---
@pytest.mark.parametrize("precio_nuestro", [0, -1])
def test_un_precio_nuestro_no_positivo_no_compara(precio_nuestro):
    """El porcentaje divide por nuestro precio: un cero tumbaría el paso entero."""
    assert mejor_oferta(precio_nuestro, "paris", [oferta(precio=1)], REGLAS) is None


def test_una_oferta_con_precio_no_positivo_se_descarta():
    """Un 'gratis' de una tienda ajena es un dato roto, no una ganga."""
    assert mejor_oferta(100000, "paris", [oferta(precio=0)], REGLAS) is None
