import logging

import runner
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


def test_una_captura_que_falla_no_tumba_el_resto(tmp_path):
    """El criterio 4 de la spec: un fallo se registra y el ciclo continúa."""
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()

    buena = captura(sku="S1")
    rota = Captura(
        tienda="paris", sku_externo="S2", titulo="Rota",
        url=buena.url,  # misma URL que S1: viola el UNIQUE de productos.url
        precio_internet=50000,
    )

    enviadas = ejecutar_ciclo(
        con, {"paris": FuenteFalsa("paris", [rota, buena])},
        [vigilado()], [], avisos, CONFIG,
    )

    assert enviadas == 1
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 1


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


class FuenteConBusquedaInferida:
    """Devuelve capturas inferidas al buscar y exactas al pedir la ficha."""

    nombre = "falabella"

    def __init__(self, inferidas, exactas):
        self.inferidas = inferidas
        self.exactas = exactas
        self.fichas_pedidas = []

    def obtener(self, referencias):
        self.fichas_pedidas.extend(r.url for r in referencias)
        return [c for c in self.exactas if any(c.url == r.url for r in referencias)]

    def buscar(self, termino, limite):
        return list(self.inferidas)


def inferida(precio, sku="F1"):
    return Captura(
        tienda="falabella", sku_externo=sku, titulo="Notebook",
        url=f"https://www.falabella.com/falabella-cl/product/{sku}/x/{sku}",
        precio_internet=precio, precios_etiquetados=False,
    )


def exacta(precio, sku="F1"):
    return Captura(
        tienda="falabella", sku_externo=sku, titulo="Notebook",
        url=f"https://www.falabella.com/falabella-cl/product/{sku}/x/{sku}",
        precio_internet=precio,
    )


def exacta_no_etiquetada(precio, sku="F1"):
    """Como `exacta`, pero la ficha tampoco trae precios etiquetados.

    Para la próxima tienda (un catálogo como SoloTodo), donde la ficha puede
    confirmar sin etiquetar nada.
    """
    return Captura(
        tienda="falabella", sku_externo=sku, titulo="Notebook",
        url=f"https://www.falabella.com/falabella-cl/product/{sku}/x/{sku}",
        precio_internet=precio, precios_etiquetados=False,
    )


def busqueda(tope):
    return [{"tienda": "falabella", "termino": "notebook", "reglas": Reglas(precio_maximo=tope)}]


def test_una_captura_inferida_que_no_cumple_no_escribe_nada(tmp_path):
    """Ni alta, ni histórico, ni ficha: se descarta en el filtro barato."""
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    fuente = FuenteConBusquedaInferida([inferida(500000)], [exacta(500000)])

    enviadas = ejecutar_ciclo(con, {"falabella": fuente}, [], busqueda(100000), avisos, CONFIG)

    assert enviadas == 0
    assert fuente.fichas_pedidas == []
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 0


def test_una_captura_inferida_que_cumple_se_confirma_y_alerta_con_el_dato_exacto(tmp_path):
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    # La inferida dice 89990; la ficha dice 92000. Manda la ficha.
    fuente = FuenteConBusquedaInferida([inferida(89990)], [exacta(92000)])

    enviadas = ejecutar_ciclo(con, {"falabella": fuente}, [], busqueda(95000), avisos, CONFIG)

    assert enviadas == 1
    assert fuente.fichas_pedidas == [inferida(89990).url]   # exactamente una confirmación
    assert avisos.enviados[-1][1].precio == 92000
    fila = con.execute("SELECT precio_internet FROM historico_precios").fetchone()
    assert fila["precio_internet"] == 92000   # el histórico guarda el dato exacto


def test_si_la_confirmacion_falla_no_se_alerta_ni_se_escribe(tmp_path, caplog):
    """La ficha no da datos: se avisa y se descarta, sin escribir nada.

    Las dos aserciones sobre el log son las que dan valor a las demás: sin
    ellas, esta prueba pasaría igual con la guarda de `_confirmada` borrada,
    porque el `IndexError` resultante lo tragaría el `except` ancho de
    `_procesar` dejando el mismo estado observable.
    """
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    fuente = FuenteConBusquedaInferida([inferida(89990)], [])   # la ficha no devuelve nada

    with caplog.at_level(logging.WARNING, logger="rastreador"):
        enviadas = ejecutar_ciclo(con, {"falabella": fuente}, [], busqueda(95000), avisos, CONFIG)

    assert enviadas == 0
    assert fuente.fichas_pedidas == [inferida(89990).url]   # sí se intentó confirmar
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 0

    assert any("la ficha no dio datos" in m for m in caplog.messages)
    assert not any("no se pudo procesar" in m for m in caplog.messages)


def test_el_dato_exacto_deja_de_cumplir_y_no_se_alerta(tmp_path):
    """La inferida prometía 89990; la ficha dice 120000. No hay oferta."""
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    fuente = FuenteConBusquedaInferida([inferida(89990)], [exacta(120000)])

    enviadas = ejecutar_ciclo(con, {"falabella": fuente}, [], busqueda(95000), avisos, CONFIG)

    assert enviadas == 0
    assert fuente.fichas_pedidas == [inferida(89990).url]   # se confirmó de verdad
    assert avisos.enviados == []


def test_si_la_ficha_tampoco_trae_precios_etiquetados_no_se_alerta_ni_se_escribe(tmp_path):
    """El orquestador, no la tienda, debe exigir el etiquetado de la confirmación.

    Hoy ninguna tienda real produce este caso (Falabella marca `True` a mano y
    Paris nunca pasa por aquí), pero la próxima fuente (un catálogo como
    SoloTodo) sí podría devolver una ficha inferida. Sin esta guarda en
    `_confirmada`, ese precio adivinado entraría al histórico y podría alertar.
    """
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    fuente = FuenteConBusquedaInferida([inferida(89990)], [exacta_no_etiquetada(89990)])

    enviadas = ejecutar_ciclo(con, {"falabella": fuente}, [], busqueda(95000), avisos, CONFIG)

    assert enviadas == 0
    assert fuente.fichas_pedidas == [inferida(89990).url]   # sí se intentó confirmar
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 0


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


def test_una_entrada_puede_declarar_su_fuente(tmp_path):
    """Un producto de abcdin se captura con la fuente solotodo."""
    ruta = tmp_path / "lista.yaml"
    ruta.write_text(
        "vigilados:\n"
        "  - tienda: abcdin\n"
        "    fuente: solotodo\n"
        "    url: https://api.solotodo.com/entities/1379496/\n"
        "    reglas:\n"
        "      precio_maximo: 400000\n",
        encoding="utf-8",
    )
    vigilados, _ = cargar_lista_deseos(ruta)
    assert vigilados[0]["tienda"] == "abcdin"
    assert vigilados[0]["fuente"] == "solotodo"


def test_sin_fuente_declarada_la_fuente_es_la_tienda(tmp_path):
    """Todas las entradas que ya existían siguen funcionando sin tocarlas."""
    ruta = tmp_path / "lista.yaml"
    ruta.write_text(
        "busquedas:\n"
        "  - tienda: paris\n"
        "    termino: notebook\n"
        "    reglas:\n"
        "      precio_maximo: 400000\n",
        encoding="utf-8",
    )
    _, busquedas = cargar_lista_deseos(ruta)
    assert busquedas[0]["fuente"] == "paris"


def test_el_ciclo_usa_la_fuente_declarada_y_no_la_tienda(tmp_path):
    con = abrir(tmp_path / "p.db")
    avisos = NotificadorFalso()
    fuente = FuenteFalsa("solotodo", [captura(sku="S1", tienda="abcdin")])

    vigilado = {
        "tienda": "abcdin",
        "fuente": "solotodo",
        "url": "https://api.solotodo.com/entities/1/",
        "reglas": Reglas(precio_maximo=90000),
    }
    enviadas = ejecutar_ciclo(con, {"solotodo": fuente}, [vigilado], [], avisos, CONFIG)

    assert enviadas == 1


def test_una_seccion_solotodo_vacia_en_el_yaml_no_tumba_el_ciclo(tmp_path, monkeypatch):
    """`solotodo:` sin hijos en el YAML da `{"solotodo": None}`, no `{}`.

    `config.get("solotodo", {})` no usa el valor por defecto cuando la clave
    existe con valor `None`, así que `.get("tiendas_excluidas", [])` sobre ese
    `None` estalla con `AttributeError` antes de abrir la base: se pierde el
    ciclo entero por una sección vacía. El resto del proyecto tiene la
    disciplina contraria (`_reglas_de`, `_entrada_valida`): una errata en el
    YAML cuesta ese producto, no el ciclo.
    """
    config = {
        "ejecucion": {"reintentos": 1, "espera_entre_peticiones_seg": [0, 0], "limite_por_busqueda": 15},
        "historico": {"ventana_minimo_dias": 90, "dias_minimos_para_descuento": 7},
        "alertas": {"canal": "archivo", "cooldown_dias": 5, "ruta_archivo": "logs/alertas.jsonl"},
        "solotodo": None,   # la clave está, pero sin hijos
    }

    monkeypatch.setattr(runner, "RAIZ", tmp_path)
    monkeypatch.setattr(runner, "cargar_config", lambda ruta: config)
    monkeypatch.setattr(runner, "cargar_lista_deseos", lambda ruta: ([], []))

    assert runner.main() == 0
