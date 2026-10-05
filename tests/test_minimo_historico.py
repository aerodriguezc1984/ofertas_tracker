from almacen.conexion import abrir
from almacen.operaciones import (
    alta_o_actualiza_producto,
    dias_de_historico,
    minimo_historico,
)
from fuentes.base import Captura


def producto(con):
    c = Captura(
        tienda="paris",
        sku_externo="SKU1",
        titulo="Notebook",
        url="https://www.paris.cl/notebook-SKU1.html",
        precio_internet=100000,
    )
    return alta_o_actualiza_producto(con, c)


def fila(con, pid, precio, hace_dias):
    con.execute(
        """
        INSERT INTO historico_precios (producto_id, precio_internet, capturado_el)
             VALUES (?, ?, datetime('now', ?))
        """,
        (pid, precio, f"-{hace_dias} days"),
    )


def test_sin_historico_devuelve_none(tmp_path):
    con = abrir(tmp_path / "p.db")
    assert minimo_historico(con, producto(con), 90) is None


def test_toma_el_menor_dentro_de_la_ventana(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = producto(con)
    fila(con, pid, 100000, 30)
    fila(con, pid, 89990, 10)
    assert minimo_historico(con, pid, 90) == 89990


def test_cuenta_el_precio_vigente_aunque_la_ventana_tenga_filas(tmp_path):
    """El precio viejo siguió vigente dentro de la ventana, así que cuenta.

    Entre el día 200 y el día 30 el precio fue 50000, y los días 90 a 30 caen
    dentro de la ventana: 50000 es de verdad el mínimo vigente en esos 90 días.
    """
    con = abrir(tmp_path / "p.db")
    pid = producto(con)
    fila(con, pid, 50000, 200)
    fila(con, pid, 100000, 30)
    assert minimo_historico(con, pid, 90) == 50000


def test_usa_el_precio_vigente_al_abrirse_la_ventana(tmp_path):
    """El caso que rompe la implementación ingenua.

    El precio se fijó hace 150 días y nunca cambió: no hay filas dentro de la
    ventana de 90, pero el producto SÍ tiene un precio conocido.
    """
    con = abrir(tmp_path / "p.db")
    pid = producto(con)
    fila(con, pid, 120000, 150)
    assert minimo_historico(con, pid, 90) == 120000


def test_dias_de_historico_mide_desde_la_primera_fila(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = producto(con)
    fila(con, pid, 100000, 10)
    assert 9.5 < dias_de_historico(con, pid) < 10.5


def test_dias_de_historico_sin_filas_es_cero(tmp_path):
    con = abrir(tmp_path / "p.db")
    assert dias_de_historico(con, producto(con)) == 0.0
