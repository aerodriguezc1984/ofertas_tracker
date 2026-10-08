from dataclasses import replace

from almacen.conexion import abrir
from almacen.operaciones import (
    alta_o_actualiza_producto,
    productos_a_comparar,
    guardar_identidad,
    marcar_comparado,
    registrar_si_cambio,
)
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
    """La tarjeta cambia y el precio no: el histórico debe enterarse igual.

    La tercera llamada es la que da valor a las dos primeras: sin ella, esta
    prueba pasaría también con el SELECT y la tupla desalineados, porque dos
    tuplas de distinta longitud nunca son iguales y la función devolvería
    `True` siempre.
    """
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

    # Nada cambió respecto de la anterior: no debe anotarse fila.
    assert registrar_si_cambio(con, pid, con_otra) is False
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 2


def test_el_alta_guarda_el_identificador_de_solotodo(tmp_path):
    con = abrir(tmp_path / "p.db")
    c = replace(captura(), producto_solotodo=43835)
    pid = alta_o_actualiza_producto(con, c)

    fila = con.execute(
        "SELECT producto_solotodo FROM productos WHERE id = ?", (pid,)
    ).fetchone()
    assert fila["producto_solotodo"] == 43835


def test_una_captura_sin_identificador_no_borra_el_que_ya_habia(tmp_path):
    """Paris y Falabella no lo traen; no pueden pisar lo que SoloTodo guardó."""
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, replace(captura(), producto_solotodo=43835))
    alta_o_actualiza_producto(con, captura())   # sin identificador

    fila = con.execute(
        "SELECT producto_solotodo FROM productos WHERE id = ?", (pid,)
    ).fetchone()
    assert fila["producto_solotodo"] == 43835


def _producto_con_precio(con, tienda, sku, precio, url=None):
    """Da de alta un producto y le deja una fila de histórico.

    El ayudante `captura()` de este archivo fija la tienda en «paris» y no
    acepta cambiarla, así que la tienda y la URL se ajustan con `replace`. No
    se toca el ayudante: lo usan las pruebas que ya existen.
    """
    nueva = replace(
        captura(precio=precio, sku=sku),
        tienda=tienda,
        url=url or f"https://www.{tienda}.cl/n-{sku}.html",
    )
    producto_id = alta_o_actualiza_producto(con, nueva)
    registrar_si_cambio(con, producto_id, nueva)
    return producto_id


def test_solo_se_comparan_los_productos_revisados_en_este_ciclo(tmp_path):
    con = abrir(tmp_path / "p.db")
    viejo = _producto_con_precio(con, "paris", "V1", 100000, "https://ejemplo/viejo")
    con.execute(
        "UPDATE productos SET ultima_revision = '2000-01-01 00:00:00' WHERE id = ?",
        (viejo,),
    )
    nuevo = _producto_con_precio(con, "paris", "N1", 90000, "https://ejemplo/nuevo")

    a_comparar = productos_a_comparar(con, "2024-01-01 00:00:00", 10)

    assert [p.id for p in a_comparar] == [nuevo]
    assert a_comparar[0].precio_internet == 90000
    assert a_comparar[0].tienda == "paris"


def test_el_tope_corta_cuantos_se_comparan(tmp_path):
    con = abrir(tmp_path / "p.db")
    for i in range(5):
        _producto_con_precio(con, "paris", f"S{i}", 100000 + i, f"https://ejemplo/{i}")

    assert len(productos_a_comparar(con, "2024-01-01 00:00:00", 2)) == 2


def test_un_tope_de_cero_no_devuelve_nada(tmp_path):
    con = abrir(tmp_path / "p.db")
    _producto_con_precio(con, "paris", "S0", 100000)
    assert productos_a_comparar(con, "2024-01-01 00:00:00", 0) == []


# --- Review Focus 4: los nulos van primero ---
def test_el_que_nunca_se_comparo_tiene_preferencia(tmp_path):
    """SQLite ordena los nulos ANTES en ASC, y eso es justo lo que queremos:
    un producto nunca comparado no puede esperar detrás de uno de ayer."""
    con = abrir(tmp_path / "p.db")
    comparado = _producto_con_precio(con, "paris", "C1", 100000, "https://ejemplo/c")
    con.execute(
        "UPDATE productos SET ultima_comparacion = '2026-01-01 00:00:00' WHERE id = ?",
        (comparado,),
    )
    nunca = _producto_con_precio(con, "paris", "N2", 100000, "https://ejemplo/n")

    assert [p.id for p in productos_a_comparar(con, "2024-01-01 00:00:00", 1)] == [nunca]


def test_un_producto_sin_historico_no_se_compara(tmp_path):
    """Sin precio nuestro no hay nada contra lo que comparar."""
    con = abrir(tmp_path / "p.db")
    alta_o_actualiza_producto(con, captura(precio=1, sku="SH"))
    assert productos_a_comparar(con, "2024-01-01 00:00:00", 10) == []


def test_guardar_identidad_y_marcar_comparado(tmp_path):
    con = abrir(tmp_path / "p.db")
    producto_id = _producto_con_precio(con, "paris", "G1", 100000)

    guardar_identidad(con, producto_id, 269594)
    marcar_comparado(con, producto_id)

    fila = con.execute(
        "SELECT producto_solotodo, ultima_comparacion FROM productos WHERE id = ?",
        (producto_id,),
    ).fetchone()
    assert fila["producto_solotodo"] == 269594
    assert fila["ultima_comparacion"] is not None
