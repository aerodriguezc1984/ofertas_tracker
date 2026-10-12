"""Lo que el portal enseña sale de aquí, y solo lee."""

import json
from pathlib import Path

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


def test_el_desempate_por_id_deshace_el_empate_del_mismo_segundo(tmp_path):
    """Un ciclo real mete varias lecturas dentro del mismo segundo."""
    con = abrir(tmp_path / "p.db")
    producto_id = _con_precios(con, [100000, 150000, 120000, 180000], sku="T1")
    con.execute(
        "UPDATE historico_precios SET capturado_el = '2026-10-10 10:00:00'"
        " WHERE producto_id = ?",
        (producto_id,),
    )

    oferta = datos_del_portal(con)["ofertas"][0]
    assert oferta["precio"] == 180000          # el último insertado, no el primero
    assert oferta["precio_anterior"] == 120000


def test_generar_escribe_los_dos_archivos(tmp_path):
    from herramientas.generar_portal import generar

    con = abrir(tmp_path / "p.db")
    _con_precios(con, [887990, 349990], sku="G1")

    html, datos = generar(con, tmp_path / "salida")

    assert html.name == "index.html"
    assert datos.name == "datos.json"
    assert html.exists() and datos.exists()


def test_el_json_generado_es_valido_y_trae_las_ofertas(tmp_path):
    from herramientas.generar_portal import generar

    con = abrir(tmp_path / "p.db")
    _con_precios(con, [887990, 349990], sku="G2", titulo='Monitor 15,6" & más')

    _, datos = generar(con, tmp_path / "salida")
    leido = json.loads(datos.read_text(encoding="utf-8"))

    assert leido["ofertas"][0]["titulo"] == 'Monitor 15,6" & más'
    assert leido["ofertas"][0]["descuento_pct"] == 61


def test_la_pagina_no_pinta_datos_con_innerhtml():
    """Los títulos vienen de las tiendas: con `innerHTML` uno con `<` rompe la
    página. La plantilla usa `textContent` y esta prueba lo fija."""
    plantilla = (Path(__file__).parent.parent / "src" / "portal" / "plantilla.html").read_text(
        encoding="utf-8"
    )
    assert "innerHTML" not in plantilla
    # `innerHTML` no es la única puerta: estas pintan marcado igual de bien.
    for puerta in ("insertAdjacentHTML", "outerHTML", "document.write", "new Function"):
        assert puerta not in plantilla


def test_la_pagina_avisa_cuando_no_puede_cargar_los_datos():
    """Un fetch que falla no puede dejar un «Cargando…» eterno."""
    plantilla = (Path(__file__).parent.parent / "src" / "portal" / "plantilla.html").read_text(
        encoding="utf-8"
    )
    assert "catch (error)" in plantilla
    assert "No se pudieron cargar los datos" in plantilla
    assert "Sin conexión con los datos" in plantilla


def test_la_pagina_no_enlaza_una_url_que_no_sea_http():
    """La URL la escribe la tienda; el esquema hay que mirarlo a mano."""
    plantilla = (Path(__file__).parent.parent / "src" / "portal" / "plantilla.html").read_text(
        encoding="utf-8"
    )
    assert "function urlSegura" in plantilla
    assert "enlace.href = destino;" in plantilla
    assert "enlace.href = mejor.url" not in plantilla
    # El nombre de la función no protege nada: lo que protege es este filtro.
    assert r"/^https?:\/\//i.test(" in plantilla


def test_las_claves_de_una_oferta_son_las_que_espera_la_pagina(tmp_path):
    """Renombrar una clave en Python deja la página sin insignias y todo verde."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [887990, 349990], sku="K1")

    oferta = datos_del_portal(con)["ofertas"][0]
    assert set(oferta) == {
        "articulo", "tienda", "titulo", "url", "imagen", "disponible",
        "precio", "fecha", "precio_anterior", "fecha_anterior",
        "descuento_pct", "minimo_historico",
    }
    # `src/portal/plantilla.html` lee estas claves por su nombre y nada más las
    # ata: si cambias una aquí, cámbiala allí.
    plantilla = (Path(__file__).parent.parent / "src" / "portal" / "plantilla.html").read_text(
        encoding="utf-8"
    )
    for clave in ("descuento_pct", "precio_anterior", "fecha_anterior", "disponible"):
        assert clave in plantilla
