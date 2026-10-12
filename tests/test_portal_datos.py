"""Lo que el portal enseña sale de aquí, y solo lee."""

from almacen.conexion import abrir
from almacen.operaciones import alta_o_actualiza_producto, registrar_si_cambio
from fuentes.base import Captura
from portal.datos import datos_del_portal


def captura(sku="S1", precio=100000, tienda="paris", titulo="Notebook", articulo=None):
    return Captura(
        tienda=tienda,
        sku_externo=sku,
        titulo=titulo,
        url=f"https://www.{tienda}.cl/n-{sku}.html",
        precio_internet=precio,
        producto_solotodo=articulo,
    )


def _con_precios(con, precios, **kw):
    """Da de alta un producto y le registra varios precios, en orden."""
    producto_id = None
    for i, precio in enumerate(precios):
        unica = captura(precio=precio, **kw)
        producto_id = alta_o_actualiza_producto(con, unica)
        registrar_si_cambio(con, producto_id, unica)
        # Las marcas de tiempo tienen resolución de segundo: se separan a mano
        # para que el orden del histórico sea el de inserción y no un empate.
        con.execute(
            "UPDATE historico_precios SET capturado_el = ? WHERE producto_id = ?"
            " AND precio_internet = ?",
            (f"2026-10-0{i + 1} 10:00:00", producto_id, precio),
        )
    return producto_id


def test_una_bajada_trae_el_antes_y_el_despues_con_fechas(tmp_path):
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [887990, 349990], sku="B1")

    oferta = datos_del_portal(con)["ofertas"][0]
    assert oferta["precio"] == 349990
    assert oferta["precio_anterior"] == 887990
    assert oferta["fecha_anterior"].startswith("2026-10-01")
    assert oferta["fecha"].startswith("2026-10-02")
    assert oferta["descuento_pct"] == 61


# --- Review Focus 2: una sola lectura ---
def test_un_producto_con_una_sola_lectura_no_tiene_anterior(tmp_path):
    """Sin precio previo no hay descuento que calcular, y dividir por `None`
    tumbaría la generación entera del portal."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="U1")

    oferta = datos_del_portal(con)["ofertas"][0]
    assert oferta["precio_anterior"] is None
    assert oferta["fecha_anterior"] is None
    assert oferta["descuento_pct"] == 0


# --- Review Focus 3: el precio subió ---
def test_un_precio_que_subio_no_es_una_oferta(tmp_path):
    """El descuento saldría negativo. No es una rebaja: es lo contrario."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000, 150000], sku="S2")

    oferta = datos_del_portal(con)["ofertas"][0]
    assert oferta["precio"] == 150000
    assert oferta["precio_anterior"] == 100000
    assert oferta["descuento_pct"] == 0


# --- Review Focus 4: sin identificador de artículo ---
def test_un_producto_sin_articulo_va_suelto(tmp_path):
    """Agruparlo por título sería adivinar, y aquí no se adivina."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="A1", articulo=None)
    _con_precios(con, [120000], sku="A2", tienda="falabella", articulo=None)

    ofertas = datos_del_portal(con)["ofertas"]
    assert len(ofertas) == 2
    assert all(o["articulo"] is None for o in ofertas)


def test_el_mismo_articulo_en_dos_tiendas_sale_dos_veces_con_su_articulo(tmp_path):
    """El portal agrupa al pintar; los datos traen las dos filas con la misma
    etiqueta, que es lo que permite agrupar sin adivinar."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="M1", articulo=269594)
    _con_precios(con, [120000], sku="M2", tienda="falabella", articulo=269594)

    ofertas = datos_del_portal(con)["ofertas"]
    assert sorted(o["articulo"] for o in ofertas) == [269594, 269594]


# --- Review Focus 5: títulos con comillas ---
def test_un_titulo_con_comillas_sobrevive(tmp_path):
    import json

    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="C1", titulo='Monitor 15,6" <Full HD> & más')

    datos = datos_del_portal(con)
    ida_y_vuelta = json.loads(json.dumps(datos, ensure_ascii=False))
    assert ida_y_vuelta["ofertas"][0]["titulo"] == 'Monitor 15,6" <Full HD> & más'


def test_la_cabecera_cuenta_productos_y_tiendas(tmp_path):
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="P1", tienda="paris")
    _con_precios(con, [100000], sku="P2", tienda="falabella")

    datos = datos_del_portal(con)
    assert datos["productos"] == 2
    assert datos["tiendas"] == 2
    assert datos["generado_el"]
