"""Apertura de la base de datos SQLite."""

import sqlite3
from pathlib import Path

ESQUEMA = Path(__file__).parent / "esquema.sql"

# Columnas añadidas después de la primera versión del esquema. `CREATE TABLE IF
# NOT EXISTS` no las lleva a una base que ya existe, así que hay que añadirlas a
# mano. Formato: (tabla, columna, declaración).
#
# Disciplina pura, sin red de seguridad: toda prueba crea la base desde cero,
# así que ninguna vigila que una columna nueva del esquema también se añada
# aquí. Y la declaración tiene un límite real: `ALTER TABLE ... ADD COLUMN` no
# admite `UNIQUE`, y solo admite `NOT NULL` si lleva `DEFAULT` —comprobado: sin
# `DEFAULT` se acepta sobre una tabla vacía y se rechaza sobre una con filas—,
# así que una declaración mal formada pasaría la suite entera y solo
# reventaría sobre la base real del usuario.
COLUMNAS_NUEVAS = [
    ("productos", "producto_solotodo", "INTEGER"),
    ("productos", "ultima_comparacion", "TEXT"),
]


def _migrar(con: sqlite3.Connection) -> None:
    """Añade a una base anterior las columnas que su esquema no tenía.

    Los nombres de tabla y columna no se pueden parametrizar en SQL, así que se
    interpolan — son literales de `COLUMNAS_NUEVAS`, escritos aquí, nunca datos
    de fuera.
    """
    for tabla, columna, declaracion in COLUMNAS_NUEVAS:
        presentes = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
        if columna not in presentes:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {declaracion}")


def _url_es_unica(con: sqlite3.Connection) -> bool:
    """Si la base arrastra el índice implícito de un `url TEXT ... UNIQUE`.

    Sobre una base recién creada la tabla no existe todavía y el PRAGMA
    devuelve cero filas, que es la respuesta correcta: no hay nada que migrar.
    """
    for indice in con.execute("PRAGMA index_list(productos)"):
        if indice["origin"] != "u":
            continue
        columnas = [
            c["name"] for c in con.execute(f"PRAGMA index_info({indice['name']})")
        ]
        if columnas == ["url"]:
            return True
    return False


def _soltar_unicidad_de_url(con: sqlite3.Connection, esquema: str) -> None:
    """Rehace `productos` sin la unicidad de `url` en una base anterior.

    SQLite no sabe soltar una restricción: hay que crear la tabla otra vez y
    traspasar las filas. Tres cuidados, y los tres tienen su prueba en
    `tests/test_conexion.py`:

    - `foreign_keys = OFF`. `historico_precios` y `registro_alertas` cuelgan de
      `productos` con ON DELETE CASCADE. Borrar la tabla vieja con las claves
      activas se lleva el histórico entero, que es lo único que esta
      herramienta no puede volver a capturar.
    - `legacy_alter_table = ON` para el renombrado. Sin eso SQLite reescribe
      las REFERENCES de los hijos apuntándolas al nombre nuevo, y acabarían
      señalando justo a la tabla que vamos a borrar.
    - Se copian solo las columnas comunes: una base de la primera versión no
      tiene `producto_solotodo` ni `ultima_comparacion`.

    No va envuelta en una transacción porque `executescript` confirma por su
    cuenta. Si se cortara a mitad, las filas seguirían en `productos_anterior`:
    por eso se hace copia de la base antes de correr esto sobre la real.
    """
    if not _url_es_unica(con):
        return

    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("PRAGMA legacy_alter_table = ON")
    con.execute("ALTER TABLE productos RENAME TO productos_anterior")
    con.execute("PRAGMA legacy_alter_table = OFF")

    con.executescript(esquema)  # crea `productos` ya sin la unicidad

    viejas = {f["name"] for f in con.execute("PRAGMA table_info(productos_anterior)")}
    comunes = ", ".join(
        f["name"]
        for f in con.execute("PRAGMA table_info(productos)")
        if f["name"] in viejas
    )
    con.execute(
        f"INSERT INTO productos ({comunes}) SELECT {comunes} FROM productos_anterior"
    )
    con.execute("DROP TABLE productos_anterior")
    con.execute("PRAGMA foreign_keys = ON")


def abrir(ruta: Path | str) -> sqlite3.Connection:
    """Abre la base en modo WAL y deja el esquema aplicado.

    El modo WAL permite leer mientras se escribe, que es lo que necesita un
    proceso que captura y consulta a la vez. `isolation_level = None` deja el
    control de las transacciones en nuestras manos en vez de en las del
    envoltorio de Python.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(ruta, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")

    esquema = ESQUEMA.read_text(encoding="utf-8")
    _soltar_unicidad_de_url(con, esquema)
    con.executescript(esquema)
    _migrar(con)
    return con
