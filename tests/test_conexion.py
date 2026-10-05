from almacen.conexion import abrir


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
