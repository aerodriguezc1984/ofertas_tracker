# Etapa 4 — La nube y el portal: plan de implementación

> **Para agentes ejecutores:** SUB-SKILL OBLIGATORIA: usa
> `superpowers:subagent-driven-development` (recomendada) o
> `superpowers:executing-plans` para ejecutar este plan tarea a tarea. Los pasos
> usan casillas (`- [ ]`) para el seguimiento.

**Objetivo:** que el rastreador corra solo en GitHub Actions cada hora, conserve su histórico entre
ejecuciones, y publique un portal web que se pueda mirar desde cualquier sitio.

**Arquitectura:** dos repositorios. El privado guarda el código y la base como **volcado SQL en
texto**; el flujo horario lo restaura, corre el ciclo de siempre, lo vuelve a volcar, genera una
página estática y la publica en un repositorio público que GitHub Pages sirve. El motor no se toca:
el portal solo lee.

**Tecnologías:** Python 3.12, SQLite, `requests`, `PyYAML`, `python-dotenv`, `pytest`. El portal es
HTML, CSS y JavaScript a mano, sin dependencias ni cadena de construcción.

**Spec:** `docs/specs/2026-10-12-etapa-4-nube-y-portal-design.md`

**Punto de partida:** `main` @ `ec68a68`. **205 pruebas en verde.** 599 productos de 40 tiendas.

## Restricciones globales

- Python 3.12. Dependencias permitidas: `requests`, `PyYAML`, `python-dotenv`, `pytest`. **Nada
  más**, y el portal tampoco añade ninguna.
- **Todo en español**: identificadores, docstrings, comentarios y mensajes de commit.
- **El dinero es `int` de pesos chilenos.** Ningún `float` toca un precio. El porcentaje es el único
  flotante, y solo se compara y se imprime.
- **Ninguna prueba accede a la red.**
- **Ningún secreto en logs, en errores, ni en el repositorio.** El token de Telegram va en la URL de
  la petición, así que de cualquier excepción solo se conserva el nombre de su tipo.
- **Las capas no se cruzan**: `nucleo` no importa `sqlite3`, `requests` ni `almacen`; `fuentes` no
  importa `sqlite3`. `portal` lee de `almacen`, nunca al revés. Lo vigila `tests/test_capas.py`.
- **Las pruebas existentes no se tocan.** Si una se pone roja, lo que se arregla es el código.
- **El motor no se toca.** Esta etapa no cambia la captura, el histórico, las alertas ni la
  comparación. Si te ves editando `src/nucleo/`, `src/fuentes/` o la lógica de `runner.py`, para.
- Cada prueba nueva se valida rompiendo a propósito lo que dice medir, y comprobando que se pone
  roja **por el motivo correcto**. Un rojo por `KeyError` donde se esperaba un valor equivocado
  significa que la mutación o la prueba están mal.

## Review Focus

Cinco entradas que la spec implica y que ninguna prueba obvia ejercita. Cada una tiene su prueba
asignada a la tarea que posee el código:

1. **Un volcado vacío restaurado sobre un histórico que existía.** Si un ciclo falla a mitad y deja
   un volcado trunco, restaurarlo borraría 599 productos. Es el fallo más caro posible de esta
   etapa. → **Tarea 1**
2. **Un producto con una sola lectura.** No tiene precio anterior: el portal no puede dividir por
   `None` ni inventarse un descuento. → **Tarea 2**
3. **Un precio que SUBIÓ.** El descuento sale negativo. No es una oferta y no debe mostrarse como
   tal. → **Tarea 2**
4. **Un producto sin identificador de artículo.** No se puede agrupar; va suelto. Agruparlo por
   título sería adivinar. → **Tarea 2**
5. **Un título con comillas, acentos y signos de menor que.** Tiene que sobrevivir al JSON y no
   romper la página. Los títulos reales ya traen `"`, `—` y `15,6"`. → **Tarea 2 y Tarea 3**

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/almacen/volcado.py` | **nuevo** — volcar la base a SQL y restaurarla desde él |
| `src/portal/__init__.py` | **nuevo** — vacío, marca el paquete |
| `src/portal/datos.py` | **nuevo** — de la base al diccionario que consume la página |
| `src/portal/plantilla.html` | **nuevo** — el portal entero: marcado, estilos y guion |
| `herramientas/generar_portal.py` | **nuevo** — escribe `index.html` y `datos.json` en una carpeta |
| `.gitignore` | + la excepción para que el volcado SÍ se versione |
| `config/lista_deseos.yaml` | Paris comentado, con su porqué |
| `.github/workflows/ciclo.yml` | **nuevo** — el ciclo horario, el volcado y la publicación |

---

# Tarea 1: El volcado — que el histórico sobreviva a la máquina

Cada ejecución en la nube arranca en una máquina nueva. Sin esto, el rastreador empezaría de cero
cada hora y no tendría histórico jamás.

**Archivos:**
- Crear: `src/almacen/volcado.py`
- Modificar: `.gitignore`
- Prueba: `tests/test_volcado.py` (nuevo)

**Interfaces:**
- Consume: `abrir(ruta)` de `almacen.conexion`, que aplica el esquema y las migraciones.
- Produce: `volcar(con, ruta_sql) -> int` (devuelve cuántas sentencias escribió) y
  `restaurar(ruta_sql, ruta_db) -> bool` (devuelve si restauró algo). Los usa la Tarea 4.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# tests/test_volcado.py — archivo nuevo
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
    """Review Focus 5: los títulos reales llevan comillas dentro."""
    origen = _base_con_datos(tmp_path / "origen.db", cuantos=1)
    sql = tmp_path / "volcado.sql"
    volcar(origen, sql)
    restaurar(sql, tmp_path / "destino.db")

    titulo = abrir(tmp_path / "destino.db").execute(
        "SELECT titulo FROM productos"
    ).fetchone()[0]
    assert titulo == 'Notebook 15,6" Full HD'


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
```

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_volcado.py -v`
Esperado: todas fallan en la importación, con
`ModuleNotFoundError: No module named 'almacen.volcado'`.

- [ ] **Paso 3: Implementar**

```python
# src/almacen/volcado.py — archivo nuevo
"""El histórico, en un archivo de texto que sobrevive a la máquina.

En la nube cada ejecución arranca en un equipo nuevo, así que la base tiene que
viajar con el repositorio. Viaja como SQL y no como archivo `.db` por dos
motivos: git no sabe comprimir SQLite —cualquier cambio reescribe páginas
dispersas y el archivo entero cuenta como contenido nuevo— y un volcado en texto
se puede leer y arreglar a mano el día que algo se corrompa.
"""

import sqlite3
from pathlib import Path

# Un volcado de una base con esquema pero sin datos ronda las 15 sentencias:
# las de creación de tablas y poco más. Por debajo de este número no hay filas
# que valga la pena restaurar.
SENTENCIAS_DE_UN_ESQUEMA_VACIO = 25


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
    """
    ruta_sql, ruta_db = Path(ruta_sql), Path(ruta_db)
    if not ruta_sql.exists():
        return False

    sql = ruta_sql.read_text(encoding="utf-8")
    if sql.count(";") < SENTENCIAS_DE_UN_ESQUEMA_VACIO:
        return False

    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    if ruta_db.exists():
        ruta_db.unlink()

    con = sqlite3.connect(ruta_db, isolation_level=None)
    try:
        con.executescript(sql)
    finally:
        con.close()
    return True
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **210 pasadas** (205 + 5).

- [ ] **Paso 5: Dejar que el volcado sí se versione**

`.gitignore` ignora `data/` entero, así que el volcado quedaría fuera. Añade la excepción
**justo debajo** de la línea `data/`, con su explicación:

```gitignore
data/
# ...pero el volcado SÍ se versiona: es como el histórico viaja entre
# ejecuciones en la nube, donde cada una arranca en una máquina nueva.
!data/volcado.sql
```

Compruébalo:

```bash
git check-ignore -v data/volcado.sql || echo "NO ignorado: correcto"
```

Esperado: `NO ignorado: correcto`.

- [ ] **Paso 6: Falsar las pruebas nuevas**

Una por una, restaurando entre medias:

1. **La guarda del volcado vacío.** Cambia `if sql.count(";") < SENTENCIAS_DE_UN_ESQUEMA_VACIO:`
   por `if False:`.
   Esperado: `test_restaurar_un_volcado_sin_productos_no_borra_lo_que_habia` roja porque la base
   de destino se queda en **0 productos** en vez de 5. Si cae con una excepción en vez de con el
   recuento, la prueba no mide lo que dice.
2. **El borrado previo.** Quita `if ruta_db.exists(): ruta_db.unlink()`.
   Esperado: `test_volcar_y_restaurar_devuelve_la_misma_base` roja, porque `executescript` choca
   contra las tablas que `abrir` ya creó.

- [ ] **Paso 7: Commit**

```bash
git add src/almacen/volcado.py tests/test_volcado.py .gitignore
git commit -m "Almacén: el histórico viaja como SQL, no como archivo binario"
```

---

# Tarea 2: Los datos del portal

**Archivos:**
- Crear: `src/portal/__init__.py`, `src/portal/datos.py`
- Prueba: `tests/test_portal_datos.py` (nuevo)

**Interfaces:**
- Consume: la base que abre `almacen.conexion.abrir`.
- Produce: `datos_del_portal(con, ventana_dias: int = 90) -> dict`. La usa la Tarea 3.

El diccionario tiene esta forma exacta:

```python
{
    "generado_el": "2026-10-12 03:14:00",
    "productos": 599,
    "tiendas": 40,
    "ofertas": [
        {
            "articulo": 269594,          # o None si SoloTodo no lo reconoce
            "tienda": "ripley",
            "titulo": 'Notebook 15,6" Full HD',
            "url": "https://...",
            "imagen": "https://..." ,     # o None
            "disponible": True,
            "precio": 349990,
            "fecha": "2026-10-11 21:44",
            "precio_anterior": 887990,    # o None si solo hay una lectura
            "fecha_anterior": "2026-10-09 18:20",
            "descuento_pct": 61,          # entero; 0 si no hay bajada
            "minimo_historico": 349990,
        },
    ],
}
```

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# tests/test_portal_datos.py — archivo nuevo
"""Lo que el portal enseña sale de aquí, y solo lee."""

from almacen.conexion import abrir
from almacen.operaciones import alta_o_actualiza_producto, registrar_si_cambio
from fuentes.base import Captura
from portal.datos import datos_del_portal


def captura(sku="S1", precio=100000, tienda="paris", titulo="Notebook", articulo=None):
    return Captura(
        tienda=tienda,
        sku_externo=sku,
        titulo=titulo,
        url=f"https://www.{tienda}.cl/n-{sku}.html",
        precio_internet=precio,
        producto_solotodo=articulo,
    )


def _con_precios(con, precios, **kw):
    """Da de alta un producto y le registra varios precios, en orden."""
    producto_id = None
    for i, precio in enumerate(precios):
        unica = captura(precio=precio, **kw)
        producto_id = alta_o_actualiza_producto(con, unica)
        registrar_si_cambio(con, producto_id, unica)
        # Las marcas de tiempo tienen resolución de segundo: se separan a mano
        # para que el orden del histórico sea el de inserción y no un empate.
        con.execute(
            "UPDATE historico_precios SET capturado_el = ? WHERE producto_id = ?"
            " AND precio_internet = ?",
            (f"2026-10-0{i + 1} 10:00:00", producto_id, precio),
        )
    return producto_id


def test_una_bajada_trae_el_antes_y_el_despues_con_fechas(tmp_path):
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [887990, 349990], sku="B1")

    oferta = datos_del_portal(con)["ofertas"][0]
    assert oferta["precio"] == 349990
    assert oferta["precio_anterior"] == 887990
    assert oferta["fecha_anterior"].startswith("2026-10-01")
    assert oferta["fecha"].startswith("2026-10-02")
    assert oferta["descuento_pct"] == 61


# --- Review Focus 2: una sola lectura ---
def test_un_producto_con_una_sola_lectura_no_tiene_anterior(tmp_path):
    """Sin precio previo no hay descuento que calcular, y dividir por `None`
    tumbaría la generación entera del portal."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="U1")

    oferta = datos_del_portal(con)["ofertas"][0]
    assert oferta["precio_anterior"] is None
    assert oferta["fecha_anterior"] is None
    assert oferta["descuento_pct"] == 0


# --- Review Focus 3: el precio subió ---
def test_un_precio_que_subio_no_es_una_oferta(tmp_path):
    """El descuento saldría negativo. No es una rebaja: es lo contrario."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000, 150000], sku="S2")

    oferta = datos_del_portal(con)["ofertas"][0]
    assert oferta["precio"] == 150000
    assert oferta["precio_anterior"] == 100000
    assert oferta["descuento_pct"] == 0


# --- Review Focus 4: sin identificador de artículo ---
def test_un_producto_sin_articulo_va_suelto(tmp_path):
    """Agruparlo por título sería adivinar, y aquí no se adivina."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="A1", articulo=None)
    _con_precios(con, [120000], sku="A2", tienda="falabella", articulo=None)

    ofertas = datos_del_portal(con)["ofertas"]
    assert len(ofertas) == 2
    assert all(o["articulo"] is None for o in ofertas)


def test_el_mismo_articulo_en_dos_tiendas_sale_dos_veces_con_su_articulo(tmp_path):
    """El portal agrupa al pintar; los datos traen las dos filas con la misma
    etiqueta, que es lo que permite agrupar sin adivinar."""
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="M1", articulo=269594)
    _con_precios(con, [120000], sku="M2", tienda="falabella", articulo=269594)

    ofertas = datos_del_portal(con)["ofertas"]
    assert sorted(o["articulo"] for o in ofertas) == [269594, 269594]


# --- Review Focus 5: títulos con comillas ---
def test_un_titulo_con_comillas_sobrevive(tmp_path):
    import json

    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="C1", titulo='Monitor 15,6" <Full HD> & más')

    datos = datos_del_portal(con)
    ida_y_vuelta = json.loads(json.dumps(datos, ensure_ascii=False))
    assert ida_y_vuelta["ofertas"][0]["titulo"] == 'Monitor 15,6" <Full HD> & más'


def test_la_cabecera_cuenta_productos_y_tiendas(tmp_path):
    con = abrir(tmp_path / "p.db")
    _con_precios(con, [100000], sku="P1", tienda="paris")
    _con_precios(con, [100000], sku="P2", tienda="falabella")

    datos = datos_del_portal(con)
    assert datos["productos"] == 2
    assert datos["tiendas"] == 2
    assert datos["generado_el"]
```

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_portal_datos.py -v`
Esperado: todas fallan con `ModuleNotFoundError: No module named 'portal'`.

- [ ] **Paso 3: Implementar**

Crea `src/portal/__init__.py` **vacío** (una línea de docstring basta) y después:

```python
# src/portal/datos.py — archivo nuevo
"""De la base a lo que el portal enseña. Solo lee.

El descuento que sale de aquí es entre DOS LECTURAS NUESTRAS, fechadas las dos.
Nunca el precio tachado de la tienda: ese «antes» es de ellos y miente la mitad
de las veces. Es la misma invariante que rige las alertas desde la Etapa 1, y el
portal no la relaja.
"""

import sqlite3
from datetime import datetime, timezone

# `LAG` da la lectura previa del mismo producto sin traerse el histórico entero.
# El desempate por `id` hace falta porque `capturado_el` tiene resolución de
# segundo y dos lecturas pueden empatar.
_CONSULTA = """
WITH ordenadas AS (
    SELECT h.producto_id,
           h.precio_internet,
           h.capturado_el,
           h.disponible,
           LAG(h.precio_internet) OVER (
               PARTITION BY h.producto_id ORDER BY h.capturado_el, h.id
           ) AS precio_anterior,
           LAG(h.capturado_el) OVER (
               PARTITION BY h.producto_id ORDER BY h.capturado_el, h.id
           ) AS fecha_anterior,
           ROW_NUMBER() OVER (
               PARTITION BY h.producto_id ORDER BY h.capturado_el DESC, h.id DESC
           ) AS fila
      FROM historico_precios h
)
SELECT p.producto_solotodo AS articulo,
       p.tienda,
       p.titulo,
       p.url,
       p.imagen_url,
       o.disponible,
       o.precio_internet,
       o.capturado_el,
       o.precio_anterior,
       o.fecha_anterior,
       (SELECT MIN(h2.precio_internet)
          FROM historico_precios h2
         WHERE h2.producto_id = p.id
           AND h2.capturado_el >= datetime('now', :ventana)) AS minimo
  FROM ordenadas o
  JOIN productos p ON p.id = o.producto_id
 WHERE o.fila = 1
 ORDER BY p.tienda, p.titulo
"""


def _descuento(precio: int, anterior: int | None) -> int:
    """Cuánto bajó, en porcentaje entero. Cero si no bajó o no hay con qué."""
    if not anterior or anterior <= 0 or precio >= anterior:
        # Un precio que subió no es una oferta, y sin lectura previa no hay
        # nada que comparar. En los dos casos el portal no enseña insignia.
        return 0
    return round((anterior - precio) / anterior * 100)


def datos_del_portal(con: sqlite3.Connection, ventana_dias: int = 90) -> dict:
    """La foto que consume la página. No escribe nada."""
    filas = con.execute(
        _CONSULTA, {"ventana": f"-{int(ventana_dias)} days"}
    ).fetchall()

    ofertas = []
    for f in filas:
        ofertas.append(
            {
                "articulo": f["articulo"],
                "tienda": f["tienda"],
                "titulo": f["titulo"],
                "url": f["url"],
                "imagen": f["imagen_url"],
                "disponible": bool(f["disponible"]),
                "precio": f["precio_internet"],
                "fecha": f["capturado_el"],
                "precio_anterior": f["precio_anterior"],
                "fecha_anterior": f["fecha_anterior"],
                "descuento_pct": _descuento(f["precio_internet"], f["precio_anterior"]),
                "minimo_historico": f["minimo"],
            }
        )

    return {
        "generado_el": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "productos": len(ofertas),
        "tiendas": len({o["tienda"] for o in ofertas}),
        "ofertas": ofertas,
    }
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **217 pasadas** (210 + 7).

- [ ] **Paso 5: Comprobar que las capas siguen limpias**

Ejecuta: `python -m pytest tests/test_capas.py -v`
Esperado: 2 pasadas. `portal` importa `sqlite3` y eso está permitido: la prueba solo vigila
`nucleo` y `fuentes`.

Y comprueba a mano que nadie importa `portal` desde dentro:

```bash
grep -rn "import portal\|from portal" src/nucleo src/fuentes src/almacen src/avisos || echo "nadie: correcto"
```

Esperado: `nadie: correcto`.

- [ ] **Paso 6: Falsar tres de las pruebas nuevas**

Una por una, restaurando entre medias:

1. **El descuento de un precio que subió.** Cambia `precio >= anterior` por `False` en `_descuento`.
   Esperado: `test_un_precio_que_subio_no_es_una_oferta` roja con un porcentaje **negativo** en vez
   de 0.
2. **La guarda del anterior nulo.** Cambia `if not anterior or ...` por `if False:`.
   Esperado: `test_un_producto_con_una_sola_lectura_no_tiene_anterior` roja con un `TypeError`,
   que aquí **sí** es el motivo correcto: es exactamente la división por `None` que la guarda
   evita.
3. **El desempate del `LAG`.** Quita `, h.id` de las dos cláusulas `ORDER BY` de las ventanas.
   Esperado: `test_una_bajada_trae_el_antes_y_el_despues_con_fechas` sigue verde —las fechas de esa
   prueba son distintas—, y **ninguna** se pone roja. Eso NO es un fallo de la implementación: es
   que ninguna prueba crea dos lecturas en el mismo segundo. Déjalo anotado en el informe y
   restaura; el desempate se queda porque el dato real sí empata.

- [ ] **Paso 7: Commit**

```bash
git add src/portal tests/test_portal_datos.py
git commit -m "Portal: la foto de ofertas, con el antes y el después fechados"
```

---

# Tarea 3: La página

**Archivos:**
- Crear: `src/portal/plantilla.html`, `herramientas/generar_portal.py`
- Prueba: `tests/test_portal_datos.py` (se amplía)

**Interfaces:**
- Consume: `datos_del_portal(con, ventana_dias)` de la Tarea 2.
- Produce: `generar(con, carpeta, ventana_dias) -> tuple[Path, Path]` en
  `herramientas/generar_portal.py`, que devuelve las rutas de `index.html` y `datos.json`.

> **La página pinta con `textContent`, nunca con `innerHTML`.** Los títulos vienen de las tiendas y
> llevan comillas, `&` y signos de menor que. Con `innerHTML` un título rompe el marcado o peor; con
> `textContent` el navegador los trata como texto y no hace falta escapar nada.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_portal_datos.py
import json
from pathlib import Path


def test_generar_escribe_los_dos_archivos(tmp_path):
    from herramientas.generar_portal import generar

    con = abrir(tmp_path / "p.db")
    _con_precios(con, [887990, 349990], sku="G1")

    html, datos = generar(con, tmp_path / "salida")

    assert html.name == "index.html"
    assert datos.name == "datos.json"
    assert html.exists() and datos.exists()


def test_el_json_generado_es_valido_y_trae_las_ofertas(tmp_path):
    from herramientas.generar_portal import generar

    con = abrir(tmp_path / "p.db")
    _con_precios(con, [887990, 349990], sku="G2", titulo='Monitor 15,6" & más')

    _, datos = generar(con, tmp_path / "salida")
    leido = json.loads(datos.read_text(encoding="utf-8"))

    assert leido["ofertas"][0]["titulo"] == 'Monitor 15,6" & más'
    assert leido["ofertas"][0]["descuento_pct"] == 61


def test_la_pagina_no_pinta_datos_con_innerhtml(tmp_path):
    """Los títulos vienen de las tiendas: con `innerHTML` uno con `<` rompe la
    página. La plantilla usa `textContent` y esta prueba lo fija."""
    plantilla = Path("src/portal/plantilla.html").read_text(encoding="utf-8")
    assert "innerHTML" not in plantilla
```

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_portal_datos.py -v`
Esperado: las dos primeras fallan con
`ModuleNotFoundError: No module named 'herramientas.generar_portal'`; la tercera con
`FileNotFoundError` sobre `src/portal/plantilla.html`.

- [ ] **Paso 3: Escribir la plantilla**

Crea `src/portal/plantilla.html` con el portal entero. Requisitos, y el marcador
`__DATOS__` es el único sitio donde se inyecta nada:

- Un solo archivo: `<style>` y `<script>` dentro, **sin ninguna dependencia externa**.
- Carga `datos.json` con `fetch` al arrancar y **cada 30 minutos**
  (`setInterval(cargar, 30 * 60 * 1000)`).
- Muestra **«Última sincronización: …»** con el `generado_el` del JSON, y la hora del último
  refresco del navegador.
- **Búsqueda** instantánea por título, con `input` (sin botón).
- **Filtros**: tienda (lista con casillas), descuento mínimo (0 / 10 / 30 / 50 %), precio mínimo y
  máximo.
- **Orden**: mayor descuento, bajada más reciente, menor precio.
- **Cada tarjeta**: título como enlace a la tienda, nombre de la tienda, precio grande, y si hay
  bajada, la insignia `−61 %` y la línea *$887.990 el 09/10 ➔ $349.990 el 11/10*.
- Los productos **con el mismo `articulo`** se pintan juntos en una tarjeta, con una línea por
  tienda ordenada de más barata a más cara. Los que tienen `articulo: null` van sueltos.
- Los **agotados** (`disponible: false`) se pintan apagados y al final.
- **Todo el pintado con `createElement` y `textContent`.** Ni un `innerHTML`.
- Responsivo: una columna en móvil, rejilla en pantalla ancha. Objetivo mínimo 360 px sin scroll
  horizontal.
- Precios en formato chileno: `$887.990`.
- Textos en español.

- [ ] **Paso 3b: El guion, sin margen de interpretación**

El estilo y el marcado son tuyos. **Estas funciones no**: aquí viven las invariantes, y una
implementación distinta rompe algo que no se ve hasta que pasa. Transcríbelas.

```javascript
// El nombre del archivo lo inyecta el generador, para que la página no dependa
// de dónde se sirva.
const ORIGEN = "__DATOS__";
const MEDIA_HORA = 30 * 60 * 1000;

let ofertas = [];

function pesos(n) {
  // 887990 -> "$887.990", como se escribe en Chile.
  return "$" + n.toLocaleString("es-CL");
}

function dia(marca) {
  // "2026-10-09 18:20" -> "09/10"
  if (!marca) return "";
  const [a, m, d] = marca.slice(0, 10).split("-");
  return `${d}/${m}`;
}

async function cargar() {
  const r = await fetch(ORIGEN + "?t=" + Date.now()); // sin caché del navegador
  const datos = await r.json();
  ofertas = datos.ofertas;
  document.getElementById("sincronizacion").textContent =
    `${datos.productos} productos de ${datos.tiendas} tiendas · datos del ${datos.generado_el} UTC`;
  poblarTiendas();
  pintar();
}

function agrupar(lista) {
  // Mismo artículo en varias tiendas = una tarjeta. Los que no tienen
  // identificador van sueltos: agruparlos por título sería adivinar, y este
  // proyecto no empareja por parecido.
  const grupos = new Map();
  for (const o of lista) {
    const clave = o.articulo === null ? `suelto:${o.tienda}:${o.url}` : `art:${o.articulo}`;
    if (!grupos.has(clave)) grupos.set(clave, []);
    grupos.get(clave).push(o);
  }
  for (const filas of grupos.values()) filas.sort((a, b) => a.precio - b.precio);
  return [...grupos.values()];
}

function tarjeta(filas) {
  // TODO EL PINTADO CON textContent. Ni un innerHTML: los títulos vienen de
  // las tiendas y traen comillas, `&` y signos de menor que.
  const mejor = filas[0];
  const art = document.createElement("article");
  art.className = "tarjeta" + (mejor.disponible ? "" : " agotado");

  const h = document.createElement("h2");
  const enlace = document.createElement("a");
  enlace.href = mejor.url;
  enlace.target = "_blank";
  enlace.rel = "noopener noreferrer";
  enlace.textContent = mejor.titulo;
  h.appendChild(enlace);
  art.appendChild(h);

  if (mejor.descuento_pct > 0) {
    const insignia = document.createElement("span");
    insignia.className = "insignia";
    insignia.textContent = `−${mejor.descuento_pct} %`;
    art.appendChild(insignia);

    const antes = document.createElement("p");
    antes.className = "antes";
    antes.textContent =
      `${pesos(mejor.precio_anterior)} el ${dia(mejor.fecha_anterior)}` +
      ` ➔ ${pesos(mejor.precio)} el ${dia(mejor.fecha)}`;
    art.appendChild(antes);
  }

  const ul = document.createElement("ul");
  for (const f of filas) {
    const li = document.createElement("li");
    li.textContent = `${f.tienda}: ${pesos(f.precio)}`;
    if (!f.disponible) li.textContent += " (agotado)";
    ul.appendChild(li);
  }
  art.appendChild(ul);
  return art;
}

function pintar() {
  const texto = document.getElementById("buscar").value.trim().toLowerCase();
  const minDesc = Number(document.getElementById("descuento").value);
  const minPrecio = Number(document.getElementById("precio-min").value) || 0;
  const maxPrecio = Number(document.getElementById("precio-max").value) || Infinity;
  const tiendas = [...document.querySelectorAll(".tienda:checked")].map((c) => c.value);

  let visibles = ofertas.filter(
    (o) =>
      (!texto || o.titulo.toLowerCase().includes(texto)) &&
      o.descuento_pct >= minDesc &&
      o.precio >= minPrecio &&
      o.precio <= maxPrecio &&
      (tiendas.length === 0 || tiendas.includes(o.tienda))
  );

  const orden = document.getElementById("orden").value;
  const criterios = {
    descuento: (a, b) => b.descuento_pct - a.descuento_pct,
    reciente: (a, b) => (b.fecha || "").localeCompare(a.fecha || ""),
    precio: (a, b) => a.precio - b.precio,
  };
  visibles.sort(criterios[orden]);

  // Los agotados, al final, pase lo que pase con el orden elegido.
  const grupos = agrupar(visibles).sort(
    (a, b) => Number(b[0].disponible) - Number(a[0].disponible)
  );

  const destino = document.getElementById("resultados");
  destino.replaceChildren(...grupos.map(tarjeta));
  document.getElementById("cuantos").textContent = `${visibles.length} ofertas`;
}

document.addEventListener("DOMContentLoaded", () => {
  for (const id of ["buscar", "descuento", "precio-min", "precio-max", "orden"]) {
    document.getElementById(id).addEventListener("input", pintar);
  }
  cargar();
  setInterval(cargar, MEDIA_HORA);
});
```

`poblarTiendas()` la escribes tú: lee las tiendas distintas de `ofertas`, crea una casilla por cada
una dentro de `#tiendas` con `textContent`, y les engancha `pintar` al evento `change`.

- [ ] **Paso 4: Escribir el generador**

```python
# herramientas/generar_portal.py — archivo nuevo
"""Escribe el portal: la página y su foto de datos.

No toca la red ni la base más que para leer. Se ejecuta al final de cada ciclo,
y también a mano para mirar el portal en local:

    python herramientas/generar_portal.py              # a ./portal
    python herramientas/generar_portal.py /otra/ruta
"""

import json
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from almacen.conexion import abrir          # noqa: E402
from portal.datos import datos_del_portal   # noqa: E402

PLANTILLA = RAIZ / "src" / "portal" / "plantilla.html"
MARCADOR = "__DATOS__"


def generar(
    con: sqlite3.Connection, carpeta: Path | str, ventana_dias: int = 90
) -> tuple[Path, Path]:
    """Escribe `index.html` y `datos.json`. Devuelve sus rutas."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)

    datos = datos_del_portal(con, ventana_dias)

    ruta_datos = carpeta / "datos.json"
    ruta_datos.write_text(
        json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # La plantilla trae el nombre del archivo de datos en un marcador, para que
    # la página no dependa de dónde se sirva.
    ruta_html = carpeta / "index.html"
    ruta_html.write_text(
        PLANTILLA.read_text(encoding="utf-8").replace(MARCADOR, "datos.json"),
        encoding="utf-8",
    )
    return ruta_html, ruta_datos


def main() -> int:
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "portal"
    con = abrir(RAIZ / "data" / "tracker.db")
    html, datos = generar(con, destino)
    print(f"escrito {html}")
    print(f"escrito {datos} ({datos.stat().st_size // 1024} KB)")
    print(f"\nábrelo con: start {html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Paso 5: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **220 pasadas** (217 + 3).

- [ ] **Paso 6: Mirarlo de verdad**

```bash
python herramientas/generar_portal.py
```

Ábrelo en el navegador y comprueba a mano, que esto no lo cubre ninguna prueba:

1. Cargan los 599 productos y se ven las tarjetas.
2. La búsqueda filtra según escribes.
3. Los filtros de tienda, descuento y precio hacen lo que dicen.
4. Los tres órdenes cambian el resultado.
5. Una tarjeta con bajada enseña la insignia y el antes/después con fechas.
6. Un artículo que está en varias tiendas sale **una vez**, con sus precios.
7. A 360 px de ancho no hay scroll horizontal.
8. La consola del navegador, sin errores.

Si algo falla aquí, arréglalo antes de comitear y dilo en el informe.

- [ ] **Paso 7: Falsar la prueba del `innerHTML`**

Añade `elemento.innerHTML = "";` en cualquier función de la plantilla.
Esperado: `test_la_pagina_no_pinta_datos_con_innerhtml` roja. Restaura.

- [ ] **Paso 8: Commit**

```bash
git add src/portal/plantilla.html herramientas/generar_portal.py tests/test_portal_datos.py
git commit -m "Portal: la página, sin dependencias y pintando con textContent"
```

---

# Tarea 4: El ciclo en la nube

**Archivos:**
- Crear: `.github/workflows/ciclo.yml`
- Modificar: `config/lista_deseos.yaml`

**Interfaces:**
- Consume: `volcar` y `restaurar` (Tarea 1), `generar` (Tarea 3).

- [ ] **Paso 1: Desactivar Paris, sin borrarlo**

En `config/lista_deseos.yaml`, comenta su búsqueda y explica por qué:

```yaml
  # Paris, desactivado el 2026-10-12. Responde 403 a las direcciones de centro
  # de datos: funciona desde una red doméstica y no desde GitHub. Medido con
  # `herramientas/sonda_entorno.py`. El adaptador `src/fuentes/paris.py` NO se
  # ha tocado y sigue probado: descomentar estas cuatro líneas lo devuelve.
  # - termino: notebook 16gb
  #   tienda: paris
  #   reglas:
  #     precio_maximo: 400000
```

- [ ] **Paso 2: Comprobar que el ciclo sigue funcionando sin Paris**

```bash
python -c "import sys; sys.path.insert(0,'src'); sys.path.insert(0,'.'); import runner; v,b = runner.cargar_lista_deseos('config/lista_deseos.yaml'); print('vigilados:', len(v), '| busquedas:', len(b)); print([x['fuente'] for x in b])"
```

Esperado: `busquedas: 19` y ninguna con fuente `paris`. El vigilado de Paris sigue en la lista: no
se toca, porque un vigilado es una URL concreta y no cuesta una búsqueda.

- [ ] **Paso 3: Escribir el flujo**

```yaml
# .github/workflows/ciclo.yml
name: Ciclo horario

on:
  schedule:
    - cron: "0 * * * *"
  workflow_dispatch:

# Dos ciclos a la vez escribirían la misma base y se pisarían el volcado.
concurrency:
  group: ciclo
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  ciclo:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Instalar dependencias
        run: pip install requests PyYAML python-dotenv

      # El histórico vive en el repositorio como SQL. Si es el primer ciclo no
      # hay nada que restaurar, y arrancar en frío es correcto.
      - name: Restaurar el histórico
        run: |
          python -c "
          import sys; sys.path.insert(0, 'src')
          from almacen.volcado import restaurar
          print('restaurado:', restaurar('data/volcado.sql', 'data/tracker.db'))
          "

      - name: Correr el ciclo
        env:
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python runner.py

      # Los pasos de abajo solo corren si el ciclo terminó bien: un ciclo que
      # falló a mitad no debe commitear una base trunca ni publicar una foto
      # incompleta.
      - name: Volcar el histórico
        run: |
          python -c "
          import sys; sys.path.insert(0, 'src')
          from almacen.conexion import abrir
          from almacen.volcado import volcar
          print('sentencias:', volcar(abrir('data/tracker.db'), 'data/volcado.sql'))
          "

      - name: Commitear el volcado si cambió
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/volcado.sql
          if git diff --cached --quiet; then
            echo "sin cambios en el histórico: no se commitea"
          else
            git commit -m "Histórico del ciclo de $(date -u '+%Y-%m-%d %H:%M UTC')"
            git push
          fi

      - name: Generar el portal
        run: python herramientas/generar_portal.py portal

      - name: Guardar el portal como artefacto
        uses: actions/upload-artifact@v4
        with:
          name: portal
          path: portal/
```

- [ ] **Paso 4: Comprobar que el YAML es válido**

```bash
python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ciclo.yml', encoding='utf-8')); print('pasos:', [s.get('name') or s.get('uses') for s in d['jobs']['ciclo']['steps']])"
```

Esperado: la lista de los **nueve** pasos.

- [ ] **Paso 5: Commit**

```bash
git add .github/workflows/ciclo.yml config/lista_deseos.yaml
git commit -m "El ciclo corre en la nube cada hora y se lleva su histórico"
```

- [ ] **Paso 6: Cargar los secretos**

**Esto lo hace una persona, en el navegador.** El repositorio es
`aerodriguezc1984/ofertas_tracker` → *Settings* → *Secrets and variables* → *Actions* →
*New repository secret*, dos veces:

| Nombre | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el token del bot, el del `.env` local |
| `TELEGRAM_CHAT_ID` | el chat, el del `.env` local |

**El token no se pega en ningún chat ni en ningún archivo del repositorio.** Se copia del `.env`
local al formulario de GitHub y nada más.

- [ ] **Paso 7: Sembrar el histórico**

La nube arrancaría de cero, y hay 599 productos y 657 lecturas que vale la pena conservar. Vuelca
la base local y súbela **una vez**:

```bash
python -c "import sys; sys.path.insert(0,'src'); from almacen.conexion import abrir; from almacen.volcado import volcar; print('sentencias:', volcar(abrir('data/tracker.db'), 'data/volcado.sql'))"
ls -lh data/volcado.sql
git add data/volcado.sql
git commit -m "Siembra el histórico en la nube: 599 productos y 657 lecturas"
git push
```

- [ ] **Paso 8: Lanzarlo y comprobar**

En *Actions* → *Ciclo horario* → *Run workflow*. Cuando termine, comprueba:

1. El paso **Restaurar** dice `restaurado: True`.
2. El paso **Correr el ciclo** termina sin error y el registro trae `ciclo terminado:` y
   `comparación terminada:`.
3. Hay un commit nuevo del bot si algún precio cambió — **o** el paso dice
   `sin cambios en el histórico`, que también es correcto.
4. El artefacto `portal` existe y pesa unos cientos de KB.
5. **Paris no aparece como error** en el registro: no aparece en absoluto.

Si llega una alerta a Telegram, mejor: es la prueba de que los secretos están bien.

---

# Tarea 5: El portal publicado

**Archivos:**
- Modificar: `.github/workflows/ciclo.yml`

**Interfaces:**
- Consume: la carpeta `portal/` que deja la Tarea 3.

- [ ] **Paso 1: Crear el repositorio público**

**Esto lo hace una persona, en el navegador.** En **github.com/new**:

- *Repository name:* `ofertas-web`
- **Public**
- Marca **Add a README file** — hace falta que tenga al menos un commit para activar Pages.
- *Create repository*

Después, en ese repositorio: *Settings* → *Pages* → en *Source* elige **Deploy from a branch**,
rama `main`, carpeta `/ (root)` → *Save*.

- [ ] **Paso 2: Crear el token de publicación**

El `GITHUB_TOKEN` del flujo solo vale para su propio repositorio, así que hace falta uno con permiso
sobre el otro.

En **github.com/settings/tokens/new**: nota `publicar ofertas-web`, marca **`repo`**, genera y
cópialo.

En `aerodriguezc1984/ofertas_tracker` → *Settings* → *Secrets and variables* → *Actions* →
*New repository secret*:

| Nombre | Valor |
|---|---|
| `TOKEN_PUBLICACION` | el token recién creado |

**No lo pegues en ningún chat.** Del formulario de GitHub al formulario de GitHub.

- [ ] **Paso 3: Añadir el paso de publicación**

En `.github/workflows/ciclo.yml`, **después** de *Generar el portal* y **antes** de
*Guardar el portal como artefacto*:

```yaml
      - name: Publicar el portal
        env:
          TOKEN: ${{ secrets.TOKEN_PUBLICACION }}
        run: |
          git clone --depth 1 "https://x-access-token:${TOKEN}@github.com/aerodriguezc1984/ofertas-web.git" publicacion
          cp portal/index.html portal/datos.json publicacion/
          cd publicacion
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add index.html datos.json
          if git diff --cached --quiet; then
            echo "la foto no cambió: no se publica"
          else
            git commit -m "Ofertas del $(date -u '+%Y-%m-%d %H:%M UTC')"
            git push
          fi
```

> **El token va en la URL de `git clone`.** Es la misma trampa que el de Telegram: si ese comando
> falla, su mensaje de error puede arrastrar la URL. GitHub Actions enmascara los secretos en los
> registros, pero no escribas tú esa URL en ningún `echo` ni la metas en un mensaje de error.

- [ ] **Paso 4: Comprobar el YAML y comitear**

```bash
python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ciclo.yml', encoding='utf-8')); print('pasos:', [s.get('name') or s.get('uses') for s in d['jobs']['ciclo']['steps']])"
git add .github/workflows/ciclo.yml
git commit -m "El portal se publica solo en cada ciclo"
git push
```

Esperado: **diez** pasos, con *Publicar el portal* entre *Generar* y *Guardar*.

- [ ] **Paso 5: Lanzarlo y mirarlo desde el móvil**

*Actions* → *Ciclo horario* → *Run workflow*. Cuando termine:

1. En `ofertas-web` hay un commit nuevo con `index.html` y `datos.json`.
2. La página está en **https://aerodriguezc1984.github.io/ofertas-web/** — Pages tarda un par de
   minutos la primera vez.
3. **Ábrela desde el móvil, con los datos del teléfono y no por wifi.** Ese es el criterio de éxito
   de la etapa entera: verla desde fuera de casa.
4. Busca, filtra y ordena. Comprueba una tarjeta con su antes/después.
5. Déjala abierta media hora y comprueba que la «última sincronización» se actualiza sola.

- [ ] **Paso 6: Actualizar el README**

Añade una sección con la dirección del portal, que el ciclo corre cada hora en Actions, que Paris
está desactivado en la nube y por qué, y que **la base de la nube es la que manda**: la local pasa a
ser copia de trabajo.

```bash
git add README.md
git commit -m "README: dónde vive el rastreador ahora"
git push
```

---

## Resumen de recuentos

| Tras la tarea | Pruebas |
|---|---|
| (partida) | 205 |
| 1 — el volcado | 210 |
| 2 — los datos | 217 |
| 3 — la página | 220 |
| 4 — el ciclo en la nube | 220 (manual) |
| 5 — el portal publicado | 220 (manual) |
