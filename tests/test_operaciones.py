from dataclasses import replace

from almacen.conexion import abrir
from almacen.operaciones import alta_o_actualiza_producto, registrar_si_cambio
from fuentes.base import Captura


def captura(precio=100000, disponible=True, sku="SKU1"):
    return Captura(
        tienda="paris",
        sku_externo=sku,
        titulo="Notebook de prueba",
        url=f"https://www.paris.cl/notebook-{sku}.html",
        precio_internet=precio,
        precio_normal=None,
        precio_tarjeta=None,
        tarjeta=None,
        disponible=disponible,
    )


def test_el_alta_no_duplica_el_producto(tmp_path):
    con = abrir(tmp_path / "p.db")
    primero = alta_o_actualiza_producto(con, captura())
    segundo = alta_o_actualiza_producto(con, captura())
    assert primero == segundo
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 1


def test_el_historico_no_crece_si_nada_cambia(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, captura())

    assert registrar_si_cambio(con, pid, captura()) is True
    assert registrar_si_cambio(con, pid, captura()) is False

    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 1


def test_el_historico_crece_si_cambia_el_precio(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, captura(precio=100000))
    registrar_si_cambio(con, pid, captura(precio=100000))

    assert registrar_si_cambio(con, pid, captura(precio=89990)) is True
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 2


def test_el_historico_crece_si_cambia_la_disponibilidad(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, captura())
    registrar_si_cambio(con, pid, captura())

    assert registrar_si_cambio(con, pid, captura(disponible=False)) is True
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 2


def test_el_alta_anota_la_revision(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, captura())
    fila = con.execute(
        "SELECT ultima_revision FROM productos WHERE id = ?", (pid,)
    ).fetchone()
    assert fila["ultima_revision"] is not None


def test_el_historico_crece_si_cambia_la_tarjeta(tmp_path):
    """La tarjeta cambia y el precio no: el histórico debe enterarse igual."""
    con = abrir(tmp_path / "p.db")
    con_cmr = Captura(
        tienda="falabella", sku_externo="F1", titulo="Notebook",
        url="https://www.falabella.com/falabella-cl/product/1/x/1",
        precio_internet=100000, precio_tarjeta=90000, tarjeta="CMR",
    )
    pid = alta_o_actualiza_producto(con, con_cmr)
    assert registrar_si_cambio(con, pid, con_cmr) is True

    con_otra = replace(con_cmr, tarjeta="CENCOSUD")
    assert registrar_si_cambio(con, pid, con_otra) is True
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 2
