# Etapa 2b — SoloTodo: plan de implementación

> **Para agentes ejecutores:** SUB-SKILL OBLIGATORIA: usa
> `superpowers:subagent-driven-development` (recomendada) o
> `superpowers:executing-plans` para ejecutar este plan tarea a tarea. Los pasos
> usan casillas (`- [ ]`) para el seguimiento.

**Objetivo:** añadir SoloTodo como fuente —una API REST que cubre 368 tiendas que no tenemos en
directo— y guardar su identificador de producto, que es lo que hará posible el emparejado entre
tiendas más adelante.

**Arquitectura:** `SoloTodo` implementa el protocolo `Fuente` **sin heredar de `FuenteJsonLd`**:
consume JSON de una API, no HTML. El `tienda` de cada captura es la tienda real (`abcdin`), no
`solotodo`, porque el producto está allí. Las tiendas que ya cubrimos en directo se excluyen.

**Tecnologías:** Python 3.12, SQLite, `requests`, `PyYAML`, `python-dotenv`, `pytest`.

**Spec:** `docs/specs/2026-10-05-etapa-2b-solotodo-design.md`

**Punto de partida:** rama `etapa-2b-solotodo` desde `main` @ `b826415`. **111 pruebas en verde.**

## Restricciones globales

- Python 3.12. Dependencias permitidas: `requests`, `PyYAML`, `python-dotenv`, `pytest`. Nada más.
- **Todo en español**: identificadores, docstrings, comentarios y mensajes de commit.
- **El dinero es `int` de pesos chilenos.** Ningún `float` toca un precio.
- **Ninguna prueba accede a la red.** Las fuentes reciben su transporte por inyección.
- **Ningún secreto en logs ni mensajes de error.**
- **Las capas no se cruzan**: `nucleo` no importa `sqlite3`, `requests` ni `almacen`; `fuentes` no
  importa `sqlite3`. Lo vigila `tests/test_capas.py`, que debe seguir en verde.
- **Las pruebas existentes no se tocan.** Si una se pone roja, lo que hay que arreglar es el código.
- Cada prueba nueva se valida rompiendo a propósito lo que dice medir, y comprobando que se pone
  roja **por el motivo correcto**.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/almacen/esquema.sql` | + `productos.producto_solotodo` |
| `src/almacen/conexion.py` | + la migración por columnas faltantes |
| `src/almacen/operaciones.py` | `alta_o_actualiza_producto` guarda el identificador |
| `src/fuentes/base.py` | + `Captura.producto_solotodo` |
| `src/fuentes/solotodo.py` | **nuevo** — conversión, búsqueda y obtención |
| `runner.py` | resuelve `fuente:`, registra SoloTodo |
| `config/config.yaml` | + `solotodo.tiendas_excluidas` |
| `herramientas/sonda_solotodo.py` | **nuevo** — sonda manual contra la API real |

---

### Tarea 1: La migración, y la columna que la obliga

Es la tarea con más riesgo real del plan, y el riesgo no está en el código sino en lo que no se ve:
**ninguna prueba del proyecto habría detectado nunca que `abrir()` no migra**, porque todas crean
su base desde cero con `tmp_path`. El único afectado sería el usuario, con meses de histórico
dentro.

**Archivos:**
- Modificar: `src/almacen/esquema.sql`, `src/almacen/conexion.py`, `src/almacen/operaciones.py`,
  `src/fuentes/base.py`
- Prueba: `tests/test_conexion.py`, `tests/test_operaciones.py`

**Interfaces:**
- Produce:
  - `fuentes.base.Captura.producto_solotodo: int | None = None`
  - `productos.producto_solotodo INTEGER` en el esquema
  - `almacen.conexion.COLUMNAS_NUEVAS: list[tuple[str, str, str]]`
  - `alta_o_actualiza_producto` escribe y preserva ese identificador

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_conexion.py
import sqlite3

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

```

```python
# añadir a tests/test_operaciones.py


def test_el_alta_guarda_el_identificador_de_solotodo(tmp_path):
    con = abrir(tmp_path / "p.db")
    c = replace(captura(), producto_solotodo=43835)
    pid = alta_o_actualiza_producto(con, c)

    fila = con.execute(
        "SELECT producto_solotodo FROM productos WHERE id = ?", (pid,)
    ).fetchone()
    assert fila["producto_solotodo"] == 43835


def test_una_captura_sin_identificador_no_borra_el_que_ya_habia(tmp_path):
    """Paris y Falabella no lo traen; no pueden pisar lo que SoloTodo guardó."""
    con = abrir(tmp_path / "p.db")
    pid = alta_o_actualiza_producto(con, replace(captura(), producto_solotodo=43835))
    alta_o_actualiza_producto(con, captura())   # sin identificador

    fila = con.execute(
        "SELECT producto_solotodo FROM productos WHERE id = ?", (pid,)
    ).fetchone()
    assert fila["producto_solotodo"] == 43835
```

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_conexion.py tests/test_operaciones.py -v`
Esperado: la prueba de migración falla porque `producto_solotodo` no está entre las columnas, y las
dos de `operaciones` fallan con `TypeError` al construir la `Captura`.

> [!note] Por qué no hay una prueba de «abrir dos veces»
> `ALTER TABLE` sobre una columna existente es un error, no una operación vacía — pero
> `test_abrir_es_idempotente`, que ya existe, abre la misma base dos veces y lo cubriría. Una
> prueba nueva para eso sería un duplicado.

- [ ] **Paso 3: Implementar**

En `src/almacen/esquema.sql`, dentro de `productos`, tras `ean`:

```sql
    producto_solotodo INTEGER,
```

En `src/fuentes/base.py`, **al final** de `Captura` (igual que `precios_etiquetados`, para no
romper ninguna construcción posicional):

```python
    precios_etiquetados: bool = True
    # El identificador que SoloTodo da al mismo artículo en todas las tiendas.
    # Solo lo trae esa fuente. Se guarda desde ya aunque nada lo use todavía:
    # es el dato que hará posible el emparejado, y no se puede recuperar hacia
    # atrás sobre un histórico que ya creció sin él.
    producto_solotodo: int | None = None
```

En `src/almacen/conexion.py`:

```python
# Columnas añadidas después de la primera versión del esquema. `CREATE TABLE IF
# NOT EXISTS` no las lleva a una base que ya existe, así que hay que añadirlas a
# mano. Formato: (tabla, columna, declaración).
COLUMNAS_NUEVAS = [
    ("productos", "producto_solotodo", "INTEGER"),
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
```

y en `abrir`, justo después del `executescript`:

```python
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    _migrar(con)
    return con
```

En `src/almacen/operaciones.py`, dentro de `alta_o_actualiza_producto`: añade la columna al INSERT,
el parámetro al diccionario, y la preservación al UPDATE.

```sql
        INSERT INTO productos (tienda, sku_externo, titulo, url, imagen_url, ean,
                               producto_solotodo, ultima_revision)
             VALUES (:tienda, :sku, :titulo, :url, :imagen, :ean,
                     :producto_solotodo, datetime('now'))
        ON CONFLICT (tienda, sku_externo) DO UPDATE SET
                titulo            = excluded.titulo,
                imagen_url        = COALESCE(excluded.imagen_url, productos.imagen_url),
                ean               = COALESCE(excluded.ean, productos.ean),
                producto_solotodo = COALESCE(excluded.producto_solotodo,
                                             productos.producto_solotodo),
                ultima_revision   = datetime('now')
```

```python
            "ean": captura.ean,
            "producto_solotodo": captura.producto_solotodo,
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **114 pasadas** (111 + 3).

- [ ] **Paso 5: Demostrar que la prueba de migración es real**

Quita la llamada a `_migrar(con)` de `abrir` y ejecuta
`python -m pytest tests/test_conexion.py::test_una_base_anterior_gana_la_columna_sin_perder_sus_datos -v`.
**Debe FALLAR** porque la columna no aparece. Restaura y comprueba que vuelve a pasar. Las dos
salidas van al informe: es la única prueba del proyecto que vigila algo que ninguna otra puede ver.

- [ ] **Paso 6: Commit**

```bash
git add src/almacen src/fuentes/base.py tests/test_conexion.py tests/test_operaciones.py
git commit -m "Almacén: el identificador de producto de SoloTodo, y la primera migración"
```

---

### Tarea 2: De una entidad de SoloTodo a una Captura

Pura conversión: sin HTTP, sin estado. Todo lo que decide qué se guarda y qué se descarta vive
aquí y se prueba sin red.

**Archivos:**
- Crear: `src/fuentes/solotodo.py`, `tests/fixtures/solotodo_entidades.json`
- Prueba: `tests/test_solotodo.py` (nuevo)

La *fixture* reproduce lo verificado contra `api.solotodo.com` el 2026-10-05: cuatro entidades, una
de ellas sin `active_registry`, otra de una tienda que excluimos, otra de una tienda desconocida.

**Interfaces:**
- Consume: `fuentes.base.Captura`, `nucleo.normalizador.a_entero`.
- Produce:
  - `fuentes.solotodo.identificador_de_tienda(nombre: str) -> str`
  - `fuentes.solotodo.captura_de_entidad(entidad: dict, tiendas: dict[int, str], excluidas: set[str]) -> Captura | None`

- [ ] **Paso 1: Escribir la fixture y la prueba que falla**

```json
[
  {
    "id": 1379496,
    "name": "Notebook AbcDin de prueba",
    "sku": "AD-100",
    "external_url": "https://www.abc.cl/notebook-AD-100",
    "ean": "7801234567890",
    "store": 30,
    "product": {"id": 43835, "name": "Notebook normalizado"},
    "active_registry": {
      "is_available": true,
      "normal_price": "587990.00",
      "offer_price": "573990.00"
    }
  },
  {
    "id": 1379497,
    "name": "Entidad sin precio activo",
    "sku": "AD-101",
    "external_url": "https://www.abc.cl/notebook-AD-101",
    "ean": null,
    "store": 30,
    "product": {"id": 43836, "name": "Otro"},
    "active_registry": null
  },
  {
    "id": 1379498,
    "name": "Cartucho visto en Falabella",
    "sku": "4839263",
    "external_url": "https://www.falabella.com/falabella-cl/product/4839263/x/4839263",
    "ean": null,
    "store": 9,
    "product": {"id": 51001, "name": "Cartucho"},
    "active_registry": {
      "is_available": true,
      "normal_price": "13990.00",
      "offer_price": "13990.00"
    }
  },
  {
    "id": 1379499,
    "name": "Entidad de una tienda desconocida",
    "sku": "XX-1",
    "external_url": "https://tienda-rara.cl/xx-1",
    "ean": null,
    "store": 999999,
    "product": null,
    "active_registry": {
      "is_available": false,
      "normal_price": "1000.00",
      "offer_price": "900.00"
    }
  }
]
```

```python
# tests/test_solotodo.py
import json
from pathlib import Path

import pytest

from fuentes.solotodo import captura_de_entidad, identificador_de_tienda

FIXTURES = Path(__file__).parent / "fixtures"
ENTIDADES = json.loads((FIXTURES / "solotodo_entidades.json").read_text(encoding="utf-8"))

TIENDAS = {30: "AbcDin", 9: "Falabella", 77: "PC Factory"}
EXCLUIDAS = {"paris", "falabella"}


@pytest.mark.parametrize(
    "nombre, esperado",
    [("AbcDin", "abcdin"), ("PC Factory", "pc-factory"), ("Tecno Saga", "tecno-saga")],
)
def test_el_identificador_de_tienda_se_normaliza(nombre, esperado):
    assert identificador_de_tienda(nombre) == esperado


def test_una_entidad_activa_da_su_captura():
    c = captura_de_entidad(ENTIDADES[0], TIENDAS, EXCLUIDAS)
    assert c is not None
    assert c.tienda == "abcdin"          # la tienda real, no «solotodo»
    assert c.sku_externo == "AD-100"
    assert c.url == "https://www.abc.cl/notebook-AD-100"
    assert c.precio_internet == 573990   # offer_price
    assert c.precio_normal == 587990     # normal_price
    assert c.precio_tarjeta is None      # SoloTodo no lo publica
    assert c.tarjeta is None
    assert c.disponible is True
    assert c.ean == "7801234567890"
    assert c.producto_solotodo == 43835
    assert c.precios_etiquetados is True


def test_los_precios_con_decimales_llegan_enteros():
    c = captura_de_entidad(ENTIDADES[0], TIENDAS, EXCLUIDAS)
    assert isinstance(c.precio_internet, int)
    assert isinstance(c.precio_normal, int)


def test_una_entidad_sin_precio_activo_se_descarta():
    assert captura_de_entidad(ENTIDADES[1], TIENDAS, EXCLUIDAS) is None


def test_una_tienda_que_cubrimos_en_directo_se_descarta():
    """Si no, el mismo producto recibiría filas alternas de dos fuentes que
    discrepan en la tarjeta, y el histórico crecería una fila por ciclo."""
    assert captura_de_entidad(ENTIDADES[2], TIENDAS, EXCLUIDAS) is None


def test_una_tienda_desconocida_se_descarta():
    """Sin nombre de tienda no hay identidad, y una inventada mezcla productos."""
    assert captura_de_entidad(ENTIDADES[3], TIENDAS, EXCLUIDAS) is None


def test_un_ean_ausente_llega_como_none_y_no_como_texto():
    entidad = dict(ENTIDADES[0], ean=None)
    c = captura_de_entidad(entidad, TIENDAS, EXCLUIDAS)
    assert c.ean is None


def test_una_entidad_sin_producto_normalizado_no_estalla():
    entidad = dict(ENTIDADES[0], product=None)
    c = captura_de_entidad(entidad, TIENDAS, EXCLUIDAS)
    assert c is not None and c.producto_solotodo is None
```

- [ ] **Paso 2: Ejecutar y comprobar que falla**

Ejecuta: `python -m pytest tests/test_solotodo.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'fuentes.solotodo'`.

- [ ] **Paso 3: Implementar**

```python
# src/fuentes/solotodo.py
"""Fuente de api.solotodo.com.

SoloTodo no es una tienda sino un agregador con API REST pública: cubre cientos
de tiendas chilenas y, además del precio, da el identificador del mismo artículo
en todas ellas.

No hereda de `FuenteJsonLd` porque no lee HTML. `Fuente` es un protocolo, no una
jerarquía, y esta fuente lo cumple por su cuenta.
"""

import logging
import re
import unicodedata

from fuentes.base import Captura
from nucleo.normalizador import a_entero

registro = logging.getLogger(__name__)

_NO_ALFANUM = re.compile(r"[^a-z0-9]+")


def identificador_de_tienda(nombre: str) -> str:
    """`AbcDin` -> `abcdin`; `PC Factory` -> `pc-factory`.

    El identificador sale del nombre y no del número que SoloTodo le da, para
    que la configuración se pueda leer. El precio es que un cambio de nombre en
    su catálogo duplicaría los productos de esa tienda; está asumido en la spec.
    """
    sin_acentos = (
        unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii")
    )
    return _NO_ALFANUM.sub("-", sin_acentos.lower()).strip("-")


def captura_de_entidad(
    entidad: dict, tiendas: dict[int, str], excluidas: set[str]
) -> Captura | None:
    """La Captura de una entidad, o None si no hay nada utilizable que guardar.

    `tienda` es la tienda REAL: el producto está en AbcDin, y SoloTodo es solo
    quien nos lo cuenta.
    """
    registro_activo = entidad.get("active_registry")
    if not registro_activo:
        return None   # la tienda ya no lo ofrece

    nombre_tienda = tiendas.get(entidad.get("store"))
    if nombre_tienda is None:
        registro.warning(
            "solotodo: entidad %s de una tienda desconocida (%s)",
            entidad.get("id"),
            entidad.get("store"),
        )
        return None

    tienda = identificador_de_tienda(nombre_tienda)
    if tienda in excluidas:
        return None   # la cubrimos en directo, con más precisión

    interno = a_entero(registro_activo.get("offer_price"))
    sku = str(entidad.get("sku") or "").strip()
    titulo = str(entidad.get("name") or "").strip()
    url = str(entidad.get("external_url") or "").strip()
    if interno is None or not sku or not titulo or not url:
        registro.warning("solotodo: entidad %s incompleta", entidad.get("id"))
        return None

    producto = entidad.get("product") or {}

    return Captura(
        tienda=tienda,
        sku_externo=sku,
        titulo=titulo,
        url=url,
        precio_internet=interno,
        precio_normal=a_entero(registro_activo.get("normal_price")),
        precio_tarjeta=None,   # SoloTodo no publica precios con tarjeta
        tarjeta=None,
        disponible=bool(registro_activo.get("is_available")),
        ean=str(entidad["ean"]) if entidad.get("ean") else None,
        producto_solotodo=producto.get("id") if isinstance(producto, dict) else None,
    )
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **124 pasadas** (114 + 10: 7 casos sueltos + 3 del `parametrize`).

- [ ] **Paso 5: Commit**

```bash
git add src/fuentes/solotodo.py tests/test_solotodo.py tests/fixtures/solotodo_entidades.json
git commit -m "Fuentes: de una entidad de SoloTodo a una Captura, con la tienda real"
```

---

### Tarea 3: La fuente: buscar y obtener

**Archivos:**
- Modificar: `src/fuentes/solotodo.py`
- Prueba: `tests/test_solotodo.py`

**Interfaces:**
- Consume: `Referencia`, `Transporte`, `TiendaBloqueada`, `captura_de_entidad`.
- Produce: `fuentes.solotodo.SoloTodo(transporte, excluidas=())` con `nombre = "solotodo"`,
  `buscar(termino, limite) -> list[Captura]` y `obtener(referencias) -> list[Captura]`.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_solotodo.py
from fuentes.base import Referencia
from fuentes.solotodo import SoloTodo
from fuentes.transporte import TiendaBloqueada

CATALOGO = json.dumps([{"id": 30, "name": "AbcDin"}, {"id": 9, "name": "Falabella"}])
BUSQUEDA = json.dumps({"count": 2, "results": [ENTIDADES[0], ENTIDADES[2]]})


def transporte_de(mapa):
    pedidas = []

    def traer(url):
        pedidas.append(url)
        if url not in mapa:
            raise TiendaBloqueada(f"sin respuesta para {url}")
        return mapa[url]

    return traer, pedidas


def test_la_busqueda_pide_el_catalogo_una_vez_y_luego_no():
    """El catálogo de tiendas no cambia dentro de un ciclo."""
    traer, pedidas = transporte_de({
        "https://api.solotodo.com/stores/": CATALOGO,
        "https://api.solotodo.com/entities/?search=notebook&is_active=true": BUSQUEDA,
    })
    fuente = SoloTodo(traer, excluidas=["paris", "falabella"])

    fuente.buscar("notebook", limite=5)
    fuente.buscar("notebook", limite=5)

    assert pedidas.count("https://api.solotodo.com/stores/") == 1


def test_la_busqueda_descarta_las_tiendas_excluidas():
    traer, _ = transporte_de({
        "https://api.solotodo.com/stores/": CATALOGO,
        "https://api.solotodo.com/entities/?search=notebook&is_active=true": BUSQUEDA,
    })
    capturas = SoloTodo(traer, excluidas=["paris", "falabella"]).buscar("notebook", limite=5)

    assert [c.tienda for c in capturas] == ["abcdin"]


def test_la_busqueda_respeta_el_limite():
    muchas = json.dumps({"count": 2, "results": [ENTIDADES[0], ENTIDADES[0]]})
    traer, _ = transporte_de({
        "https://api.solotodo.com/stores/": CATALOGO,
        "https://api.solotodo.com/entities/?search=notebook&is_active=true": muchas,
    })
    assert len(SoloTodo(traer).buscar("notebook", limite=1)) == 1


def test_el_termino_se_codifica():
    traer, pedidas = transporte_de({"https://api.solotodo.com/stores/": CATALOGO})
    SoloTodo(traer).buscar("notebook 16 gb", limite=5)
    assert pedidas[-1] == (
        "https://api.solotodo.com/entities/?search=notebook+16+gb&is_active=true"
    )


def test_un_catalogo_inalcanzable_deja_la_busqueda_en_vacio():
    traer, _ = transporte_de({})   # ni siquiera el catálogo responde
    assert SoloTodo(traer).buscar("notebook", limite=5) == []


def test_una_busqueda_bloqueada_devuelve_vacio():
    traer, _ = transporte_de({"https://api.solotodo.com/stores/": CATALOGO})
    assert SoloTodo(traer).buscar("notebook", limite=5) == []


def test_obtener_pide_cada_entidad_y_una_caida_no_tumba_las_demas():
    traer, pedidas = transporte_de({
        "https://api.solotodo.com/stores/": CATALOGO,
        "https://api.solotodo.com/entities/1379496/": json.dumps(ENTIDADES[0]),
    })
    capturas = SoloTodo(traer).obtener([
        Referencia("abcdin", "https://api.solotodo.com/entities/999999/"),
        Referencia("abcdin", "https://api.solotodo.com/entities/1379496/"),
    ])
    assert len(capturas) == 1
    assert capturas[0].sku_externo == "AD-100"
```

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_solotodo.py -v`
Esperado: FALLA con `ImportError: cannot import name 'SoloTodo'`.

- [ ] **Paso 3: Implementar**

Añade arriba `import json` y `from urllib.parse import urlencode`, más
`from fuentes.base import Captura, Referencia, Transporte` y
`from fuentes.transporte import TiendaBloqueada`. Luego, al final del módulo:

```python
class SoloTodo:
    nombre = "solotodo"
    BASE = "https://api.solotodo.com"

    def __init__(self, transporte: Transporte, excluidas=()) -> None:
        self._traer = transporte
        self._excluidas = {identificador_de_tienda(t) for t in excluidas}
        self._tiendas: dict[int, str] | None = None

    def _catalogo(self) -> dict[int, str] | None:
        """Los nombres de las tiendas, pedidos una sola vez.

        Se piden de forma perezosa: un ciclo que no use esta fuente no gasta
        ninguna petición. Devuelve None si la API no responde, y entonces no se
        puede construir la identidad de ninguna captura.
        """
        if self._tiendas is None:
            try:
                crudo = self._traer(f"{self.BASE}/stores/")
            except TiendaBloqueada as error:
                registro.warning("solotodo: no se pudo leer el catálogo (%s)", error)
                return None
            self._tiendas = {t["id"]: t["name"] for t in json.loads(crudo)}
        return self._tiendas

    def buscar(self, termino: str, limite: int) -> list[Captura]:
        tiendas = self._catalogo()
        if tiendas is None:
            return []

        consulta = urlencode({"search": termino, "is_active": "true"})
        url = f"{self.BASE}/entities/?{consulta}"
        try:
            datos = json.loads(self._traer(url))
        except TiendaBloqueada as error:
            registro.warning("solotodo: búsqueda bloqueada para %r (%s)", termino, error)
            return []

        capturas: list[Captura] = []
        for entidad in datos.get("results") or []:
            if len(capturas) >= limite:
                break
            captura = captura_de_entidad(entidad, tiendas, self._excluidas)
            if captura is not None:
                capturas.append(captura)
        return capturas

    def obtener(self, referencias: list[Referencia]) -> list[Captura]:
        tiendas = self._catalogo()
        if tiendas is None:
            return []

        capturas: list[Captura] = []
        for referencia in referencias:
            try:
                entidad = json.loads(self._traer(referencia.url))
            except TiendaBloqueada as error:
                registro.warning(
                    "solotodo: no se pudo leer %s (%s)", referencia.url, error
                )
                continue
            captura = captura_de_entidad(entidad, tiendas, self._excluidas)
            if captura is None:
                registro.warning(
                    "solotodo: sin datos utilizables en %s", referencia.url
                )
                continue
            capturas.append(captura)
        return capturas
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **131 pasadas** (124 + 7).

- [ ] **Paso 5: Commit**

```bash
git add src/fuentes/solotodo.py tests/test_solotodo.py
git commit -m "Fuentes: SoloTodo busca y obtiene, con el catálogo de tiendas cacheado"
```

---

### Tarea 4: La lista de deseos aprende a nombrar su fuente

Hoy el orquestador busca la fuente por el nombre de la tienda. Con SoloTodo esos dos valores dejan
de coincidir: un producto de `abcdin` se captura con la fuente `solotodo`.

**Archivos:**
- Modificar: `runner.py`
- Prueba: `tests/test_runner.py`

**Interfaces:**
- Produce: cada entrada de `cargar_lista_deseos` lleva `"fuente"`, que vale lo que `fuente:` diga
  en el YAML o, si no lo dice, lo mismo que `tienda`.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_runner.py


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
```

El ayudante `captura()` de ese archivo ya admite `tienda`, así que no hay que tocarlo.

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_runner.py -v`
Esperado: las dos primeras fallan con `KeyError: 'fuente'`, y la tercera con
`sin fuente para la tienda 'abcdin'` y `enviadas == 0`.

- [ ] **Paso 3: Implementar**

En `cargar_lista_deseos`, añade la clave a los dos diccionarios que construye:

```python
        vigilados.append(
            {
                "tienda": entrada["tienda"],
                "fuente": entrada.get("fuente") or entrada["tienda"],
                "url": entrada["url"],
                "reglas": reglas,
            }
        )
```

```python
        busquedas.append(
            {
                "tienda": entrada["tienda"],
                "fuente": entrada.get("fuente") or entrada["tienda"],
                "termino": entrada["termino"],
                "reglas": reglas,
            }
        )
```

En `ejecutar_ciclo`, los dos bucles buscan por `fuente` y el aviso nombra lo que no se encontró:

```python
    for vigilado in vigilados:
        fuente = fuentes.get(vigilado["fuente"])
        if fuente is None:
            registro.warning("sin fuente %r para la tienda %r",
                             vigilado["fuente"], vigilado["tienda"])
            continue
```

y lo mismo en el bucle de búsquedas, con `busqueda["fuente"]` y `busqueda["tienda"]`.

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **134 pasadas** (131 + 3).

- [ ] **Paso 5: Commit**

```bash
git add runner.py tests/test_runner.py
git commit -m "Orquestador: una entrada puede declarar qué fuente la captura"
```

---

### Tarea 5: Cableado y sonda manual

**Archivos:**
- Modificar: `runner.py`, `config/config.yaml`, `config/lista_deseos.yaml`, `README.md`
- Crear: `herramientas/sonda_solotodo.py`

- [ ] **Paso 1: Configurar y registrar la fuente**

En `config/config.yaml`, una sección nueva:

```yaml
solotodo:
  # Las tiendas que ya cubrimos con un adaptador directo. SoloTodo las ignora:
  # su `external_url` es el mismo que el nuestro, así que caerían en la misma
  # fila discrepando en el precio de tarjeta, y el histórico crecería una fila
  # por ciclo sin que nada hubiera cambiado.
  tiendas_excluidas: [paris, falabella]
```

En `config/lista_deseos.yaml`, una búsqueda nueva:

```yaml
  - termino: notebook
    tienda: solotodo
    fuente: solotodo
    reglas:
      precio_maximo: 700000
```

En `runner.py`, importa `from fuentes.solotodo import SoloTodo` y amplía `main()`:

```python
    fuentes = {
        "paris": Paris(transporte),
        "falabella": Falabella(transporte),
        "solotodo": SoloTodo(
            transporte,
            excluidas=config.get("solotodo", {}).get("tiendas_excluidas", []),
        ),
    }
```

- [ ] **Paso 2: Escribir la sonda**

```python
# herramientas/sonda_solotodo.py
"""Comprueba contra api.solotodo.com que la fuente sigue funcionando.

No es una prueba automática: toca la red y depende de que haya entidades
activas. Se ejecuta a mano cuando algo huele mal o antes de dar por buena una
entrega.

    python herramientas/sonda_solotodo.py "notebook"
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.solotodo import SoloTodo                # noqa: E402
from fuentes.transporte import crear_transporte      # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    termino = sys.argv[1] if len(sys.argv) > 1 else "notebook"

    fuente = SoloTodo(crear_transporte(), excluidas=["paris", "falabella"])
    capturas = fuente.buscar(termino, limite=5)

    if not capturas:
        print(f"FALLA: la búsqueda de {termino!r} no devolvió nada.")
        print("Puede que la API haya cambiado de forma, o que esté bloqueando.")
        return 1

    print(f"OK: {len(capturas)} capturas para {termino!r}\n")
    for c in capturas:
        print(f"  [{c.tienda}] {c.titulo[:52]}")
        print(f"    oferta={c.precio_internet}  normal={c.precio_normal}  "
              f"stock={c.disponible}  producto_solotodo={c.producto_solotodo}")
        print(f"    {c.url[:88]}")

    directas = {"paris", "falabella"}
    coladas = sorted({c.tienda for c in capturas} & directas)
    if coladas:
        print(f"\nAVISO: se colaron tiendas que cubrimos en directo: {coladas}")
        print("La exclusión no está funcionando.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Paso 3: Ejecutarla contra la red**

Ejecuta: `python herramientas/sonda_solotodo.py notebook`
Esperado: `OK` con cinco capturas de tiendas que **no** son Paris ni Falabella, precios enteros
plausibles y algún `producto_solotodo` con valor.

Si falla, **no toques las pruebas ni las fixtures**: el fallo está en que la API cambió. Mira la
respuesta a mano, ajusta la fuente, y actualiza la *fixture* después.

- [ ] **Paso 4: Comprobar la migración sobre la base real**

Este es el criterio de éxito que no se puede repetir. **Antes de ejecutar nada, copia la base:**

```bash
cp data/tracker.db data/tracker.db.antes-de-2b
python -c "import sqlite3; c=sqlite3.connect('data/tracker.db.antes-de-2b'); print('antes -> productos:', c.execute('SELECT COUNT(*) FROM productos').fetchone()[0], '| historico:', c.execute('SELECT COUNT(*) FROM historico_precios').fetchone()[0])"
```

Luego abre la base real una vez y comprueba que ganó la columna sin perder nada:

```bash
python -c "import sys; sys.path.insert(0,'src'); from almacen.conexion import abrir; c=abrir('data/tracker.db'); print('columnas:', [f['name'] for f in c.execute('PRAGMA table_info(productos)')]); print('despues -> productos:', c.execute('SELECT COUNT(*) FROM productos').fetchone()[0], '| historico:', c.execute('SELECT COUNT(*) FROM historico_precios').fetchone()[0])"
```

Los dos recuentos deben coincidir con los de antes, y `producto_solotodo` debe aparecer en la lista.

- [ ] **Paso 5: Ejecutar el ciclo real, dos veces**

```bash
python runner.py
python runner.py
```

Esperado: la primera pasada da de alta productos de tiendas nuevas y guarda su
`producto_solotodo`; la segunda **no añade filas al histórico ni manda alertas**. Compruébalo:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/tracker.db'); print('por tienda:', c.execute('SELECT tienda, COUNT(*) FROM productos GROUP BY tienda').fetchall()); print('con identificador de solotodo:', c.execute('SELECT COUNT(*) FROM productos WHERE producto_solotodo IS NOT NULL').fetchone()[0]); print('historico:', c.execute('SELECT COUNT(*) FROM historico_precios').fetchone()[0])"
```

- [ ] **Paso 6: Comprobar que las tiendas de antes siguen bien**

```bash
python herramientas/sonda_paris.py notebook
python herramientas/sonda_falabella.py notebook
```

Las dos deben seguir en verde: la fuente nueva no debía tocar a las que ya funcionaban.

- [ ] **Paso 7: Actualizar el README**

En la sección de pruebas, añade la sonda nueva junto a las otras dos. Y en «Cómo está hecho»,
después del párrafo de las fuentes:

```markdown
Además de las tiendas que se leen en directo, **SoloTodo** aporta anchura: es un
agregador con API pública que cubre cientos de tiendas chilenas. Sus capturas
llevan la tienda real —`abcdin`, no `solotodo`—, porque el producto está allí.
Las tiendas que ya tenemos en directo se excluyen: su `external_url` es el mismo
que el nuestro y las dos fuentes discrepan en el precio de tarjeta, así que
alternándose harían crecer el histórico una fila por ciclo.

De SoloTodo viene también el identificador del mismo artículo en todas las
tiendas. Todavía no se usa para nada: se guarda porque es el dato que hará
posible comparar precios entre tiendas, y no se puede recuperar hacia atrás.
```

- [ ] **Paso 8: Commit**

```bash
git add runner.py config herramientas/sonda_solotodo.py README.md
git commit -m "Cablea SoloTodo en el ciclo y añade su sonda manual"
```

---

## Qué queda fuera

- **El emparejado entre tiendas.** El identificador se guarda desde esta etapa; la vista de «el
  mismo producto en varias tiendas» se diseña cuando haya meses de histórico con él dentro.
- **Avisar de datos rancios.** Cada entidad trae `last_pricing_update`; permitiría detectar que
  SoloTodo dejó de actualizar una tienda y que el silencio no es nuestro. No entra aquí.
- **El precio con tarjeta de las tiendas que cubre SoloTodo.** No lo publica. Una tienda que
  importe de verdad merece su adaptador directo.
