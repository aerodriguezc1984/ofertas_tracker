# Etapa 1 — El esqueleto que camina: plan de implementación

> **Para agentes ejecutores:** SUB-SKILL OBLIGATORIA: usa
> `superpowers:subagent-driven-development` (recomendada) o
> `superpowers:executing-plans` para ejecutar este plan tarea a tarea. Los pasos
> usan casillas (`- [ ]`) para el seguimiento.

**Objetivo:** un rastreador que vigile productos de Paris —por lista de deseos y por
búsqueda de palabra clave—, guarde el histórico de variaciones de precio, evalúe reglas y
avise una sola vez por oferta.

**Arquitectura:** una fuente por plataforma detrás de un protocolo común (`Fuente`), que
devuelve siempre el mismo objeto `Captura`. Paris se lee raspando el HTML: el JSON-LD de
la ficha da nombre, SKU y precio; la página de búsqueda da las URLs. El núcleo (almacén,
evaluador, avisos) no sabe de HTTP ni de qué tienda vienen los datos.

**Tecnologías:** Python 3.12, SQLite en modo WAL, `requests`, `PyYAML`, `python-dotenv`,
`pytest`. Sin framework de scraping, sin navegador, sin evasión.

**Spec:** `docs/specs/2026-10-04-esqueleto-design.md`

## Restricciones globales

- Python 3.12 (`python --version` → 3.12.10 en esta máquina).
- Dependencias permitidas: `requests`, `PyYAML`, `python-dotenv`, `pytest`. Nada más sin
  discutirlo.
- **Todo el código, los nombres y los comentarios en español.** Los mensajes de commit,
  también.
- **El dinero es `int` de pesos chilenos.** Ningún `float` toca un precio.
- **Ninguna prueba accede a la red.** Las fuentes reciben su transporte por inyección; las
  pruebas pasan uno falso.
- **Sin evasión de anti-bot.** Una cabecera `User-Agent` honesta y descriptiva, pausa de 2
  a 5 segundos entre peticiones, y si una tienda bloquea se registra y se sigue.
- Fechas en SQLite como texto ISO en UTC, vía `datetime('now')`.
- `.env` nunca se versiona. Ningún secreto aparece en logs ni en mensajes de error.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `pyproject.toml` | dependencias y configuración de pytest (`pythonpath = ["src"]`) |
| `src/almacen/esquema.sql` | las tres tablas y sus índices |
| `src/almacen/conexion.py` | abrir SQLite en WAL y aplicar el esquema |
| `src/almacen/operaciones.py` | alta de producto, registro de cambio, mínimo histórico, alertas |
| `src/fuentes/base.py` | `Captura`, `Referencia`, protocolo `Fuente`, tipo `Transporte` |
| `src/fuentes/transporte.py` | el transporte HTTP real, con reintentos y pausas |
| `src/fuentes/paris.py` | `obtener()` y `buscar()` sobre paris.cl |
| `src/nucleo/normalizador.py` | HTML → `Captura` leyendo el JSON-LD |
| `src/nucleo/evaluador.py` | reglas de precio y descuento, guarda de arranque en frío |
| `src/nucleo/frecuencia.py` | decide si una oferta ya avisada se vuelve a avisar |
| `src/avisos/base.py` | protocolo `Notificador` y redacción del mensaje |
| `src/avisos/archivo.py` | escribe `logs/alertas.jsonl` |
| `src/avisos/telegram.py` | envía por la API de Telegram |
| `runner.py` | orquesta el ciclo completo |

Cada módulo se prueba solo. `nucleo` no importa `requests`; `fuentes` no importa `sqlite3`.

---

### Tarea 1: Andamiaje y almacén

**Archivos:**
- Crear: `pyproject.toml`, `requirements.txt`, `.env.example`
- Crear: `src/almacen/esquema.sql`, `src/almacen/conexion.py`
- Crear: `src/almacen/__init__.py`, `src/fuentes/__init__.py`, `src/nucleo/__init__.py`, `src/avisos/__init__.py`
- Prueba: `tests/test_conexion.py`

**Interfaces:**
- Consume: nada.
- Produce: `almacen.conexion.abrir(ruta: Path | str) -> sqlite3.Connection`, con el esquema
  ya aplicado, `row_factory = sqlite3.Row` y claves foráneas activas.

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_conexion.py
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
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_conexion.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'almacen'`.

- [ ] **Paso 3: Escribir la implementación mínima**

```toml
# pyproject.toml
[project]
name = "ofertas-tracker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["requests", "PyYAML", "python-dotenv"]

[tool.pytest.ini_options]
pythonpath = ["src", "."]
testpaths = ["tests"]
```

`requirements.txt`:

```
requests
PyYAML
python-dotenv
pytest
```

```sql
-- src/almacen/esquema.sql
CREATE TABLE IF NOT EXISTS productos (
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

CREATE TABLE IF NOT EXISTS historico_precios (
    id               INTEGER PRIMARY KEY,
    producto_id      INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    precio_normal    INTEGER,
    precio_internet  INTEGER NOT NULL,
    precio_tarjeta   INTEGER,
    tarjeta_asociada TEXT,
    disponible       INTEGER NOT NULL DEFAULT 1,
    capturado_el     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS registro_alertas (
    id                INTEGER PRIMARY KEY,
    producto_id       INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    regla             TEXT    NOT NULL,
    precio_notificado INTEGER NOT NULL,
    enviado_el        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_hist_prod_fecha
    ON historico_precios (producto_id, capturado_el DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_prod_regla
    ON registro_alertas (producto_id, regla, enviado_el DESC);
```

```python
# src/almacen/conexion.py
"""Apertura de la base de datos SQLite."""

import sqlite3
from pathlib import Path

ESQUEMA = Path(__file__).parent / "esquema.sql"


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
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    return con
```

Crea además los cuatro `__init__.py` vacíos y `.env.example`:

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_conexion.py -v`
Esperado: 2 pasadas.

- [ ] **Paso 5: Commit**

```bash
git add pyproject.toml requirements.txt .env.example src tests
git commit -m "Almacén: apertura de SQLite en modo WAL con el esquema aplicado"
```

---

### Tarea 2: Alta de producto e histórico de variaciones

**Archivos:**
- Crear: `src/almacen/operaciones.py`, `src/fuentes/base.py`
- Prueba: `tests/test_operaciones.py`

**Interfaces:**
- Consume: `almacen.conexion.abrir`.
- Produce:
  - `fuentes.base.Captura` (dataclass congelada, campos abajo)
  - `fuentes.base.Referencia` (dataclass congelada: `tienda`, `url`, `sku_externo=None`)
  - `fuentes.base.Transporte = Callable[[str], str]`
  - `almacen.operaciones.alta_o_actualiza_producto(con, captura) -> int`
  - `almacen.operaciones.registrar_si_cambio(con, producto_id, captura) -> bool`

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_operaciones.py
from almacen.conexion import abrir
from almacen.operaciones import alta_o_actualiza_producto, registrar_si_cambio
from fuentes.base import Captura


def captura(precio=100000, disponible=True, sku="SKU1"):
    return Captura(
        tienda="paris",
        sku_externo=sku,
        titulo="Notebook de prueba",
        url=f"https://www.paris.cl/notebook-{sku}.html",
        precio_internet=precio,
        precio_normal=None,
        precio_tarjeta=None,
        tarjeta=None,
        disponible=disponible,
    )


def test_el_alta_no_duplica_el_producto(tmp_path):
    con = abrir(tmp_path / "p.db")
    primero = alta_o_actualiza_producto(con, captura())
    segundo = alta_o_actualiza_producto(con, captura())
    assert primero == segundo
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 1


def test_el_historico_no_crece_si_nada_cambia(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, captura())

    assert registrar_si_cambio(con, pid, captura()) is True
    assert registrar_si_cambio(con, pid, captura()) is False

    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 1


def test_el_historico_crece_si_cambia_el_precio(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, captura(precio=100000))
    registrar_si_cambio(con, pid, captura(precio=100000))

    assert registrar_si_cambio(con, pid, captura(precio=89990)) is True
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 2


def test_el_historico_crece_si_cambia_la_disponibilidad(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, captura())
    registrar_si_cambio(con, pid, captura())

    assert registrar_si_cambio(con, pid, captura(disponible=False)) is True
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 2


def test_el_alta_anota_la_revision(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, captura())
    fila = con.execute(
        "SELECT ultima_revision FROM productos WHERE id = ?", (pid,)
    ).fetchone()
    assert fila["ultima_revision"] is not None
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_operaciones.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'almacen.operaciones'`.

- [ ] **Paso 3: Escribir la implementación mínima**

```python
# src/fuentes/base.py
"""El contrato que cumple toda fuente, venga de donde venga el dato."""

from dataclasses import dataclass
from typing import Callable, Protocol

# Una fuente no habla HTTP directamente: recibe una función que, dada una URL,
# devuelve el cuerpo como texto. Así las pruebas no tocan la red.
Transporte = Callable[[str], str]


@dataclass(frozen=True)
class Captura:
    """Una lectura de precio ya normalizada. Todos los precios en CLP enteros."""

    tienda: str
    sku_externo: str
    titulo: str
    url: str
    precio_internet: int
    precio_normal: int | None = None
    precio_tarjeta: int | None = None
    tarjeta: str | None = None
    disponible: bool = True
    imagen_url: str | None = None
    ean: str | None = None


@dataclass(frozen=True)
class Referencia:
    """Lo que la lista de deseos entrega a una fuente: qué mirar y dónde."""

    tienda: str
    url: str
    sku_externo: str | None = None


class Fuente(Protocol):
    nombre: str

    def obtener(self, referencias: list[Referencia]) -> list[Captura]: ...

    def buscar(self, termino: str, limite: int) -> list[Captura]: ...
```

```python
# src/almacen/operaciones.py
"""Escrituras y consultas sobre la base. Nadie más toca SQL."""

import sqlite3

from fuentes.base import Captura


def alta_o_actualiza_producto(con: sqlite3.Connection, captura: Captura) -> int:
    """Devuelve el id del producto, dándolo de alta si es nuevo.

    La identidad del producto es el par (tienda, sku_externo). El título y la
    imagen se refrescan en cada pasada porque las tiendas los cambian.
    """
    con.execute(
        """
        INSERT INTO productos (tienda, sku_externo, titulo, url, imagen_url, ean,
                               ultima_revision)
             VALUES (:tienda, :sku, :titulo, :url, :imagen, :ean, datetime('now'))
        ON CONFLICT (tienda, sku_externo) DO UPDATE SET
                titulo          = excluded.titulo,
                imagen_url      = COALESCE(excluded.imagen_url, productos.imagen_url),
                ean             = COALESCE(excluded.ean, productos.ean),
                ultima_revision = datetime('now')
        """,
        {
            "tienda": captura.tienda,
            "sku": captura.sku_externo,
            "titulo": captura.titulo,
            "url": captura.url,
            "imagen": captura.imagen_url,
            "ean": captura.ean,
        },
    )
    fila = con.execute(
        "SELECT id FROM productos WHERE tienda = ? AND sku_externo = ?",
        (captura.tienda, captura.sku_externo),
    ).fetchone()
    return fila["id"]


def registrar_si_cambio(
    con: sqlite3.Connection, producto_id: int, captura: Captura
) -> bool:
    """Inserta en el histórico solo si algo cambió. Devuelve si insertó.

    El histórico es un registro de VARIACIONES, no de pasadas: insertar una fila
    por ejecución entierra los cambios reales bajo miles de filas idénticas.
    """
    ultima = con.execute(
        """
        SELECT precio_internet, precio_normal, precio_tarjeta, disponible
          FROM historico_precios
         WHERE producto_id = ?
         ORDER BY capturado_el DESC, id DESC
         LIMIT 1
        """,
        (producto_id,),
    ).fetchone()

    nuevo = (
        captura.precio_internet,
        captura.precio_normal,
        captura.precio_tarjeta,
        int(captura.disponible),
    )
    if ultima is not None and tuple(ultima) == nuevo:
        return False

    con.execute(
        """
        INSERT INTO historico_precios (producto_id, precio_internet, precio_normal,
                                       precio_tarjeta, tarjeta_asociada, disponible)
             VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            producto_id,
            captura.precio_internet,
            captura.precio_normal,
            captura.precio_tarjeta,
            captura.tarjeta,
            int(captura.disponible),
        ),
    )
    return True
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_operaciones.py -v`
Esperado: 5 pasadas.

- [ ] **Paso 5: Commit**

```bash
git add src/fuentes/base.py src/almacen/operaciones.py tests/test_operaciones.py
git commit -m "Almacén: alta idempotente de producto e histórico de variaciones"
```

---

### Tarea 3: El mínimo histórico y su ventana

Aquí es donde una implementación ingenua pasa desapercibida. Si el precio se fijó hace 100
días y no ha cambiado, no hay **ninguna** fila dentro de la ventana de 90 días, y un
`MIN(...) WHERE capturado_el >= ...` devuelve `NULL`. El mínimo correcto incluye además la
última fila anterior al inicio de la ventana: el precio que estaba vigente al abrirse.

**Archivos:**
- Modificar: `src/almacen/operaciones.py`
- Prueba: `tests/test_minimo_historico.py`

**Interfaces:**
- Consume: `alta_o_actualiza_producto`, `Captura`.
- Produce:
  - `almacen.operaciones.minimo_historico(con, producto_id, ventana_dias) -> int | None`
  - `almacen.operaciones.dias_de_historico(con, producto_id) -> float`

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_minimo_historico.py
from almacen.conexion import abrir
from almacen.operaciones import (
    alta_o_actualiza_producto,
    dias_de_historico,
    minimo_historico,
)
from fuentes.base import Captura


def producto(con):
    c = Captura(
        tienda="paris",
        sku_externo="SKU1",
        titulo="Notebook",
        url="https://www.paris.cl/notebook-SKU1.html",
        precio_internet=100000,
    )
    return alta_o_actualiza_producto(con, c)


def fila(con, pid, precio, hace_dias):
    con.execute(
        """
        INSERT INTO historico_precios (producto_id, precio_internet, capturado_el)
             VALUES (?, ?, datetime('now', ?))
        """,
        (pid, precio, f"-{hace_dias} days"),
    )


def test_sin_historico_devuelve_none(tmp_path):
    con = abrir(tmp_path / "p.db")
    assert minimo_historico(con, producto(con), 90) is None


def test_toma_el_menor_dentro_de_la_ventana(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = producto(con)
    fila(con, pid, 100000, 30)
    fila(con, pid, 89990, 10)
    assert minimo_historico(con, pid, 90) == 89990


def test_cuenta_el_precio_vigente_aunque_la_ventana_tenga_filas(tmp_path):
    """El precio viejo siguió vigente dentro de la ventana, así que cuenta.

    Entre el día 200 y el día 30 el precio fue 50000, y los días 90 a 30 caen
    dentro de la ventana: 50000 es de verdad el mínimo vigente en esos 90 días.
    """
    con = abrir(tmp_path / "p.db")
    pid = producto(con)
    fila(con, pid, 50000, 200)
    fila(con, pid, 100000, 30)
    assert minimo_historico(con, pid, 90) == 50000


def test_usa_el_precio_vigente_al_abrirse_la_ventana(tmp_path):
    """El caso que rompe la implementación ingenua.

    El precio se fijó hace 150 días y nunca cambió: no hay filas dentro de la
    ventana de 90, pero el producto SÍ tiene un precio conocido.
    """
    con = abrir(tmp_path / "p.db")
    pid = producto(con)
    fila(con, pid, 120000, 150)
    assert minimo_historico(con, pid, 90) == 120000


def test_dias_de_historico_mide_desde_la_primera_fila(tmp_path):
    con = abrir(tmp_path / "p.db")
    pid = producto(con)
    fila(con, pid, 100000, 10)
    assert 9.5 < dias_de_historico(con, pid) < 10.5


def test_dias_de_historico_sin_filas_es_cero(tmp_path):
    con = abrir(tmp_path / "p.db")
    assert dias_de_historico(con, producto(con)) == 0.0
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_minimo_historico.py -v`
Esperado: FALLA con `ImportError: cannot import name 'minimo_historico'`.

Antes de implementar, comprueba a propósito que la versión ingenua falla: escribe primero
el `MIN` sin el `UNION ALL` y verifica que `test_usa_el_precio_vigente_al_abrirse_la_ventana`
falla. Si pasa igualmente, la prueba está mal escrita y no mide lo que dice medir.

- [ ] **Paso 3: Escribir la implementación mínima**

```python
# añadir al final de src/almacen/operaciones.py


def minimo_historico(
    con: sqlite3.Connection, producto_id: int, ventana_dias: int
) -> int | None:
    """El precio más bajo vigente en los últimos `ventana_dias` días.

    No basta con mirar las filas dentro de la ventana: como solo se guardan
    variaciones, un precio fijado antes del inicio de la ventana y nunca
    cambiado no tiene ninguna fila dentro, y aun así es el precio vigente. Por
    eso se une la última fila anterior al corte.
    """
    ventana = f"-{int(ventana_dias)} days"
    fila = con.execute(
        """
        SELECT MIN(p) AS minimo FROM (
            SELECT precio_internet AS p
              FROM historico_precios
             WHERE producto_id = :pid
               AND capturado_el >= datetime('now', :ventana)
            UNION ALL
            SELECT p FROM (
                SELECT precio_internet AS p
                  FROM historico_precios
                 WHERE producto_id = :pid
                   AND capturado_el < datetime('now', :ventana)
                 ORDER BY capturado_el DESC, id DESC
                 LIMIT 1
            )
        )
        """,
        {"pid": producto_id, "ventana": ventana},
    ).fetchone()
    return fila["minimo"]


def dias_de_historico(con: sqlite3.Connection, producto_id: int) -> float:
    """Cuántos días hace que se vigila este producto. Cero si no hay histórico."""
    fila = con.execute(
        """
        SELECT (julianday('now') - julianday(MIN(capturado_el))) AS dias
          FROM historico_precios
         WHERE producto_id = ?
        """,
        (producto_id,),
    ).fetchone()
    return float(fila["dias"]) if fila["dias"] is not None else 0.0
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_minimo_historico.py -v`
Esperado: 6 pasadas.

- [ ] **Paso 5: Commit**

```bash
git add src/almacen/operaciones.py tests/test_minimo_historico.py
git commit -m "Almacén: mínimo histórico contando el precio vigente al abrir la ventana"
```

---

### Tarea 4: El normalizador — del HTML a una Captura

**Archivos:**
- Crear: `src/nucleo/normalizador.py`
- Crear: `tests/fixtures/paris_ficha.html`, `tests/fixtures/paris_ficha_sin_precio.html`
- Prueba: `tests/test_normalizador.py`

Las *fixtures* son recortes: la ficha real de Paris pesa 2 MB y no tiene sentido
versionarla. Se guarda una página mínima que contiene **el bloque JSON-LD real**, copiado
tal cual de la ficha `home-panel-monaco-tv-55-1-6-castano-off-white-MK2GCAHDUR` de
paris.cl, verificada el 2026-10-04.

**Interfaces:**
- Consume: `fuentes.base.Captura`.
- Produce:
  - `nucleo.normalizador.bloques_ld_json(html: str) -> list[dict]`
  - `nucleo.normalizador.a_captura(html: str, url: str, tienda: str) -> Captura | None`

- [ ] **Paso 1: Escribir las fixtures y la prueba que falla**

```html
<!-- tests/fixtures/paris_ficha.html -->
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"Paris"}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Home Panel Mónaco Tv 55 1 6 castaño off White",
 "sku":"MK2GCAHDUR",
 "image":"https://cdn.paris.cl/monaco.jpg",
 "offers":{"@type":"Offer","price":229990,"priceCurrency":"CLP"}}
</script>
</head><body></body></html>
```

```html
<!-- tests/fixtures/paris_ficha_sin_precio.html -->
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Producto agotado","sku":"SINPRECIO",
 "offers":{"@type":"Offer","priceCurrency":"CLP"}}
</script>
</head><body></body></html>
```

```python
# tests/test_normalizador.py
from pathlib import Path

import pytest

from nucleo.normalizador import a_captura, bloques_ld_json

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.paris.cl/home-panel-monaco-MK2GCAHDUR.html"


def leer(nombre):
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def test_encuentra_todos_los_bloques():
    assert len(bloques_ld_json(leer("paris_ficha.html"))) == 2


def test_extrae_la_captura_de_una_ficha_real():
    c = a_captura(leer("paris_ficha.html"), URL, "paris")
    assert c is not None
    assert c.tienda == "paris"
    assert c.sku_externo == "MK2GCAHDUR"
    assert c.titulo == "Home Panel Mónaco Tv 55 1 6 castaño off White"
    assert c.precio_internet == 229990
    assert isinstance(c.precio_internet, int)
    assert c.url == URL
    assert c.imagen_url == "https://cdn.paris.cl/monaco.jpg"
    assert c.disponible is True


def test_sin_precio_no_hay_captura():
    """Devolver un cero sería inventarse una oferta."""
    assert a_captura(leer("paris_ficha_sin_precio.html"), URL, "paris") is None


def test_sin_bloque_de_producto_no_hay_captura():
    html = '<html><script type="application/ld+json">{"@type":"WebPage"}</script></html>'
    assert a_captura(html, URL, "paris") is None


def test_el_json_ilegible_no_estalla():
    html = '<html><script type="application/ld+json">{esto no es json</script></html>'
    assert bloques_ld_json(html) == []


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("229990", 229990),
        ('"229990"', 229990),
        ('"229990.00"', 229990),
        ('"229.990"', 229990),
    ],
)
def test_el_precio_siempre_acaba_en_entero(crudo, esperado):
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X","sku":"S",'
        f'"offers":{{"price":{crudo},"priceCurrency":"CLP"}}}}'
        "</script>"
    )
    c = a_captura(html, URL, "paris")
    assert c is not None and c.precio_internet == esperado


def test_agotado_segun_availability():
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X","sku":"S",'
        '"offers":{"price":1000,"availability":"https://schema.org/OutOfStock"}}'
        "</script>"
    )
    c = a_captura(html, URL, "paris")
    assert c is not None and c.disponible is False
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_normalizador.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'nucleo.normalizador'`.

- [ ] **Paso 3: Escribir la implementación mínima**

```python
# src/nucleo/normalizador.py
"""Del HTML de una ficha a una Captura, leyendo el JSON-LD de schema.org.

Es el motor genérico: cualquier tienda que publique un bloque
`<script type="application/ld+json">` con un Product se lee con este código, sin
escribir selectores para cada sitio.
"""

import json
import re

from fuentes.base import Captura

_BLOQUE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def bloques_ld_json(html: str) -> list[dict]:
    """Todos los objetos JSON-LD de la página. Los ilegibles se descartan."""
    objetos: list[dict] = []
    for crudo in _BLOQUE.findall(html):
        try:
            dato = json.loads(crudo.strip())
        except json.JSONDecodeError:
            continue
        for item in dato if isinstance(dato, list) else [dato]:
            if isinstance(item, dict):
                objetos.append(item)
    return objetos


def _a_entero(valor) -> int | None:
    """Pasa el precio a pesos enteros, o None si no hay nada utilizable.

    Las tiendas escriben el precio de todas las formas imaginables: número,
    cadena, con separador de miles. El peso chileno no tiene decimales, así que
    un punto o una coma son separadores de miles salvo que dejen exactamente dos
    cifras detrás, en cuyo caso son decimales y se redondean.
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return int(round(valor))

    texto = str(valor).strip()
    if not texto:
        return None
    if re.fullmatch(r"\d+[.,]\d{2}", texto):       # 229990.00 -> decimales
        return int(round(float(texto.replace(",", "."))))
    solo_digitos = re.sub(r"[^\d]", "", texto)      # 229.990 -> miles
    return int(solo_digitos) if solo_digitos else None


def _tipo_es(objeto: dict, tipo: str) -> bool:
    valor = objeto.get("@type")
    if isinstance(valor, list):
        return tipo in valor
    return valor == tipo


def a_captura(html: str, url: str, tienda: str) -> Captura | None:
    """La Captura de la ficha, o None si la página no da un precio utilizable."""
    for objeto in bloques_ld_json(html):
        if not _tipo_es(objeto, "Product"):
            continue

        ofertas = objeto.get("offers") or {}
        if isinstance(ofertas, list):
            ofertas = ofertas[0] if ofertas else {}

        precio = _a_entero(ofertas.get("price"))
        if precio is None:
            return None

        imagen = objeto.get("image")
        if isinstance(imagen, list):
            imagen = imagen[0] if imagen else None

        disponibilidad = str(ofertas.get("availability") or "")
        # Cuando la tienda no declara stock, se asume disponible: lo contrario
        # silenciaría todas las alertas de las tiendas que no publican el dato.
        disponible = "outofstock" not in disponibilidad.lower().replace("/", "")

        return Captura(
            tienda=tienda,
            sku_externo=str(objeto.get("sku") or "").strip(),
            titulo=str(objeto.get("name") or "").strip(),
            url=url,
            precio_internet=precio,
            precio_normal=_a_entero(objeto.get("listPrice")),
            disponible=disponible,
            imagen_url=imagen if isinstance(imagen, str) else None,
            ean=objeto.get("gtin13") or objeto.get("gtin14") or objeto.get("gtin"),
        )
    return None
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_normalizador.py -v`
Esperado: 10 pasadas (6 casos sueltos + 4 del `parametrize`).

- [ ] **Paso 5: Commit**

```bash
git add src/nucleo/normalizador.py tests/test_normalizador.py tests/fixtures
git commit -m "Núcleo: normalizador genérico de JSON-LD a Captura"
```

---

### Tarea 5: El transporte HTTP, con reintentos y pausas

**Archivos:**
- Crear: `src/fuentes/transporte.py`
- Prueba: `tests/test_transporte.py`

**Interfaces:**
- Consume: `fuentes.base.Transporte`.
- Produce:
  - `fuentes.transporte.TiendaBloqueada(Exception)`
  - `fuentes.transporte.crear_transporte(sesion=None, reintentos=3, pausa=(2.0, 5.0), dormir=time.sleep) -> Transporte`

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_transporte.py
import pytest

from fuentes.transporte import TiendaBloqueada, crear_transporte


class RespuestaFalsa:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class SesionFalsa:
    """Devuelve las respuestas programadas, una por llamada, y apunta las URLs."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return self.respuestas.pop(0)


def test_devuelve_el_cuerpo_cuando_responde_bien():
    sesion = SesionFalsa([RespuestaFalsa(200, "<html>ok</html>")])
    traer = crear_transporte(sesion=sesion, pausa=None, dormir=lambda _: None)
    assert traer("https://www.paris.cl/x.html") == "<html>ok</html>"


def test_reintenta_ante_un_500_y_acaba_bien():
    sesion = SesionFalsa([RespuestaFalsa(500), RespuestaFalsa(200, "ok")])
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=lambda _: None)
    assert traer("https://www.paris.cl/x.html") == "ok"
    assert len(sesion.urls) == 2


def test_agotados_los_reintentos_avisa_de_bloqueo():
    sesion = SesionFalsa([RespuestaFalsa(429)] * 3)
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=lambda _: None)
    with pytest.raises(TiendaBloqueada):
        traer("https://www.paris.cl/x.html")


def test_un_404_no_se_reintenta():
    """Un recurso que no existe no mejora por insistir."""
    sesion = SesionFalsa([RespuestaFalsa(404)])
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=lambda _: None)
    with pytest.raises(TiendaBloqueada):
        traer("https://www.paris.cl/x.html")
    assert len(sesion.urls) == 1


def test_la_espera_crece_entre_intentos():
    esperas = []
    sesion = SesionFalsa(
        [RespuestaFalsa(500), RespuestaFalsa(500), RespuestaFalsa(200, "ok")]
    )
    traer = crear_transporte(sesion=sesion, reintentos=3, pausa=None, dormir=esperas.append)
    traer("https://www.paris.cl/x.html")
    assert len(esperas) == 2
    # Crecimiento estricto: `esperas == sorted(esperas)` también pasaría con una
    # espera constante, y entonces la prueba no mediría lo que dice su nombre.
    assert esperas[1] > esperas[0]
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_transporte.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'fuentes.transporte'`.

- [ ] **Paso 3: Escribir la implementación mínima**

```python
# src/fuentes/transporte.py
"""El transporte HTTP real: una función URL -> texto, con reintentos.

Se aísla aquí para que las fuentes sean probables sin red y para que el ritmo
lento y la cabecera honesta estén en un solo sitio.
"""

import logging
import random
import time

import requests

from fuentes.base import Transporte

registro = logging.getLogger(__name__)

# Identificarse de verdad: ni suplantamos un navegador ni rotamos agentes.
AGENTE = "rastreador-ofertas-personal/0.1 (uso personal, ritmo bajo)"

REINTENTABLES = {429, 500, 502, 503, 504}


class TiendaBloqueada(Exception):
    """La tienda no quiere darnos la página. Se registra y se sigue con otras."""


def crear_transporte(
    sesion=None,
    reintentos: int = 3,
    pausa: tuple[float, float] | None = (2.0, 5.0),
    dormir=time.sleep,
) -> Transporte:
    sesion = sesion if sesion is not None else requests.Session()

    def traer(url: str) -> str:
        if pausa:
            dormir(random.uniform(*pausa))

        for intento in range(1, reintentos + 1):
            respuesta = sesion.get(
                url,
                headers={"User-Agent": AGENTE, "Accept-Language": "es-CL,es;q=0.9"},
                timeout=30,
            )
            if respuesta.status_code == 200:
                return respuesta.text

            if respuesta.status_code not in REINTENTABLES:
                raise TiendaBloqueada(f"{url} respondió {respuesta.status_code}")

            if intento < reintentos:
                espera = 2.0**intento
                registro.warning(
                    "%s respondió %s; reintento %s de %s en %.0f s",
                    url, respuesta.status_code, intento, reintentos, espera,
                )
                dormir(espera)

        raise TiendaBloqueada(f"{url} agotó los {reintentos} intentos")

    return traer
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_transporte.py -v`
Esperado: 5 pasadas.

- [ ] **Paso 5: Commit**

```bash
git add src/fuentes/transporte.py tests/test_transporte.py
git commit -m "Fuentes: transporte HTTP con reintentos, espera creciente y ritmo lento"
```

---

### Tarea 6: La fuente Paris — obtener y buscar

**Archivos:**
- Crear: `src/fuentes/paris.py`
- Crear: `tests/fixtures/paris_busqueda.html`
- Prueba: `tests/test_paris.py`

La *fixture* de búsqueda reproduce la forma de enlace verificada el 2026-10-04 en
`https://www.paris.cl/search?q=notebook`: rutas del tipo `/slug-con-guiones-SKU.html`.

**Interfaces:**
- Consume: `Captura`, `Referencia`, `Transporte`, `a_captura`, `TiendaBloqueada`.
- Produce: `fuentes.paris.Paris(transporte)` con `nombre = "paris"`,
  `obtener(referencias) -> list[Captura]` y `buscar(termino, limite) -> list[Captura]`.

- [ ] **Paso 1: Escribir la fixture y la prueba que falla**

```html
<!-- tests/fixtures/paris_busqueda.html -->
<html><body>
<a href="/apple-macbook-air-chip-m5-16gb-ram-512gb-ssd-13-plata-422566999.html">uno</a>
<a href="/notebook-15-fc0250la-amd-ryzen-5-8gb-ram-512gb-ssd-156-fhd-512134999.html">dos</a>
<a href="/rack-atenas-nogal-851304999.html">tres</a>
<a href="/apple-macbook-air-chip-m5-16gb-ram-512gb-ssd-13-plata-422566999.html">repetido</a>
<a href="/ayuda/">no es ficha</a>
</body></html>
```

```python
# tests/test_paris.py
from pathlib import Path

from fuentes.base import Referencia
from fuentes.paris import Paris
from fuentes.transporte import TiendaBloqueada

FIXTURES = Path(__file__).parent / "fixtures"
FICHA = (FIXTURES / "paris_ficha.html").read_text(encoding="utf-8")
BUSQUEDA = (FIXTURES / "paris_busqueda.html").read_text(encoding="utf-8")
URL_FICHA = "https://www.paris.cl/home-panel-monaco-MK2GCAHDUR.html"

UNO = "https://www.paris.cl/apple-macbook-air-chip-m5-16gb-ram-512gb-ssd-13-plata-422566999.html"
DOS = "https://www.paris.cl/notebook-15-fc0250la-amd-ryzen-5-8gb-ram-512gb-ssd-156-fhd-512134999.html"
TRES = "https://www.paris.cl/rack-atenas-nogal-851304999.html"


def transporte_de(mapa):
    """Transporte falso: devuelve lo que diga el mapa para cada URL."""

    def traer(url):
        if url not in mapa:
            raise TiendaBloqueada(f"sin fixture para {url}")
        return mapa[url]

    return traer


def test_obtener_devuelve_la_captura():
    paris = Paris(transporte_de({URL_FICHA: FICHA}))
    capturas = paris.obtener([Referencia(tienda="paris", url=URL_FICHA)])
    assert len(capturas) == 1
    assert capturas[0].sku_externo == "MK2GCAHDUR"
    assert capturas[0].precio_internet == 229990
    assert capturas[0].tienda == "paris"


def test_una_ficha_bloqueada_no_tumba_las_demas():
    paris = Paris(transporte_de({URL_FICHA: FICHA}))
    capturas = paris.obtener([
        Referencia(tienda="paris", url="https://www.paris.cl/no-existe.html"),
        Referencia(tienda="paris", url=URL_FICHA),
    ])
    assert len(capturas) == 1


def test_buscar_extrae_las_fichas_sin_repetir():
    mapa = {
        "https://www.paris.cl/search?q=notebook": BUSQUEDA,
        UNO: FICHA, DOS: FICHA, TRES: FICHA,
    }
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return mapa[url]

    capturas = Paris(traer).buscar("notebook", limite=10)
    # tres fichas distintas: el enlace repetido y /ayuda/ se descartan
    assert len(capturas) == 3
    assert len(pedidas) == 4  # una búsqueda + tres fichas


def test_buscar_respeta_el_limite():
    mapa = {"https://www.paris.cl/search?q=notebook": BUSQUEDA, UNO: FICHA}
    capturas = Paris(lambda u: mapa[u]).buscar("notebook", limite=1)
    assert len(capturas) == 1


def test_el_termino_se_codifica():
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return "<html></html>"

    Paris(traer).buscar("notebook 16 gb", limite=5)
    assert pedidas[0] == "https://www.paris.cl/search?q=notebook+16+gb"


def test_una_busqueda_bloqueada_devuelve_vacio():
    def traer(url):
        raise TiendaBloqueada("403")

    assert Paris(traer).buscar("notebook", limite=5) == []
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_paris.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'fuentes.paris'`.

- [ ] **Paso 3: Escribir la implementación mínima**

```python
# src/fuentes/paris.py
"""Fuente de paris.cl: se lee raspando el HTML.

La ficha publica un bloque JSON-LD con nombre, SKU y precio, así que el trabajo
real lo hace el normalizador genérico. Aquí solo vive lo propio de Paris: la
forma de su URL de búsqueda y la de sus enlaces a ficha.
"""

import logging
import re
from urllib.parse import urlencode

from fuentes.base import Captura, Referencia, Transporte
from fuentes.transporte import TiendaBloqueada
from nucleo.normalizador import a_captura

registro = logging.getLogger(__name__)

# Las fichas de Paris son rutas del tipo /slug-con-guiones-SKU.html
_ENLACE_FICHA = re.compile(r'href="(/[a-z0-9][a-z0-9\-]{8,90}\.html)"', re.IGNORECASE)


class Paris:
    nombre = "paris"
    BASE = "https://www.paris.cl"

    def __init__(self, transporte: Transporte) -> None:
        self._traer = transporte

    def obtener(self, referencias: list[Referencia]) -> list[Captura]:
        capturas: list[Captura] = []
        for referencia in referencias:
            try:
                html = self._traer(referencia.url)
            except TiendaBloqueada as error:
                registro.warning("paris: no se pudo leer %s (%s)", referencia.url, error)
                continue

            captura = a_captura(html, referencia.url, self.nombre)
            if captura is None:
                registro.warning("paris: sin precio utilizable en %s", referencia.url)
                continue
            capturas.append(captura)
        return capturas

    def buscar(self, termino: str, limite: int) -> list[Captura]:
        url = f"{self.BASE}/search?{urlencode({'q': termino})}"
        try:
            html = self._traer(url)
        except TiendaBloqueada as error:
            registro.warning("paris: búsqueda bloqueada para %r (%s)", termino, error)
            return []

        vistas: list[str] = []
        for ruta in _ENLACE_FICHA.findall(html):
            completa = self.BASE + ruta
            if completa not in vistas:
                vistas.append(completa)

        referencias = [Referencia(tienda=self.nombre, url=u) for u in vistas[:limite]]
        return self.obtener(referencias)
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_paris.py -v`
Esperado: 6 pasadas.

- [ ] **Paso 5: Commit**

```bash
git add src/fuentes/paris.py tests/test_paris.py tests/fixtures/paris_busqueda.html
git commit -m "Fuentes: Paris por raspado, con lista de deseos y búsqueda"
```

---

### Tarea 7: El evaluador de reglas

**Archivos:**
- Crear: `src/nucleo/evaluador.py`
- Prueba: `tests/test_evaluador.py`

**Interfaces:**
- Consume: `fuentes.base.Captura`.
- Produce:
  - `nucleo.evaluador.Reglas` (dataclass congelada: `precio_maximo: int | None = None`,
    `descuento_minimo_pct: float | None = None`, `permitir_precio_tarjeta: bool = False`)
  - `nucleo.evaluador.Veredicto` (dataclass congelada: `regla: str`, `precio: int`, `motivo: str`)
  - `nucleo.evaluador.precio_aplicable(captura, reglas) -> int`
  - `nucleo.evaluador.evaluar(captura, reglas, minimo_historico, dias_historico, dias_minimos) -> Veredicto | None`

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_evaluador.py
from fuentes.base import Captura
from nucleo.evaluador import Reglas, evaluar


def captura(precio=100000, tarjeta=None, disponible=True):
    return Captura(
        tienda="paris",
        sku_externo="S1",
        titulo="Notebook",
        url="https://www.paris.cl/n-S1.html",
        precio_internet=precio,
        precio_tarjeta=tarjeta,
        disponible=disponible,
    )


def test_sin_stock_nunca_avisa():
    assert evaluar(captura(disponible=False), Reglas(precio_maximo=999999), None, 0, 7) is None


def test_precio_maximo_cumplido():
    v = evaluar(captura(precio=89990), Reglas(precio_maximo=90000), None, 0, 7)
    assert v is not None and v.regla == "precio_maximo" and v.precio == 89990


def test_precio_maximo_no_cumplido():
    assert evaluar(captura(precio=95000), Reglas(precio_maximo=90000), None, 0, 7) is None


def test_el_precio_de_tarjeta_se_ignora_por_defecto():
    """Una oferta que solo existe con la tarjeta de la casa no cuenta."""
    reglas = Reglas(precio_maximo=90000, permitir_precio_tarjeta=False)
    assert evaluar(captura(precio=95000, tarjeta=85000), reglas, None, 0, 7) is None


def test_el_precio_de_tarjeta_cuenta_si_se_permite():
    reglas = Reglas(precio_maximo=90000, permitir_precio_tarjeta=True)
    v = evaluar(captura(precio=95000, tarjeta=85000), reglas, None, 0, 7)
    assert v is not None and v.precio == 85000


def test_descuento_por_encima_del_umbral():
    v = evaluar(captura(precio=80000), Reglas(descuento_minimo_pct=15), 100000, 30, 7)
    assert v is not None and v.regla == "descuento_minimo_pct"


def test_descuento_por_debajo_del_umbral():
    assert evaluar(captura(precio=90000), Reglas(descuento_minimo_pct=15), 100000, 30, 7) is None


def test_arranque_en_frio_no_evalua_el_descuento():
    """Con 2 días de histórico, todo precio es su propio mínimo."""
    assert evaluar(captura(precio=80000), Reglas(descuento_minimo_pct=15), 100000, 2, 7) is None


def test_sin_minimo_historico_no_evalua_el_descuento():
    assert evaluar(captura(precio=80000), Reglas(descuento_minimo_pct=15), None, 30, 7) is None


def test_el_precio_maximo_manda_sobre_el_descuento():
    """Si cumple las dos, se informa de la más concreta."""
    reglas = Reglas(precio_maximo=90000, descuento_minimo_pct=15)
    v = evaluar(captura(precio=80000), reglas, 100000, 30, 7)
    assert v is not None and v.regla == "precio_maximo"


def test_sin_reglas_no_avisa():
    assert evaluar(captura(), Reglas(), 100000, 30, 7) is None
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_evaluador.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'nucleo.evaluador'`.

- [ ] **Paso 3: Escribir la implementación mínima**

```python
# src/nucleo/evaluador.py
"""Decide si una captura es una oferta según las reglas del producto."""

from dataclasses import dataclass

from fuentes.base import Captura


@dataclass(frozen=True)
class Reglas:
    precio_maximo: int | None = None
    descuento_minimo_pct: float | None = None
    permitir_precio_tarjeta: bool = False


@dataclass(frozen=True)
class Veredicto:
    regla: str
    precio: int
    motivo: str


def _pesos(cantidad: int) -> str:
    return "$" + f"{cantidad:,}".replace(",", ".")


def precio_aplicable(captura: Captura, reglas: Reglas) -> int:
    """El precio que el usuario considera pagable.

    Por defecto solo cuenta el que paga cualquiera: una oferta que exige la
    tarjeta de la casa no es una oferta si no tienes esa tarjeta.
    """
    if reglas.permitir_precio_tarjeta and captura.precio_tarjeta is not None:
        return min(captura.precio_internet, captura.precio_tarjeta)
    return captura.precio_internet


def evaluar(
    captura: Captura,
    reglas: Reglas,
    minimo_historico: int | None,
    dias_historico: float,
    dias_minimos: int,
) -> Veredicto | None:
    """El veredicto, o None si la captura no es una oferta."""
    if not captura.disponible:
        return None

    precio = precio_aplicable(captura, reglas)

    if reglas.precio_maximo is not None and precio <= reglas.precio_maximo:
        return Veredicto(
            regla="precio_maximo",
            precio=precio,
            motivo=f"{_pesos(precio)}, por debajo de tu tope de {_pesos(reglas.precio_maximo)}",
        )

    # La guarda de arranque en frío: sin histórico suficiente, el mínimo es el
    # propio precio de hoy y el descuento no significa nada.
    if (
        reglas.descuento_minimo_pct is not None
        and minimo_historico
        and dias_historico >= dias_minimos
    ):
        caida = (minimo_historico - precio) / minimo_historico * 100
        if caida >= reglas.descuento_minimo_pct:
            return Veredicto(
                regla="descuento_minimo_pct",
                precio=precio,
                motivo=f"{caida:.0f} % por debajo de su mínimo histórico",
            )

    return None
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_evaluador.py -v`
Esperado: 11 pasadas.

- [ ] **Paso 5: Commit**

```bash
git add src/nucleo/evaluador.py tests/test_evaluador.py
git commit -m "Núcleo: evaluador de reglas con guarda de arranque en frío"
```

---

### Tarea 8: Control de frecuencia

**Archivos:**
- Crear: `src/nucleo/frecuencia.py`
- Modificar: `src/almacen/operaciones.py` (añadir las dos funciones de alertas)
- Prueba: `tests/test_frecuencia.py`

**Interfaces:**
- Consume: `abrir`, `alta_o_actualiza_producto`.
- Produce:
  - `almacen.operaciones.ultima_alerta(con, producto_id, regla) -> sqlite3.Row | None`
    (columnas `precio_notificado` y `dias_desde`)
  - `almacen.operaciones.registrar_alerta(con, producto_id, regla, precio) -> None`
  - `nucleo.frecuencia.debe_notificar(con, producto_id, regla, precio, cooldown_dias) -> bool`

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_frecuencia.py
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
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_frecuencia.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'nucleo.frecuencia'`.

- [ ] **Paso 3: Escribir la implementación mínima**

```python
# añadir al final de src/almacen/operaciones.py


def ultima_alerta(con: sqlite3.Connection, producto_id: int, regla: str):
    """La última alerta enviada para ese producto y esa regla, si la hubo."""
    return con.execute(
        """
        SELECT precio_notificado,
               (julianday('now') - julianday(enviado_el)) AS dias_desde
          FROM registro_alertas
         WHERE producto_id = ? AND regla = ?
         ORDER BY enviado_el DESC, id DESC
         LIMIT 1
        """,
        (producto_id, regla),
    ).fetchone()


def registrar_alerta(
    con: sqlite3.Connection, producto_id: int, regla: str, precio: int
) -> None:
    con.execute(
        """
        INSERT INTO registro_alertas (producto_id, regla, precio_notificado)
             VALUES (?, ?, ?)
        """,
        (producto_id, regla, precio),
    )
```

```python
# src/nucleo/frecuencia.py
"""Evita repetir la misma alerta hasta cansar al usuario.

Un rastreador que avisa de la misma oferta seis veces al día acaba silenciado,
y entonces no sirve para nada. Esta es la pieza que lo impide.
"""

import sqlite3

from almacen.operaciones import ultima_alerta


def debe_notificar(
    con: sqlite3.Connection,
    producto_id: int,
    regla: str,
    precio: int,
    cooldown_dias: int,
) -> bool:
    """Se avisa si es la primera vez, si bajó más, o si pasó el descanso."""
    anterior = ultima_alerta(con, producto_id, regla)
    if anterior is None:
        return True
    if precio < anterior["precio_notificado"]:
        return True
    return anterior["dias_desde"] > cooldown_dias
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_frecuencia.py -v`
Esperado: 6 pasadas.

- [ ] **Paso 5: Commit**

```bash
git add src/nucleo/frecuencia.py src/almacen/operaciones.py tests/test_frecuencia.py
git commit -m "Núcleo: control de frecuencia para no repetir la misma alerta"
```

---

### Tarea 9: Los avisos — archivo y Telegram

**Archivos:**
- Crear: `src/avisos/base.py`, `src/avisos/archivo.py`, `src/avisos/telegram.py`
- Prueba: `tests/test_avisos.py`

**Interfaces:**
- Consume: `nucleo.evaluador.Veredicto`, `fuentes.base.Captura`.
- Produce:
  - `avisos.base.pesos(cantidad: int) -> str`
  - `avisos.base.redactar(captura, veredicto) -> str`
  - `avisos.base.Notificador` (protocolo con `enviar(captura, veredicto) -> None`)
  - `avisos.archivo.NotificadorArchivo(ruta)`
  - `avisos.telegram.NotificadorTelegram(token, chat_id, sesion=None)`
  - `avisos.telegram.TelegramMalConfigurado(Exception)`, `avisos.telegram.EnvioFallido(Exception)`

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_avisos.py
import json

import pytest

from avisos.archivo import NotificadorArchivo
from avisos.base import redactar
from avisos.telegram import EnvioFallido, NotificadorTelegram, TelegramMalConfigurado
from fuentes.base import Captura
from nucleo.evaluador import Veredicto

CAPTURA = Captura(
    tienda="paris", sku_externo="S1", titulo="Notebook Lenovo",
    url="https://www.paris.cl/n-S1.html", precio_internet=89990, precio_normal=129990,
)
VEREDICTO = Veredicto(regla="precio_maximo", precio=89990, motivo="por debajo de tu tope")


def test_el_mensaje_lleva_lo_imprescindible():
    texto = redactar(CAPTURA, VEREDICTO)
    assert "Notebook Lenovo" in texto
    assert "89.990" in texto          # formato chileno, con punto de miles
    assert "paris" in texto.lower()
    assert CAPTURA.url in texto


def test_el_notificador_de_archivo_escribe_una_linea_json(tmp_path):
    ruta = tmp_path / "alertas.jsonl"
    NotificadorArchivo(ruta).enviar(CAPTURA, VEREDICTO)
    NotificadorArchivo(ruta).enviar(CAPTURA, VEREDICTO)

    lineas = ruta.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 2
    registro = json.loads(lineas[0])
    assert registro["precio"] == 89990
    assert registro["url"] == CAPTURA.url


def test_telegram_sin_token_falla_al_construirse():
    """Mejor estallar al arrancar que a mitad del ciclo."""
    with pytest.raises(TelegramMalConfigurado):
        NotificadorTelegram(token="", chat_id="123")


def test_telegram_envia_el_mensaje():
    enviados = []

    class SesionFalsa:
        def post(self, url, json=None, timeout=None):
            enviados.append((url, json))

            class R:
                status_code = 200

            return R()

    NotificadorTelegram("secreto", "123", sesion=SesionFalsa()).enviar(CAPTURA, VEREDICTO)
    url, cuerpo = enviados[0]
    assert url.endswith("/sendMessage")
    assert cuerpo["chat_id"] == "123"
    assert "Notebook Lenovo" in cuerpo["text"]


def test_telegram_no_filtra_el_token_en_el_error():
    class SesionFalsa:
        def post(self, url, json=None, timeout=None):
            class R:
                status_code = 401

            return R()

    notificador = NotificadorTelegram("SECRETO-QUE-NO-DEBE-SALIR", "123", sesion=SesionFalsa())
    with pytest.raises(EnvioFallido) as error:
        notificador.enviar(CAPTURA, VEREDICTO)
    assert "SECRETO-QUE-NO-DEBE-SALIR" not in str(error.value)
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_avisos.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'avisos.archivo'`.

- [ ] **Paso 3: Escribir la implementación mínima**

```python
# src/avisos/base.py
"""Qué se le dice al usuario y por dónde."""

from typing import Protocol

from fuentes.base import Captura
from nucleo.evaluador import Veredicto


def pesos(cantidad: int) -> str:
    """89990 -> '$89.990', como se escribe en Chile."""
    return "$" + f"{cantidad:,}".replace(",", ".")


def redactar(captura: Captura, veredicto: Veredicto) -> str:
    lineas = [
        "🔥 Oferta detectada",
        "",
        captura.titulo,
        f"Tienda: {captura.tienda}",
        f"Precio: {pesos(veredicto.precio)}",
    ]
    if captura.precio_normal and captura.precio_normal > veredicto.precio:
        lineas.append(f"Antes: {pesos(captura.precio_normal)}")
    lineas += [f"Motivo: {veredicto.motivo}", "", captura.url]
    return "\n".join(lineas)


class Notificador(Protocol):
    def enviar(self, captura: Captura, veredicto: Veredicto) -> None: ...
```

```python
# src/avisos/archivo.py
"""Notificador de respaldo: deja las alertas en un .jsonl legible."""

import json
from datetime import datetime, timezone
from pathlib import Path

from avisos.base import redactar
from fuentes.base import Captura
from nucleo.evaluador import Veredicto


class NotificadorArchivo:
    def __init__(self, ruta: Path | str) -> None:
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)

    def enviar(self, captura: Captura, veredicto: Veredicto) -> None:
        registro = {
            "momento": datetime.now(timezone.utc).isoformat(),
            "tienda": captura.tienda,
            "titulo": captura.titulo,
            "url": captura.url,
            "regla": veredicto.regla,
            "precio": veredicto.precio,
            "mensaje": redactar(captura, veredicto),
        }
        with self.ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
```

```python
# src/avisos/telegram.py
"""Notificador por Telegram. El token nunca aparece en logs ni en errores."""

import requests

from avisos.base import redactar
from fuentes.base import Captura
from nucleo.evaluador import Veredicto


class TelegramMalConfigurado(Exception):
    """Falta el token o el chat. Se detecta al arrancar, no a mitad del ciclo."""


class EnvioFallido(Exception):
    """Telegram rechazó el mensaje. El texto del error no lleva el token."""


class NotificadorTelegram:
    def __init__(self, token: str, chat_id: str, sesion=None) -> None:
        if not token or not chat_id:
            raise TelegramMalConfigurado(
                "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el .env"
            )
        self._token = token
        self._chat_id = chat_id
        self._sesion = sesion if sesion is not None else requests.Session()

    def enviar(self, captura: Captura, veredicto: Veredicto) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        cuerpo = {
            "chat_id": self._chat_id,
            "text": redactar(captura, veredicto),
            "disable_web_page_preview": False,
        }

        # El `try` contiene exactamente una sentencia: la llamada de red. Si
        # abarcara también la construcción del cuerpo, un fallo al redactar se
        # relanzaría disfrazado de problema de conexión.
        tipo_de_fallo = None
        try:
            respuesta = self._sesion.post(url, json=cuerpo, timeout=30)
        except Exception as error:
            tipo_de_fallo = type(error).__name__
        if tipo_de_fallo is not None:
            # El texto de las excepciones de requests incluye la URL, y la URL
            # lleva el token incrustado. Se relanza ya FUERA del bloque except,
            # cuando Python no tiene ninguna excepción en curso que encadenar:
            # así el error nuevo no lleva ni __cause__ ni __context__.
            # `raise ... from None` no bastaría: limpia __cause__ pero deja
            # __context__ apuntando a la excepción original, token incluido.
            raise EnvioFallido(f"No se pudo contactar con Telegram ({tipo_de_fallo})")
        if respuesta.status_code != 200:
            # Sin la URL en el mensaje: lleva el token incrustado.
            raise EnvioFallido(f"Telegram respondió {respuesta.status_code}")
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_avisos.py -v`
Esperado: 5 pasadas.

- [ ] **Paso 5: Commit**

```bash
git add src/avisos tests/test_avisos.py
git commit -m "Avisos: redacción del mensaje, notificador a archivo y a Telegram"
```

---

### Tarea 10: El orquestador

**Archivos:**
- Crear: `runner.py`, `config/config.yaml`, `config/lista_deseos.yaml`
- Prueba: `tests/test_runner.py`

**Interfaces:**
- Consume: todo lo anterior.
- Produce:
  - `runner.cargar_config(ruta) -> dict`
  - `runner.cargar_lista_deseos(ruta) -> tuple[list[dict], list[dict]]`
  - `runner.ejecutar_ciclo(con, fuentes, vigilados, busquedas, notificador, config) -> int`
  - `runner.construir_notificador(config)`
  - `runner.main() -> int`

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_runner.py
from almacen.conexion import abrir
from fuentes.base import Captura
from nucleo.evaluador import Reglas
from runner import ejecutar_ciclo

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
```

- [ ] **Paso 2: Ejecutar la prueba y comprobar que falla**

Ejecuta: `python -m pytest tests/test_runner.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'runner'`.

(`runner.py` vive en la raíz, que está en `pythonpath` por el `pyproject.toml` de la Tarea 1.)

- [ ] **Paso 3: Escribir la implementación mínima**

```yaml
# config/config.yaml
ejecucion:
  espera_entre_peticiones_seg: [2, 5]
  reintentos: 3
  limite_por_busqueda: 15
historico:
  ventana_minimo_dias: 90
  dias_minimos_para_descuento: 7
alertas:
  canal: archivo          # archivo | telegram
  cooldown_dias: 5
  ruta_archivo: logs/alertas.jsonl
```

```yaml
# config/lista_deseos.yaml
vigilados:
  - nombre: Home Panel Mónaco TV 55
    tienda: paris
    url: https://www.paris.cl/home-panel-monaco-tv-55-1-6-castano-off-white-MK2GCAHDUR.html
    reglas:
      precio_maximo: 200000
      descuento_minimo_pct: 15
      permitir_precio_tarjeta: false

busquedas:
  - termino: notebook 16gb
    tienda: paris
    reglas:
      precio_maximo: 400000
```

```python
# runner.py
"""Orquesta un ciclo completo: capturar, guardar, evaluar, avisar."""

import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Bajo pytest, `src` entra por el pythonpath del pyproject.toml. Al ejecutar
# `python runner.py` a secas no hay tal cosa, así que se añade aquí.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from almacen.conexion import abrir                 # noqa: E402
from almacen.operaciones import (                  # noqa: E402
    alta_o_actualiza_producto,
    dias_de_historico,
    minimo_historico,
    registrar_alerta,
    registrar_si_cambio,
)
from avisos.archivo import NotificadorArchivo      # noqa: E402
from avisos.telegram import NotificadorTelegram    # noqa: E402
from fuentes.base import Referencia                # noqa: E402
from fuentes.paris import Paris                    # noqa: E402
from fuentes.transporte import crear_transporte    # noqa: E402
from nucleo.evaluador import Reglas, evaluar       # noqa: E402
from nucleo.frecuencia import debe_notificar       # noqa: E402

registro = logging.getLogger("rastreador")

RAIZ = Path(__file__).parent


def cargar_config(ruta: Path | str) -> dict:
    return yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))


def cargar_lista_deseos(ruta: Path | str) -> tuple[list[dict], list[dict]]:
    """Devuelve (vigilados, busquedas) con las reglas ya convertidas."""
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}

    vigilados = [
        {
            "tienda": entrada["tienda"],
            "url": entrada["url"],
            "reglas": Reglas(**(entrada.get("reglas") or {})),
        }
        for entrada in datos.get("vigilados") or []
    ]
    busquedas = [
        {
            "tienda": entrada["tienda"],
            "termino": entrada["termino"],
            "reglas": Reglas(**(entrada.get("reglas") or {})),
        }
        for entrada in datos.get("busquedas") or []
    ]
    return vigilados, busquedas


def _procesar(con, capturas, reglas, notificador, config) -> int:
    """Guarda las capturas, evalúa y avisa. Devuelve cuántas alertas mandó."""
    ventana = config["historico"]["ventana_minimo_dias"]
    dias_minimos = config["historico"]["dias_minimos_para_descuento"]
    cooldown = config["alertas"]["cooldown_dias"]

    enviadas = 0
    for captura in capturas:
        producto_id = alta_o_actualiza_producto(con, captura)

        # El mínimo se consulta ANTES de insertar la captura de hoy: si no, el
        # precio actual sería su propio mínimo y el descuento siempre cero.
        minimo = minimo_historico(con, producto_id, ventana)
        dias = dias_de_historico(con, producto_id)

        registrar_si_cambio(con, producto_id, captura)

        veredicto = evaluar(captura, reglas, minimo, dias, dias_minimos)
        if veredicto is None:
            continue
        if not debe_notificar(con, producto_id, veredicto.regla, veredicto.precio, cooldown):
            continue

        notificador.enviar(captura, veredicto)
        registrar_alerta(con, producto_id, veredicto.regla, veredicto.precio)
        enviadas += 1

    return enviadas


def ejecutar_ciclo(con, fuentes, vigilados, busquedas, notificador, config) -> int:
    """Un ciclo completo. Un fallo de una tienda nunca detiene a las demás."""
    enviadas = 0

    for vigilado in vigilados:
        fuente = fuentes.get(vigilado["tienda"])
        if fuente is None:
            registro.warning("sin fuente para la tienda %r", vigilado["tienda"])
            continue
        try:
            capturas = fuente.obtener(
                [Referencia(tienda=vigilado["tienda"], url=vigilado["url"])]
            )
        except Exception as error:  # noqa: BLE001
            registro.warning("fuente %s falló: %s", fuente.nombre, error)
            continue
        enviadas += _procesar(con, capturas, vigilado["reglas"], notificador, config)

    limite = config.get("ejecucion", {}).get("limite_por_busqueda", 15)
    for busqueda in busquedas:
        fuente = fuentes.get(busqueda["tienda"])
        if fuente is None:
            registro.warning("sin fuente para la tienda %r", busqueda["tienda"])
            continue
        try:
            capturas = fuente.buscar(busqueda["termino"], busqueda.get("limite", limite))
        except Exception as error:  # noqa: BLE001
            registro.warning("búsqueda en %s falló: %s", fuente.nombre, error)
            continue
        enviadas += _procesar(con, capturas, busqueda["reglas"], notificador, config)

    return enviadas


def construir_notificador(config):
    if config["alertas"].get("canal", "archivo") == "telegram":
        return NotificadorTelegram(
            token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        )
    return NotificadorArchivo(RAIZ / config["alertas"]["ruta_archivo"])


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv(RAIZ / ".env")

    config = cargar_config(RAIZ / "config" / "config.yaml")
    vigilados, busquedas = cargar_lista_deseos(RAIZ / "config" / "lista_deseos.yaml")

    transporte = crear_transporte(
        reintentos=config["ejecucion"]["reintentos"],
        pausa=tuple(config["ejecucion"]["espera_entre_peticiones_seg"]),
    )
    fuentes = {"paris": Paris(transporte)}

    con = abrir(RAIZ / "data" / "tracker.db")
    enviadas = ejecutar_ciclo(
        con, fuentes, vigilados, busquedas, construir_notificador(config), config
    )
    registro.info("ciclo terminado: %s alertas enviadas", enviadas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Paso 4: Ejecutar la prueba y comprobar que pasa**

Ejecuta: `python -m pytest tests/test_runner.py -v`
Esperado: 6 pasadas.

- [ ] **Paso 5: Ejecutar la suite entera**

Ejecuta: `python -m pytest -v`
Esperado: **62 pasadas**, sin red (2 + 5 + 6 + 10 + 5 + 6 + 11 + 6 + 5 + 6).

- [ ] **Paso 6: Commit**

```bash
git add runner.py config tests/test_runner.py
git commit -m "Orquestador: ciclo completo con aislamiento de fallos por tienda"
```

---

### Tarea 11: Prueba de humo contra Paris de verdad

Las diez tareas anteriores no han tocado la red ni una vez. Esta es la única que sí, y es
manual: comprueba que las *fixtures* siguen pareciéndose a la realidad.

**Archivos:**
- Crear: `herramientas/sonda_paris.py`, `README.md`

- [ ] **Paso 1: Escribir la sonda**

```python
# herramientas/sonda_paris.py
"""Comprueba contra paris.cl que el raspado sigue funcionando.

No es una prueba automática: toca la red y depende de que un producto exista.
Se ejecuta a mano cuando algo huele mal o antes de dar por buena una entrega.

    python herramientas/sonda_paris.py "notebook"
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.paris import Paris                   # noqa: E402
from fuentes.transporte import crear_transporte   # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    termino = sys.argv[1] if len(sys.argv) > 1 else "notebook"

    capturas = Paris(crear_transporte()).buscar(termino, limite=3)

    if not capturas:
        print(f"FALLA: la búsqueda de {termino!r} no devolvió nada.")
        print("Puede que Paris haya cambiado la forma de sus enlaces o su JSON-LD.")
        return 1

    print(f"OK: {len(capturas)} capturas para {termino!r}\n")
    for c in capturas:
        print(f"  {c.titulo[:60]}")
        print(f"    sku={c.sku_externo}  precio={c.precio_internet}  stock={c.disponible}")
        print(f"    {c.url}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Paso 2: Ejecutarla contra la red**

Ejecuta: `python herramientas/sonda_paris.py notebook`
Esperado: `OK: 3 capturas` con títulos, SKU y precios enteros plausibles (seis cifras).

Si falla, **no toques las pruebas**: el fallo está en que Paris ha cambiado. Vuelve a mirar
la ficha a mano, ajusta `_ENLACE_FICHA` o el normalizador, y actualiza la *fixture*.

- [ ] **Paso 3: Ejecutar el ciclo de verdad, dos veces**

```bash
python runner.py
python runner.py
```

Esperado, según los criterios de éxito de la spec: la primera pasada da de alta los
productos y escribe en `logs/alertas.jsonl` las que cumplan; la **segunda no añade filas al
histórico ni manda alertas**. Compruébalo:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/tracker.db'); print('productos:', c.execute('SELECT COUNT(*) FROM productos').fetchone()[0]); print('historico:', c.execute('SELECT COUNT(*) FROM historico_precios').fetchone()[0])"
```

- [ ] **Paso 4: Escribir el README**

````markdown
# Rastreador de ofertas — retail chileno

Vigila precios de tiendas chilenas, guarda el histórico de variaciones y avisa
cuando algo baja de verdad.

## Puesta en marcha

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edita `config/lista_deseos.yaml` con lo que quieras vigilar y ejecuta:

```
python runner.py
```

## Pruebas

```
python -m pytest
```

No tocan la red. Para comprobar contra Paris de verdad:

```
python herramientas/sonda_paris.py notebook
```

## Cómo está hecho

Cada tienda es una `Fuente` que devuelve `Captura`. El núcleo no sabe de HTTP ni
de qué tienda viene el dato, así que añadir una tienda nueva no toca el núcleo.

El histórico guarda **variaciones**, no pasadas: una fila solo cuando el precio o
el stock cambian.

No se evade la detección de robots. Si una tienda bloquea, queda registrada y el
ciclo sigue con las demás.

El diseño está en `docs/specs/` y el plan en `docs/plans/`.
````

- [ ] **Paso 5: Commit**

```bash
git add herramientas README.md
git commit -m "Sonda manual contra Paris y documentación de puesta en marcha"
```

---

## Qué queda fuera, y dónde seguir

Al terminar la Tarea 11 hay un rastreador que funciona. Lo que la spec deja para después:

- **Etapa 2 (anchura):** Falabella y abc.cl con el mismo normalizador —verificado el
  2026-10-04 que ambas sirven JSON-LD—, y la matriz de tres precios, que **no está en el
  JSON-LD** y exige leer los datos que Next.js incrusta en la página.
- **Etapa 3 (emparejado):** reconocer el mismo producto en dos tiendas. Verificado que
  Paris no publica `gtin`, así que habrá que apoyarse en el parecido entre títulos, con lo
  incierto que eso es.
- **Etapa 4 (operación):** reporte Excel, rotación de logs y Programador de tareas.
