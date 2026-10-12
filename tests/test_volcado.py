"""El histórico tiene que sobrevivir a la máquina que lo generó."""

from almacen.conexion import abrir
from almacen.operaciones import alta_o_actualiza_producto, registrar_si_cambio
from almacen.volcado import restaurar, volcar
from fuentes.base import Captura


def captura(sku="S1", precio=100000, tienda="paris"):
    return Captura(
        tienda=tienda,
        sku_externo=sku,
        titulo='Notebook 15,6" Full HD',
        url=f"https://www.{tienda}.cl/n-{sku}.html",
        precio_internet=precio,
    )


def _base_con_datos(ruta, cuantos=3):
    con = abrir(ruta)
    for i in range(cuantos):
        unica = captura(sku=f"S{i}", precio=100000 + i)
        producto_id = alta_o_actualiza_producto(con, unica)
        registrar_si_cambio(con, producto_id, unica)
    return con


def test_volcar_y_restaurar_devuelve_la_misma_base(tmp_path):
    """La ida y vuelta es la propiedad entera de este módulo."""
    origen = _base_con_datos(tmp_path / "origen.db")
    antes = origen.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
    sql = tmp_path / "volcado.sql"
    volcar(origen, sql)

    assert restaurar(sql, tmp_path / "destino.db") is True
    destino = abrir(tmp_path / "destino.db")
    assert destino.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == antes
    assert destino.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == antes


def test_el_volcado_conserva_los_titulos_con_comillas(tmp_path):
    """Review Focus 5: los títulos reales llevan comillas dentro.

    El carácter que importa es el apóstrofo —delimita los literales SQL que
    genera `iterdump`—, no la comilla doble, que ahí dentro no es especial.
    10 de 599 títulos reales lo llevan como marca de pulgadas.
    """
    titulo_con_comillas = 'Notebook 16\'\' WUXGA "Edición Especial"'
    con = abrir(tmp_path / "origen.db")
    unica = Captura(
        tienda="paris",
        sku_externo="S1",
        titulo=titulo_con_comillas,
        url="https://www.paris.cl/n-S1.html",
        precio_internet=100000,
    )
    producto_id = alta_o_actualiza_producto(con, unica)
    registrar_si_cambio(con, producto_id, unica)

    sql = tmp_path / "volcado.sql"
    volcar(con, sql)
    restaurar(sql, tmp_path / "destino.db")

    titulo = abrir(tmp_path / "destino.db").execute(
        "SELECT titulo FROM productos"
    ).fetchone()[0]
    assert titulo == titulo_con_comillas


# --- Review Focus 1: el fallo más caro de esta etapa ---
def test_restaurar_un_volcado_vacio_no_borra_lo_que_habia(tmp_path):
    """Un ciclo que falla a mitad deja un volcado trunco.

    Restaurarlo encima borraría el histórico entero. Mejor no restaurar nada y
    seguir con la base que ya estaba: perder una hora de datos es recuperable,
    perder 599 productos no.
    """
    destino = tmp_path / "destino.db"
    _base_con_datos(destino, cuantos=5)
    vacio = tmp_path / "vacio.sql"
    vacio.write_text("", encoding="utf-8")

    assert restaurar(vacio, destino) is False
    assert abrir(destino).execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 5


def test_restaurar_un_volcado_sin_productos_no_borra_lo_que_habia(tmp_path):
    """Lo mismo, pero con un volcado sintácticamente válido y sin datos.

    Es el caso que de verdad puede pasar: la base se abrió, no se capturó nada,
    y se volcó un esquema vacío encima de uno lleno.
    """
    destino = tmp_path / "destino.db"
    _base_con_datos(destino, cuantos=5)

    hueca = abrir(tmp_path / "hueca.db")
    sql = tmp_path / "hueca.sql"
    volcar(hueca, sql)

    assert restaurar(sql, destino) is False
    assert abrir(destino).execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 5


def test_restaurar_cuando_no_existe_el_volcado(tmp_path):
    """El primer ciclo de todos: no hay nada que restaurar y eso es correcto."""
    assert restaurar(tmp_path / "no-existe.sql", tmp_path / "destino.db") is False


def test_restaurar_dos_veces_no_choca_con_las_tablas_de_la_vez_anterior(tmp_path):
    """Paso 6, mutación 2: ninguna prueba anterior deja `ruta_db` ya poblado.

    Todas apuntan a un archivo que nunca existió, así que quitar el borrado
    previo no las pone rojas: no hay nada que borrar. El caso real es el
    segundo ciclo horario, que restaura sobre la base que dejó el primero.
    Sin el borrado, el `CREATE TABLE` del volcado chocaría con las tablas que
    ya están ahí.
    """
    origen = _base_con_datos(tmp_path / "origen.db")
    sql = tmp_path / "volcado.sql"
    volcar(origen, sql)

    destino = tmp_path / "destino.db"
    assert restaurar(sql, destino) is True
    assert restaurar(sql, destino) is True

    con = abrir(destino)
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 3


def test_un_volcado_cortado_a_mitad_no_borra_lo_que_habia(tmp_path):
    """El fallo más caro de esta etapa: un volcado trunco pisando el histórico."""
    origen = _base_con_datos(tmp_path / "origen.db", cuantos=10)
    sql = tmp_path / "volcado.sql"
    volcar(origen, sql)
    origen.close()

    entero = sql.read_text(encoding="utf-8")
    sql.write_text(entero[: len(entero) // 2], encoding="utf-8")

    ruta_destino = tmp_path / "destino.db"
    destino = _base_con_datos(ruta_destino, cuantos=5)
    destino.close()

    assert restaurar(sql, ruta_destino) is False
    sobrevivio = abrir(ruta_destino)
    assert sobrevivio.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 5
    sobrevivio.close()
