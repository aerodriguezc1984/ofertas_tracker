from fuentes.base import Captura
from nucleo.evaluador import Reglas, evaluar


def captura(precio=100000, tarjeta=None, disponible=True):
    return Captura(
        tienda="paris",
        sku_externo="S1",
        titulo="Notebook",
        url="https://www.paris.cl/n-S1.html",
        precio_internet=precio,
        precio_tarjeta=tarjeta,
        disponible=disponible,
    )


def test_sin_stock_nunca_avisa():
    assert evaluar(captura(disponible=False), Reglas(precio_maximo=999999), None, 0, 7) is None


def test_precio_maximo_cumplido():
    v = evaluar(captura(precio=89990), Reglas(precio_maximo=90000), None, 0, 7)
    assert v is not None and v.regla == "precio_maximo" and v.precio == 89990


def test_precio_maximo_no_cumplido():
    assert evaluar(captura(precio=95000), Reglas(precio_maximo=90000), None, 0, 7) is None


def test_el_precio_de_tarjeta_se_ignora_por_defecto():
    """Una oferta que solo existe con la tarjeta de la casa no cuenta."""
    reglas = Reglas(precio_maximo=90000, permitir_precio_tarjeta=False)
    assert evaluar(captura(precio=95000, tarjeta=85000), reglas, None, 0, 7) is None


def test_el_precio_de_tarjeta_cuenta_si_se_permite():
    reglas = Reglas(precio_maximo=90000, permitir_precio_tarjeta=True)
    v = evaluar(captura(precio=95000, tarjeta=85000), reglas, None, 0, 7)
    assert v is not None and v.precio == 85000


def test_descuento_por_encima_del_umbral():
    v = evaluar(captura(precio=80000), Reglas(descuento_minimo_pct=15), 100000, 30, 7)
    assert v is not None and v.regla == "descuento_minimo_pct"


def test_descuento_por_debajo_del_umbral():
    assert evaluar(captura(precio=90000), Reglas(descuento_minimo_pct=15), 100000, 30, 7) is None


def test_arranque_en_frio_no_evalua_el_descuento():
    """Con 2 días de histórico, todo precio es su propio mínimo."""
    assert evaluar(captura(precio=80000), Reglas(descuento_minimo_pct=15), 100000, 2, 7) is None


def test_sin_minimo_historico_no_evalua_el_descuento():
    assert evaluar(captura(precio=80000), Reglas(descuento_minimo_pct=15), None, 30, 7) is None


def test_el_precio_maximo_manda_sobre_el_descuento():
    """Si cumple las dos, se informa de la más concreta."""
    reglas = Reglas(precio_maximo=90000, descuento_minimo_pct=15)
    v = evaluar(captura(precio=80000), reglas, 100000, 30, 7)
    assert v is not None and v.regla == "precio_maximo"


def test_sin_reglas_no_avisa():
    assert evaluar(captura(), Reglas(), 100000, 30, 7) is None
