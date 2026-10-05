from almacen.conexion import abrir
from almacen.operaciones import alta_o_actualiza_producto, registrar_alerta
from fuentes.base import Captura
from nucleo.frecuencia import debe_notificar


def base(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(
        con,
        Captura(
            tienda="paris", sku_externo="S1", titulo="N",
            url="https://www.paris.cl/n-S1.html", precio_internet=100000,
        ),
    )
    return con, pid


def envejecer(con, pid, dias):
    con.execute(
        "UPDATE registro_alertas SET enviado_el = datetime('now', ?) WHERE producto_id = ?",
        (f"-{dias} days", pid),
    )


def test_la_primera_vez_siempre_avisa(tmp_path):
    con, pid = base(tmp_path)
    assert debe_notificar(con, pid, "precio_maximo", 89990, 5) is True


def test_el_mismo_precio_no_vuelve_a_avisar(tmp_path):
    con, pid = base(tmp_path)
    registrar_alerta(con, pid, "precio_maximo", 89990)
    assert debe_notificar(con, pid, "precio_maximo", 89990, 5) is False


def test_un_precio_mas_alto_no_avisa(tmp_path):
    con, pid = base(tmp_path)
    registrar_alerta(con, pid, "precio_maximo", 89990)
    assert debe_notificar(con, pid, "precio_maximo", 92000, 5) is False


def test_una_bajada_vuelve_a_avisar(tmp_path):
    con, pid = base(tmp_path)
    registrar_alerta(con, pid, "precio_maximo", 89990)
    assert debe_notificar(con, pid, "precio_maximo", 84990, 5) is True


def test_pasado_el_descanso_recuerda_la_oferta(tmp_path):
    con, pid = base(tmp_path)
    registrar_alerta(con, pid, "precio_maximo", 89990)
    envejecer(con, pid, 6)
    assert debe_notificar(con, pid, "precio_maximo", 89990, 5) is True


def test_cada_regla_lleva_su_propia_cuenta(tmp_path):
    con, pid = base(tmp_path)
    registrar_alerta(con, pid, "precio_maximo", 89990)
    assert debe_notificar(con, pid, "descuento_minimo_pct", 89990, 5) is True
