from almacen.conexion import abrir
from fuentes.base import Captura
from nucleo.evaluador import Reglas
from runner import cargar_lista_deseos, ejecutar_ciclo

CONFIG = {
    "ejecucion": {"limite_por_busqueda": 15},
    "historico": {"ventana_minimo_dias": 90, "dias_minimos_para_descuento": 7},
    "alertas": {"cooldown_dias": 5},
}


class FuenteFalsa:
    def __init__(self, nombre, capturas, estalla=False):
        self.nombre = nombre
        self._capturas = capturas
        self._estalla = estalla

    def obtener(self, referencias):
        if self._estalla:
            raise RuntimeError("la tienda se cayó")
        return self._capturas

    def buscar(self, termino, limite):
        if self._estalla:
            raise RuntimeError("la tienda se cayó")
        return self._capturas


class NotificadorFalso:
    def __init__(self):
        self.enviados = []

    def enviar(self, captura, veredicto):
        self.enviados.append((captura, veredicto))


def captura(precio=89990, sku="S1", tienda="paris"):
    return Captura(
        tienda=tienda, sku_externo=sku, titulo="Notebook",
        url=f"https://www.{tienda}.cl/n-{sku}.html", precio_internet=precio,
    )


def vigilado(tienda="paris", sku="S1", tope=90000):
    return {
        "tienda": tienda,
        "url": f"https://www.{tienda}.cl/n-{sku}.html",
        "reglas": Reglas(precio_maximo=tope),
    }


def test_un_ciclo_guarda_y_avisa(tmp_path):
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    enviadas = ejecutar_ciclo(
        con, {"paris": FuenteFalsa("paris", [captura()])},
        [vigilado()], [], avisos, CONFIG,
    )
    assert enviadas == 1
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 1


def test_el_segundo_ciclo_no_duplica_nada(tmp_path):
    """El criterio de éxito nº 2 de la spec."""
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    fuentes = {"paris": FuenteFalsa("paris", [captura()])}

    ejecutar_ciclo(con, fuentes, [vigilado()], [], avisos, CONFIG)
    segundo = ejecutar_ciclo(con, fuentes, [vigilado()], [], avisos, CONFIG)

    assert segundo == 0
    assert len(avisos.enviados) == 1
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 1


def test_una_bajada_vuelve_a_avisar(tmp_path):
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    ejecutar_ciclo(con, {"paris": FuenteFalsa("paris", [captura(89990)])},
                   [vigilado()], [], avisos, CONFIG)
    ejecutar_ciclo(con, {"paris": FuenteFalsa("paris", [captura(79990)])},
                   [vigilado()], [], avisos, CONFIG)
    assert len(avisos.enviados) == 2


def test_una_tienda_caida_no_detiene_a_las_demas(tmp_path):
    """El criterio de éxito nº 4 y la prueba de robustez del plan original."""
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    fuentes = {
        "rota": FuenteFalsa("rota", [], estalla=True),
        "paris": FuenteFalsa("paris", [captura()]),
    }
    enviadas = ejecutar_ciclo(
        con, fuentes,
        [vigilado(tienda="rota"), vigilado(tienda="paris")],
        [], avisos, CONFIG,
    )
    assert enviadas == 1


def test_una_tienda_sin_fuente_no_estalla(tmp_path):
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    enviadas = ejecutar_ciclo(con, {}, [vigilado(tienda="desconocida")], [], avisos, CONFIG)
    assert enviadas == 0


def test_las_busquedas_tambien_capturan(tmp_path):
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    busquedas = [
        {"tienda": "paris", "termino": "notebook", "reglas": Reglas(precio_maximo=90000)}
    ]
    enviadas = ejecutar_ciclo(
        con, {"paris": FuenteFalsa("paris", [captura(sku="S9")])},
        [], busquedas, avisos, CONFIG,
    )
    assert enviadas == 1
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 1


def test_un_fallo_al_avisar_no_detiene_el_ciclo_ni_marca_la_alerta(tmp_path):
    """La spec: el dato no se pierde y el próximo ciclo reintenta."""
    con = abrir(tmp_path / "p.db")

    class NotificadorRoto:
        def enviar(self, captura, veredicto):
            raise RuntimeError("Telegram caído")

    enviadas = ejecutar_ciclo(
        con, {"paris": FuenteFalsa("paris", [captura()])},
        [vigilado()], [], NotificadorRoto(), CONFIG,
    )

    assert enviadas == 0
    assert con.execute("SELECT COUNT(*) FROM registro_alertas").fetchone()[0] == 0
    # El histórico sí se guardó: el dato no se pierde.
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 1


def test_una_regla_desconocida_se_salta_sin_abortar(tmp_path):
    """Una errata en el YAML cuesta ese producto, no el ciclo entero."""
    ruta = tmp_path / "lista.yaml"
    ruta.write_text(
        "vigilados:\n"
        "  - tienda: paris\n"
        "    url: https://www.paris.cl/bueno-S1.html\n"
        "    reglas:\n"
        "      precio_maximo: 1000\n"
        "  - tienda: paris\n"
        "    url: https://www.paris.cl/malo-S2.html\n"
        "    reglas:\n"
        "      descuento_inventado: 99\n",
        encoding="utf-8",
    )

    vigilados, busquedas = cargar_lista_deseos(ruta)

    assert len(vigilados) == 1
    assert vigilados[0]["url"].endswith("bueno-S1.html")
    assert busquedas == []


def test_una_entrada_sin_clave_obligatoria_se_salta_sin_abortar(tmp_path):
    """Como la regla desconocida: a una entrada le falta lo imprescindible y se salta sola."""
    ruta = tmp_path / "lista.yaml"
    ruta.write_text(
        "vigilados:\n"
        "  - tienda: paris\n"
        "    url: https://www.paris.cl/bueno-S1.html\n"
        "    reglas:\n"
        "      precio_maximo: 1000\n"
        "  - tienda: paris\n"
        "    reglas:\n"
        "      precio_maximo: 1000\n",
        encoding="utf-8",
    )

    vigilados, busquedas = cargar_lista_deseos(ruta)

    assert len(vigilados) == 1
    assert vigilados[0]["url"].endswith("bueno-S1.html")
    assert busquedas == []


def test_el_descuento_se_mide_contra_el_minimo_anterior_a_la_captura(tmp_path):
    """Si el mínimo se consultara tras guardar, hoy sería su propio mínimo.

    Fija el orden de `_procesar`: consultar el histórico ANTES de insertar la
    captura de hoy. Con el orden invertido el descuento saldría siempre 0 %.
    """
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    vigilado_con_descuento = {
        "tienda": "paris",
        "url": "https://www.paris.cl/n-S1.html",
        "reglas": Reglas(descuento_minimo_pct=15),
    }

    # Primer ciclo: deja el histórico en 100000, y se envejece 30 días para
    # superar la guarda de arranque en frío.
    ejecutar_ciclo(
        con, {"paris": FuenteFalsa("paris", [captura(100000)])},
        [vigilado_con_descuento], [], avisos, CONFIG,
    )
    con.execute("UPDATE historico_precios SET capturado_el = datetime('now', '-30 days')")

    # Segundo ciclo: 80000 es un 20 % por debajo de ese mínimo de 100000.
    enviadas = ejecutar_ciclo(
        con, {"paris": FuenteFalsa("paris", [captura(80000)])},
        [vigilado_con_descuento], [], avisos, CONFIG,
    )

    assert enviadas == 1
    assert avisos.enviados[-1][1].regla == "descuento_minimo_pct"
