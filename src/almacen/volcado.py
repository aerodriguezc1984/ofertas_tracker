"""El histórico, en un archivo de texto que sobrevive a la máquina.

En la nube cada ejecución arranca en un equipo nuevo, así que la base tiene que
viajar con el repositorio. Viaja como SQL y no como archivo `.db` por dos
motivos: git no sabe comprimir SQLite —cualquier cambio reescribe páginas
dispersas y el archivo entero cuenta como contenido nuevo— y un volcado en texto
se puede leer y arreglar a mano el día que algo se corrompa.
"""

import sqlite3
from pathlib import Path

# Medido el 2026-10-11 con una base recién abierta (solo `abrir()`, sin
# ninguna captura): `len(list(con.iterdump()))` da 7 sentencias —3 CREATE
# TABLE, 2 CREATE INDEX y el BEGIN/COMMIT que envuelve el volcado—, igual al
# conteo de ";" que usa la guarda de abajo. El umbral queda en 8: por encima
# de las 7 del esquema vacío (lo descarta con un punto de margen), y por
# debajo de las 9 que deja un solo producto con una sola lectura (dos INSERT
# más), que es el volcado real más pequeño que existe y tiene que pasar. No
# hay más margen posible: subir el umbral descartaría en silencio ese caso.
SENTENCIAS_DE_UN_ESQUEMA_VACIO = 8


def volcar(con: sqlite3.Connection, ruta_sql: Path | str) -> int:
    """Escribe la base entera como SQL. Devuelve cuántas sentencias salieron."""
    ruta_sql = Path(ruta_sql)
    ruta_sql.parent.mkdir(parents=True, exist_ok=True)

    sentencias = list(con.iterdump())
    ruta_sql.write_text("\n".join(sentencias) + "\n", encoding="utf-8")
    return len(sentencias)


def restaurar(ruta_sql: Path | str, ruta_db: Path | str) -> bool:
    """Crea la base desde el volcado. Devuelve si de verdad restauró algo.

    NO restaura un volcado vacío o que solo traiga el esquema. Ese es el
    resultado de un ciclo que falló a mitad, y escribirlo encima borraría el
    histórico: perder una hora de capturas es recuperable, perder la base
    entera no.

    Tampoco restaura un volcado cortado a mitad: se construye en un archivo
    aparte y solo se mueve encima del destino si el script entero se ejecutó.
    """
    ruta_sql, ruta_db = Path(ruta_sql), Path(ruta_db)
    if not ruta_sql.exists():
        return False

    sql = ruta_sql.read_text(encoding="utf-8")
    if sql.count(";") < SENTENCIAS_DE_UN_ESQUEMA_VACIO:
        return False

    ruta_db.parent.mkdir(parents=True, exist_ok=True)

    # Se construye aparte y solo se mueve encima si el script terminó entero. Un
    # volcado cortado a mitad de escritura pasa la guarda de arriba sin problema
    # —con datos reales sobra el umbral mucho antes del corte—, así que lo único
    # que impide que se lleve por delante el histórico es no haberlo tocado
    # todavía cuando `executescript` revienta.
    a_medias = ruta_db.with_name(ruta_db.name + ".restaurando")
    a_medias.unlink(missing_ok=True)

    con = sqlite3.connect(a_medias, isolation_level=None)
    try:
        con.executescript(sql)
    except sqlite3.DatabaseError:
        entero = False
    else:
        entero = True
    finally:
        con.close()

    if not entero:
        a_medias.unlink(missing_ok=True)
        return False

    a_medias.replace(ruta_db)
    return True
