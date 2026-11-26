import sqlite3

from almacen.conexion import abrir

# El esquema tal y como era ANTES de esta etapa. Se copia aquí a propósito: una
# prueba de migración que lea el esquema actual no prueba nada, porque migraría
# de la versión nueva a la versión nueva.
ESQUEMA_ANTERIOR = """
CREATE TABLE productos (
    id              INTEGER PRIMARY KEY,
    tienda          TEXT    NOT NULL,
    sku_externo     TEXT    NOT NULL,
    ean             TEXT,
    titulo          TEXT    NOT NULL,
    url             TEXT    NOT NULL UNIQUE,
    imagen_url      TEXT,
    creado_el       TEXT    NOT NULL DEFAULT (datetime('now')),
    ultima_revision TEXT,
    UNIQUE (tienda, sku_externo)
);
"""


def test_abrir_crea_las_tablas_y_activa_wal(tmp_path):
    con = abrir(tmp_path / "prueba.db")

    tablas = {
        f["name"]
        for f in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"productos", "historico_precios", "registro_alertas"} <= tablas

    modo = con.execute("PRAGMA journal_mode").fetchone()[0]
    assert modo.lower() == "wal"

    claves = con.execute("PRAGMA foreign_keys").fetchone()[0]
    assert claves == 1


def test_abrir_es_idempotente(tmp_path):
    ruta = tmp_path / "prueba.db"
    abrir(ruta)
    con = abrir(ruta)  # no debe estallar al reaplicar el esquema
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0


def test_una_base_anterior_gana_la_columna_sin_perder_sus_datos(tmp_path):
    """El caso que ninguna otra prueba puede ver.

    Todas las demás crean su base desde cero, donde `CREATE TABLE` ya trae la
    columna. Sobre una base que ya existe no llega nunca, y el único afectado
    sería el usuario con su histórico dentro.
    """
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    vieja.executescript(ESQUEMA_ANTERIOR)
    vieja.execute(
        "INSERT INTO productos (tienda, sku_externo, titulo, url)"
        " VALUES ('paris', 'S1', 'Notebook', 'https://www.paris.cl/n-S1.html')"
    )
    vieja.commit()
    vieja.close()

    con = abrir(ruta)

    columnas = {f["name"] for f in con.execute("PRAGMA table_info(productos)")}
    assert "producto_solotodo" in columnas

    fila = con.execute("SELECT tienda, sku_externo, titulo FROM productos").fetchone()
    assert (fila["tienda"], fila["sku_externo"], fila["titulo"]) == (
        "paris", "S1", "Notebook",
    )


def test_la_base_nueva_trae_la_columna_de_comparacion(tmp_path):
    """Una base creada hoy no necesita migración: la columna viene del esquema."""
    con = abrir(tmp_path / "nueva.db")
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(productos)")}
    assert "ultima_comparacion" in columnas


def test_una_base_sin_la_columna_de_comparacion_se_migra(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` no añade columnas a una tabla que ya existe."""
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    vieja.executescript(
        """
        CREATE TABLE productos (
            id                INTEGER PRIMARY KEY,
            tienda            TEXT    NOT NULL,
            sku_externo       TEXT    NOT NULL,
            ean               TEXT,
            producto_solotodo INTEGER,
            titulo            TEXT    NOT NULL,
            url               TEXT    NOT NULL UNIQUE,
            imagen_url        TEXT,
            creado_el         TEXT    NOT NULL DEFAULT (datetime('now')),
            ultima_revision   TEXT,
            UNIQUE (tienda, sku_externo)
        );
        INSERT INTO productos (tienda, sku_externo, titulo, url)
             VALUES ('paris', '123', 'Un notebook', 'https://ejemplo/1');
        """
    )
    vieja.commit()
    vieja.close()

    con = abrir(ruta)
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(productos)")}
    assert "ultima_comparacion" in columnas
    # Y la fila que ya estaba sigue ahí, con la columna nueva a nulo.
    fila = con.execute("SELECT sku_externo, ultima_comparacion FROM productos").fetchone()
    assert fila["sku_externo"] == "123"
    assert fila["ultima_comparacion"] is None


# El esquema anterior, con su histórico y sus alertas colgando de `productos`.
# Quitar la unicidad de `url` obliga a recrear la tabla —SQLite no sabe soltar
# una restricción—, y recrearla significa borrar la vieja con dos tablas
# apuntándola en cascada. De ahí que estas pruebas miren los hijos y no solo
# la columna.
ESQUEMA_ANTERIOR_CON_HIJOS = ESQUEMA_ANTERIOR + """
CREATE TABLE historico_precios (
    id               INTEGER PRIMARY KEY,
    producto_id      INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    precio_normal    INTEGER,
    precio_internet  INTEGER NOT NULL,
    precio_tarjeta   INTEGER,
    tarjeta_asociada TEXT,
    disponible       INTEGER NOT NULL DEFAULT 1,
    capturado_el     TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE registro_alertas (
    id                INTEGER PRIMARY KEY,
    producto_id       INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    regla             TEXT    NOT NULL,
    precio_notificado INTEGER NOT NULL,
    enviado_el        TEXT    NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO productos (id, tienda, sku_externo, titulo, url)
     VALUES (7, 'entel', 'PO_B_13928', 'iPhone 13 Semi 128GB',
             'https://miportal.entel.cl/personas/producto/prod1910048');
INSERT INTO historico_precios (producto_id, precio_internet) VALUES (7, 399990);
INSERT INTO historico_precios (producto_id, precio_internet) VALUES (7, 349990);
INSERT INTO registro_alertas (producto_id, regla, precio_notificado)
     VALUES (7, 'minimo_historico', 349990);
"""


def _base_anterior(ruta):
    vieja = sqlite3.connect(ruta)
    vieja.executescript(ESQUEMA_ANTERIOR_CON_HIJOS)
    vieja.commit()
    vieja.close()


def test_una_base_anterior_deja_de_exigir_la_url_unica(tmp_path):
    """El caso del usuario: dos SKU de Entel sobre la misma ficha."""
    ruta = tmp_path / "vieja.db"
    _base_anterior(ruta)

    con = abrir(ruta)
    con.execute(
        "INSERT INTO productos (tienda, sku_externo, titulo, url)"
        " VALUES ('entel', 'PO_B_13532', 'Vivo Y55 5G',"
        "         'https://miportal.entel.cl/personas/producto/prod1910048')"
    )

    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 2


def test_la_migracion_no_se_lleva_el_historico_por_delante(tmp_path):
    """Recrear `productos` borra la tabla vieja, y los hijos van en cascada.

    Si la migración se hace con las claves foráneas activas, el histórico
    entero —lo único que esta herramienta no puede recuperar— se va con ella.
    """
    ruta = tmp_path / "vieja.db"
    _base_anterior(ruta)

    con = abrir(ruta)

    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM registro_alertas").fetchone()[0] == 1
    fila = con.execute("SELECT id, tienda, sku_externo, titulo FROM productos").fetchone()
    assert (fila["id"], fila["tienda"], fila["sku_externo"]) == (7, "entel", "PO_B_13928")


def test_la_migracion_conserva_la_identidad_por_tienda_y_sku(tmp_path):
    """Quitar la unicidad de `url` no puede llevarse la que sí importa.

    Sin `UNIQUE (tienda, sku_externo)` el upsert de `alta_o_actualiza_producto`
    no tiene a qué agarrarse y cada pasada daría de alta el producto otra vez.
    """
    ruta = tmp_path / "vieja.db"
    _base_anterior(ruta)

    con = abrir(ruta)

    try:
        con.execute(
            "INSERT INTO productos (tienda, sku_externo, titulo, url)"
            " VALUES ('entel', 'PO_B_13928', 'Repetido', 'https://otra/ficha')"
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("se aceptó un (tienda, sku_externo) repetido")


def test_la_migracion_deja_las_claves_de_los_hijos_apuntando_bien(tmp_path):
    """Renombrar una tabla reescribe las REFERENCES que la señalan.

    Sin `legacy_alter_table`, los hijos acaban apuntando a
    `productos_anterior` —justo la tabla que la migración borra después— y la
    base queda con las claves rotas sin que nada estalle en ese momento. Se
    descubre semanas más tarde, cuando un borrado en cascada no encuentra a
    quién cascadear.
    """
    ruta = tmp_path / "vieja.db"
    _base_anterior(ruta)

    con = abrir(ruta)

    apuntadas = {
        f["table"]
        for tabla in ("historico_precios", "registro_alertas")
        for f in con.execute(f"PRAGMA foreign_key_list({tabla})")
    }
    assert apuntadas == {"productos"}
    assert list(con.execute("PRAGMA foreign_key_check")) == []
