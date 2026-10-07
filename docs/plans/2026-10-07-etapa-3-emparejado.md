# Etapa 3 — Emparejado entre tiendas: plan de implementación

> **Para agentes ejecutores:** SUB-SKILL OBLIGATORIA: usa
> `superpowers:subagent-driven-development` (recomendada) o
> `superpowers:executing-plans` para ejecutar este plan tarea a tarea. Los pasos
> usan casillas (`- [ ]`) para el seguimiento.

**Objetivo:** avisar de que un producto que vigilamos está significativamente más barato en otra
tienda chilena, usando el identificador de producto de SoloTodo como emparejador exacto.

**Arquitectura:** un paso nuevo del ciclo, después de capturar. La decisión es pura y vive en
`nucleo`; las dos peticiones viven en la fuente SoloTodo; las consultas en `almacen`. El histórico
y el mínimo **no** cambian: siguen siendo por tienda, y un precio ajeno nunca entra en
`historico_precios`.

**Tecnologías:** Python 3.12, SQLite, `requests`, `PyYAML`, `python-dotenv`, `pytest`.

**Spec:** `docs/specs/2026-10-07-etapa-3-emparejado-design.md`

**Punto de partida:** `main` @ `c7e3177`. **142 pruebas en verde.**

## Restricciones globales

- Python 3.12. Dependencias permitidas: `requests`, `PyYAML`, `python-dotenv`, `pytest`. Nada más.
- **Todo en español**: identificadores, docstrings, comentarios y mensajes de commit.
- **El dinero es `int` de pesos chilenos.** Ningún `float` toca un precio. El único flotante es el
  porcentaje, que se compara y se imprime, nunca se guarda ni genera un precio.
- **Ninguna prueba accede a la red.** Las fuentes reciben su transporte por inyección.
- **Ningún secreto en logs ni en mensajes de error.** El token de Telegram va en la URL.
- **Las capas no se cruzan**: `nucleo` no importa `sqlite3`, `requests` ni `almacen`; `fuentes` no
  importa `sqlite3`. Lo vigila `tests/test_capas.py`, que debe seguir en verde.
- **Las pruebas existentes no se tocan.** Si una se pone roja, lo que hay que arreglar es el código.
- Cada prueba nueva se valida rompiendo a propósito lo que dice medir, y comprobando que se pone
  roja **por el motivo correcto**. Un rojo por `KeyError` o `IndexError` donde se esperaba un valor
  equivocado significa que la mutación o la prueba están mal.

## Review Focus

Cinco entradas que la spec implica y que ninguna prueba obvia ejercita. Cada una tiene su prueba
asignada a la tarea que posee el código:

1. **Nuestro precio es 0** (un producto con histórico raro). El porcentaje divide por él:
   `ZeroDivisionError` tumbaría la comparación entera. Debe devolver «sin veredicto». → **Tarea 2**
2. **Una oferta de nuestra propia tienda.** El producto *es* una entidad de SoloTodo, así que
   aparece en su propia lista. Compararse consigo mismo daría ahorro cero o, peor, un aviso de que
   Paris está más barato que Paris. → **Tarea 2**
3. **`offer_price` nulo en una entidad con `active_registry`.** Visto en la sonda: la API lo hace.
   `a_entero(None)` da `None` y construir un `OfertaAjena` con eso metería `None` donde va un
   `int`. → **Tarea 3**
4. **`ultima_comparacion` nula en todas las filas** (el primer ciclo). SQLite ordena los nulos
   **antes** que cualquier valor en `ASC`, que es lo que queremos; si alguien lo «arregla» con
   `NULLS LAST`, los productos nunca comparados no se comparan jamás. → **Tarea 4**
5. **Una tienda nuestra que SoloTodo no cubre.** No hay identificador numérico para ella, así que
   la resolución de identidad no tiene a quién preguntar. Debe registrarse y seguir, no estallar.
   → **Tarea 3**

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/nucleo/comparacion.py` | **nuevo** — los cuatro tipos y la decisión pura |
| `src/almacen/esquema.sql` | + `productos.ultima_comparacion` |
| `src/almacen/conexion.py` | + la entrada en `COLUMNAS_NUEVAS` |
| `src/almacen/operaciones.py` | + `productos_a_comparar`, `guardar_identidad`, `marcar_comparado` |
| `src/fuentes/solotodo.py` | + `identidad_de` y `ofertas_de` |
| `src/avisos/base.py` | + `redactar_mejor_precio` y el método del protocolo |
| `src/avisos/archivo.py` | + `enviar_mejor_precio` |
| `src/avisos/telegram.py` | + `enviar_mejor_precio`, con el envío extraído a un método privado |
| `runner.py` | + `ejecutar_comparacion`, llamada tras `ejecutar_ciclo` |
| `config/config.yaml` | + la sección `comparacion` |
| `herramientas/sonda_comparacion.py` | **nueva** — sonda manual contra la API real |

---

# Tarea 1: El esquema aprende `ultima_comparacion`

La rotación del tope necesita saber cuándo se comparó cada producto por última vez. Es la **segunda
migración** del proyecto; la primera dejó escrito por qué esto no lo vigila ninguna prueba.

**Archivos:**
- Modificar: `src/almacen/esquema.sql`, `src/almacen/conexion.py`
- Prueba: `tests/test_conexion.py`

**Interfaces:**
- Produce: la columna `productos.ultima_comparacion`, `TEXT` nulable, que la Tarea 4 lee y escribe.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_conexion.py


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
```

Si `import sqlite3` no está ya al principio de `tests/test_conexion.py`, añádelo.

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_conexion.py -v`
Esperado: las dos fallan con `'ultima_comparacion' not in columnas` (un `AssertionError`, no un
error de SQL).

- [ ] **Paso 3: Implementar**

En `src/almacen/esquema.sql`, dentro de `CREATE TABLE IF NOT EXISTS productos`, justo después de
`ultima_revision`:

```sql
    ultima_comparacion TEXT,
```

En `src/almacen/conexion.py`, añade la entrada a la lista existente:

```python
COLUMNAS_NUEVAS = [
    ("productos", "producto_solotodo", "INTEGER"),
    ("productos", "ultima_comparacion", "TEXT"),
]
```

`TEXT` nulable no toca ninguno de los dos límites de `ADD COLUMN` que el comentario de ese archivo
ya documenta: no es `UNIQUE` y no es `NOT NULL` sin `DEFAULT`.

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **144 pasadas** (142 + 2).

- [ ] **Paso 5: Falsar las pruebas nuevas**

Quita la línea `("productos", "ultima_comparacion", "TEXT"),` de `COLUMNAS_NUEVAS` y ejecuta
`python -m pytest tests/test_conexion.py -v`.
Esperado: **solo** `test_una_base_sin_la_columna_de_comparacion_se_migra` se pone roja con
`assert 'ultima_comparacion' in columnas`. La de la base nueva sigue verde, porque esa columna le
llega por el esquema, no por la migración. **Ese contraste es el punto**: demuestra que las dos
pruebas miden caminos distintos.

Restaura la línea y confirma que vuelven las 144.

- [ ] **Paso 6: Commit**

```bash
git add src/almacen/esquema.sql src/almacen/conexion.py tests/test_conexion.py
git commit -m "Almacén: la segunda migración, para saber cuándo se comparó cada producto"
```

---

# Tarea 2: El núcleo decide, sin red y sin SQL

**Archivos:**
- Crear: `src/nucleo/comparacion.py`
- Prueba: `tests/test_comparacion.py` (nuevo)

**Interfaces:**
- Produce: `OfertaAjena`, `ProductoVigilado`, `ReglasComparacion`, `VeredictoMejorPrecio` y
  `mejor_oferta(precio_nuestro, tienda_nuestra, ofertas, reglas)`. Los consumen la Tarea 3
  (`OfertaAjena`), la Tarea 4 (`ProductoVigilado`), la Tarea 5 (los dos veredictos) y la Tarea 6
  (todo).

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# tests/test_comparacion.py — archivo nuevo
"""La decisión de «está más barato en otra parte», sin red y sin base."""

import pytest

from nucleo.comparacion import (
    OfertaAjena,
    ReglasComparacion,
    mejor_oferta,
)

REGLAS = ReglasComparacion(caida_minima_pct=10.0, ahorro_minimo_pesos=10000)


def oferta(tienda="winpy", precio=80000, disponible=True):
    return OfertaAjena(
        tienda=tienda, precio=precio, url=f"https://{tienda}.cl/x", disponible=disponible
    )


def test_una_oferta_que_cumple_los_dos_umbrales_gana():
    veredicto = mejor_oferta(100000, "paris", [oferta(precio=80000)], REGLAS)
    assert veredicto is not None
    assert veredicto.oferta.tienda == "winpy"
    assert veredicto.ahorro == 20000
    assert round(veredicto.porcentaje) == 20


def test_sin_ofertas_no_hay_veredicto():
    assert mejor_oferta(100000, "paris", [], REGLAS) is None


def test_una_oferta_mas_cara_no_cuenta():
    assert mejor_oferta(100000, "paris", [oferta(precio=120000)], REGLAS) is None


def test_una_oferta_agotada_no_cuenta():
    """Un precio más bajo de algo que no se puede comprar es ruido."""
    assert mejor_oferta(100000, "paris", [oferta(precio=50000, disponible=False)], REGLAS) is None


def test_cumplir_el_porcentaje_sin_el_ahorro_no_basta():
    """Un 20 % de un producto barato son 800 pesos: no mueve ninguna decisión."""
    assert mejor_oferta(4000, "paris", [oferta(precio=3200)], REGLAS) is None


def test_cumplir_el_ahorro_sin_el_porcentaje_no_basta():
    """15.000 pesos sobre 900.000 es un 1,7 %: tampoco."""
    assert mejor_oferta(900000, "paris", [oferta(precio=885000)], REGLAS) is None


def test_justo_en_los_dos_umbrales_avisa():
    """Los umbrales son inclusivos: 10 % exacto y 10.000 pesos exactos."""
    veredicto = mejor_oferta(100000, "paris", [oferta(precio=90000)], REGLAS)
    assert veredicto is not None
    assert veredicto.ahorro == 10000


def test_se_queda_con_la_mas_barata_de_varias():
    ofertas = [oferta("winpy", 85000), oferta("spdigital", 70000), oferta("wei", 78000)]
    veredicto = mejor_oferta(100000, "paris", ofertas, REGLAS)
    assert veredicto.oferta.tienda == "spdigital"


def test_un_empate_se_resuelve_siempre_igual():
    """Dos tiendas al mismo precio no pueden dar un aviso distinto en cada ciclo."""
    ofertas = [oferta("winpy", 70000), oferta("spdigital", 70000)]
    primero = mejor_oferta(100000, "paris", ofertas, REGLAS)
    segundo = mejor_oferta(100000, "paris", list(reversed(ofertas)), REGLAS)
    assert primero.oferta.tienda == segundo.oferta.tienda == "spdigital"


# --- Review Focus 2: la oferta de nuestra propia tienda ---
def test_nuestra_propia_tienda_no_compite_consigo_misma():
    """El producto ES una entidad de SoloTodo, así que sale en su propia lista."""
    ofertas = [oferta("paris", 70000), oferta("winpy", 95000)]
    # La de Paris es la más barata, pero somos Paris: la única candidata real
    # es la de Winpy, que no llega a los umbrales.
    assert mejor_oferta(100000, "paris", ofertas, REGLAS) is None


# --- Review Focus 1: nuestro precio a cero ---
@pytest.mark.parametrize("precio_nuestro", [0, -1])
def test_un_precio_nuestro_no_positivo_no_compara(precio_nuestro):
    """El porcentaje divide por nuestro precio: un cero tumbaría el paso entero."""
    assert mejor_oferta(precio_nuestro, "paris", [oferta(precio=1)], REGLAS) is None


def test_una_oferta_con_precio_no_positivo_se_descarta():
    """Un 'gratis' de una tienda ajena es un dato roto, no una ganga."""
    assert mejor_oferta(100000, "paris", [oferta(precio=0)], REGLAS) is None
```

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_comparacion.py -v`
Esperado: todas fallan en la importación, con
`ModuleNotFoundError: No module named 'nucleo.comparacion'`.

- [ ] **Paso 3: Implementar**

```python
# src/nucleo/comparacion.py — archivo nuevo
"""Decide si el mismo producto está lo bastante más barato en otra tienda.

Pura: sin red, sin SQL y sin reloj. Entra nuestro precio y lo que un agregador
dice de las demás tiendas; sale un veredicto o nada. Que no sepa de dónde vienen
las ofertas es lo que la hace probable entera con listas escritas a mano.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OfertaAjena:
    """El precio del mismo artículo en una tienda que no capturamos nosotros."""

    tienda: str
    precio: int
    url: str
    disponible: bool = True


@dataclass(frozen=True)
class ProductoVigilado:
    """Una fila de `productos` con su último precio, lista para comparar."""

    id: int
    tienda: str
    sku_externo: str
    titulo: str
    url: str
    precio_internet: int
    producto_solotodo: int | None


@dataclass(frozen=True)
class ReglasComparacion:
    """Los dos umbrales. Se exigen LOS DOS, no uno.

    Cada uno tapa el agujero del otro: sin el absoluto, un mouse de 8.000 pesos
    avisa por 800; sin el relativo, un notebook de 900.000 avisa por 10.000, que
    no mueve ninguna decisión.
    """

    caida_minima_pct: float = 10.0
    ahorro_minimo_pesos: int = 10000


@dataclass(frozen=True)
class VeredictoMejorPrecio:
    oferta: OfertaAjena
    ahorro: int
    porcentaje: float


def mejor_oferta(
    precio_nuestro: int,
    tienda_nuestra: str,
    ofertas: list[OfertaAjena],
    reglas: ReglasComparacion,
) -> VeredictoMejorPrecio | None:
    """La mejor oferta ajena que supera los dos umbrales, o None."""
    if precio_nuestro <= 0:
        # El porcentaje divide por este número. Y un producto sin precio no
        # tiene con qué comparar: no es un caso de error, es un «todavía no».
        return None

    candidatas = [
        oferta
        for oferta in ofertas
        if oferta.disponible
        and oferta.precio > 0
        and oferta.precio < precio_nuestro
        # Nuestro propio producto aparece en su lista de entidades: el
        # agregador también cubre nuestra tienda. Compararse consigo mismo
        # diría que Paris está más barato que Paris.
        and oferta.tienda != tienda_nuestra
    ]
    if not candidatas:
        return None

    # El desempate por nombre no es cosmético: sin él, dos tiendas al mismo
    # precio darían un aviso distinto según el orden en que la API las listara.
    mejor = min(candidatas, key=lambda oferta: (oferta.precio, oferta.tienda))

    ahorro = precio_nuestro - mejor.precio
    porcentaje = ahorro / precio_nuestro * 100
    if ahorro < reglas.ahorro_minimo_pesos or porcentaje < reglas.caida_minima_pct:
        return None

    return VeredictoMejorPrecio(oferta=mejor, ahorro=ahorro, porcentaje=porcentaje)
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **157 pasadas** (144 + 13).

- [ ] **Paso 5: Falsar tres de las pruebas nuevas**

Una por una, restaurando entre medias:

1. **El desempate.** Cambia `key=lambda oferta: (oferta.precio, oferta.tienda)` por
   `key=lambda oferta: oferta.precio`.
   Esperado: `test_un_empate_se_resuelve_siempre_igual` roja comparando dos nombres de tienda
   distintos, no con un `TypeError`.
2. **La propia tienda.** Quita la condición `and oferta.tienda != tienda_nuestra`.
   Esperado: `test_nuestra_propia_tienda_no_compite_consigo_misma` roja porque **sí** hay
   veredicto (`assert <VeredictoMejorPrecio...> is None`).
3. **Los dos umbrales.** Cambia el `or` de la última guarda por `and`.
   Esperado: `test_cumplir_el_porcentaje_sin_el_ahorro_no_basta` **y**
   `test_cumplir_el_ahorro_sin_el_porcentaje_no_basta` rojas, las dos. Si solo se pone roja una,
   la mutación no demuestra lo que dice: vuelve a mirarla.

- [ ] **Paso 6: Commit**

```bash
git add src/nucleo/comparacion.py tests/test_comparacion.py
git commit -m "Núcleo: la decisión de «más barato en otra parte», con doble umbral"
```

---

# Tarea 3: Las dos peticiones de SoloTodo

**Archivos:**
- Modificar: `src/fuentes/solotodo.py`
- Crear: `tests/fixtures/solotodo_entidades_de_producto.json`
- Prueba: `tests/test_solotodo.py`

**Interfaces:**
- Consume: `OfertaAjena` de `nucleo.comparacion` (Tarea 2).
- Produce: `SoloTodo.identidad_de(tienda: str, sku: str) -> int | None` y
  `SoloTodo.ofertas_de(producto_solotodo: int) -> list[OfertaAjena]`. Los llama la Tarea 6.

`src/fuentes/solotodo.py` ya importa de `nucleo.normalizador`, así que importar de
`nucleo.comparacion` no cruza ninguna capa nueva. `test_capas.py` solo prohíbe `sqlite3` en
`fuentes`.

- [ ] **Paso 1: Crear la fixture**

```json
[
  {
    "id": 101,
    "store": 45,
    "sku": "AAA-1",
    "external_url": "https://www.winpy.cl/venta/memoria-8gb/",
    "active_registry": {"offer_price": "80000.00", "normal_price": "84000.00", "is_available": true}
  },
  {
    "id": 102,
    "store": 86,
    "sku": "BBB-2",
    "external_url": "https://www.spdigital.cl/memoria-8gb",
    "active_registry": {"offer_price": "70000.00", "normal_price": "70000.00", "is_available": false}
  },
  {
    "id": 103,
    "store": 45,
    "sku": "CCC-3",
    "external_url": "https://www.winpy.cl/venta/otra/",
    "active_registry": null
  },
  {
    "id": 104,
    "store": 999,
    "sku": "DDD-4",
    "external_url": "https://desconocida.cl/x",
    "active_registry": {"offer_price": "10000.00", "normal_price": "10000.00", "is_available": true}
  },
  {
    "id": 105,
    "store": 86,
    "sku": "EEE-5",
    "external_url": "https://www.spdigital.cl/sin-precio",
    "active_registry": {"offer_price": null, "normal_price": null, "is_available": true}
  }
]
```

Las cinco entidades cubren, en orden: la buena, la agotada, la que no tiene registro activo, la de
una tienda que no está en el catálogo, y la que trae el precio a nulo (**Review Focus 3**).

- [ ] **Paso 2: Escribir las pruebas que fallan**

```python
# añadir a tests/test_solotodo.py

ENTIDADES_DE_PRODUCTO = (
    FIXTURES / "solotodo_entidades_de_producto.json"
).read_text(encoding="utf-8")

CATALOGO_AMPLIO = json.dumps(
    [
        {"id": 11, "name": "Paris"},
        {"id": 45, "name": "Winpy"},
        {"id": 86, "name": "SpDigital"},
    ]
)

ENTIDAD_CON_SKU = json.dumps(
    {"count": 1, "results": [{"id": 7, "store": 11, "sku": "106450999",
                              "product": {"id": 269594}}]}
)

URL_CATALOGO = "https://api.solotodo.com/stores/"
URL_IDENTIDAD = "https://api.solotodo.com/entities/?stores=11&search=106450999"
URL_OFERTAS = "https://api.solotodo.com/products/43835/entities/"


def test_la_identidad_sale_del_sku_que_coincide():
    """La URL del mapa es exacta: si la fuente pidiera otra, el ayudante
    lanzaría `TiendaBloqueada` y esto daría None. O sea que esta prueba fija
    también la forma de la consulta, sin una aserción aparte."""
    traer, _ = transporte_de({URL_CATALOGO: CATALOGO_AMPLIO,
                              URL_IDENTIDAD: ENTIDAD_CON_SKU})
    assert SoloTodo(traer).identidad_de("paris", "106450999") == 269594


def test_un_sku_que_no_coincide_no_resuelve_identidad():
    """Un único resultado NO prueba identidad: una identidad adivinada
    contamina todas las comparaciones futuras de esa fila, no solo un ciclo."""
    url_otro = "https://api.solotodo.com/entities/?stores=11&search=otro-sku"
    traer, _ = transporte_de({URL_CATALOGO: CATALOGO_AMPLIO,
                              url_otro: ENTIDAD_CON_SKU})
    assert SoloTodo(traer).identidad_de("paris", "otro-sku") is None


# --- Review Focus 5: una tienda que el agregador no cubre ---
def test_una_tienda_fuera_del_catalogo_no_resuelve_ni_pide_nada():
    traer, pedidas = transporte_de({URL_CATALOGO: CATALOGO_AMPLIO})
    assert SoloTodo(traer).identidad_de("una-tienda-rara", "123") is None
    assert not [u for u in pedidas if "/entities/" in u]


def test_las_ofertas_salen_de_las_entidades_del_producto():
    traer, _ = transporte_de({URL_CATALOGO: CATALOGO_AMPLIO,
                              URL_OFERTAS: ENTIDADES_DE_PRODUCTO})
    ofertas = SoloTodo(traer).ofertas_de(43835)

    # Solo sobreviven las dos de tiendas conocidas con precio entero: la de
    # Winpy disponible y la de SpDigital agotada. La agotada SE DEVUELVE —
    # descartarla es decisión del núcleo, que es quien tiene las reglas.
    assert [(o.tienda, o.precio, o.disponible) for o in ofertas] == [
        ("winpy", 80000, True),
        ("spdigital", 70000, False),
    ]


def test_una_entidad_sin_precio_no_produce_oferta():
    """Review Focus 3: la API devuelve `active_registry` con `offer_price` nulo."""
    traer, _ = transporte_de({URL_CATALOGO: CATALOGO_AMPLIO,
                              URL_OFERTAS: ENTIDADES_DE_PRODUCTO})
    ofertas = SoloTodo(traer).ofertas_de(43835)
    assert all(isinstance(o.precio, int) and o.precio > 0 for o in ofertas)
    assert "sin-precio" not in " ".join(o.url for o in ofertas)


def test_sin_catalogo_no_hay_ofertas_ni_identidad():
    traer, _ = transporte_de({})   # cualquier URL lanza TiendaBloqueada
    fuente = SoloTodo(traer)
    assert fuente.ofertas_de(1) == []
    assert fuente.identidad_de("paris", "1") is None
```

> **No escribas un ayudante de transporte nuevo.** `tests/test_solotodo.py` ya tiene
> `transporte_de(mapa)`, que devuelve `(traer, pedidas)` y casa por **URL exacta**, lanzando
> `TiendaBloqueada` si se pide otra. Definir otro con el mismo nombre taparía al existente y
> rompería las pruebas que ya lo usan. Reutilízalo tal cual.

`json`, `FIXTURES`, `TiendaBloqueada` y `SoloTodo` ya están importados en ese archivo.

- [ ] **Paso 3: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_solotodo.py -v`
Esperado: `AttributeError: 'SoloTodo' object has no attribute 'identidad_de'` (y lo mismo para
`ofertas_de`).

- [ ] **Paso 4: Implementar**

Añade al principio de `src/fuentes/solotodo.py`, junto a los otros imports:

```python
from nucleo.comparacion import OfertaAjena
```

Y los dos métodos dentro de la clase `SoloTodo`, después de `obtener`:

```python
    def identidad_de(self, tienda: str, sku: str) -> int | None:
        """El id de producto que el agregador da a (tienda, sku), o None.

        No basta con que la búsqueda devuelva un único resultado: se exige que
        el `sku` de la entidad coincida con el nuestro. Un precio equivocado
        contamina un ciclo; una identidad equivocada contamina todas las
        comparaciones futuras de esa fila.
        """
        tiendas = self._catalogo()
        if tiendas is None:
            return None

        numericos = [
            identificador
            for identificador, nombre in tiendas.items()
            if identificador_de_tienda(nombre) == tienda
        ]
        if not numericos:
            # Una tienda que el agregador no cubre. No es un fallo: hay tiendas
            # nuestras que simplemente no están ahí.
            registro.warning("solotodo: no cubre la tienda %r", tienda)
            return None

        consulta = urlencode({"stores": numericos[0], "search": sku})
        url = f"{self.BASE}/entities/?{consulta}"
        try:
            datos = json.loads(self._traer(url))
        except TiendaBloqueada as error:
            registro.warning(
                "solotodo: identidad bloqueada para %s/%s (%s)", tienda, sku, error
            )
            return None

        for entidad in datos.get("results") or []:
            if str(entidad.get("sku") or "").strip() != sku:
                continue
            producto = entidad.get("product") or {}
            identificador = producto.get("id") if isinstance(producto, dict) else None
            if isinstance(identificador, int):
                return identificador

        registro.warning("solotodo: ninguna entidad de %r con el sku %r", tienda, sku)
        return None

    def ofertas_de(self, producto_solotodo: int) -> list[OfertaAjena]:
        """El precio del mismo artículo en todas las tiendas, en una petición.

        Devuelve también las agotadas: descartarlas es decisión del núcleo, que
        es quien conoce las reglas. Aquí solo se traduce.
        """
        tiendas = self._catalogo()
        if tiendas is None:
            return []

        url = f"{self.BASE}/products/{int(producto_solotodo)}/entities/"
        try:
            datos = json.loads(self._traer(url))
        except TiendaBloqueada as error:
            registro.warning(
                "solotodo: ofertas bloqueadas para el producto %s (%s)",
                producto_solotodo, error,
            )
            return []

        ofertas: list[OfertaAjena] = []
        for entidad in datos if isinstance(datos, list) else []:
            activo = entidad.get("active_registry")
            if not isinstance(activo, dict):
                continue
            precio = a_entero(activo.get("offer_price"))
            if precio is None or precio <= 0:
                continue
            nombre = tiendas.get(entidad.get("store"))
            if nombre is None:
                continue
            enlace = str(entidad.get("external_url") or "").strip()
            if not enlace:
                continue
            ofertas.append(
                OfertaAjena(
                    tienda=identificador_de_tienda(nombre),
                    precio=precio,
                    url=enlace,
                    disponible=bool(activo.get("is_available")),
                )
            )
        return ofertas
```

- [ ] **Paso 5: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **163 pasadas** (157 + 6).

- [ ] **Paso 6: Falsar dos de las pruebas nuevas**

1. **La guarda de SKU.** Quita las dos líneas
   `if str(entidad.get("sku") or "").strip() != sku: continue`.
   Esperado: `test_un_sku_que_no_coincide_no_resuelve_identidad` roja con
   `assert 269594 is None` — es decir, devolviendo el producto equivocado. **No** debe ponerse roja
   con una excepción: si lo hace, la fixture no llega a esa rama.
2. **El precio nulo.** Cambia `if precio is None or precio <= 0:` por `if False:`.
   Esperado: `test_las_ofertas_salen_de_las_entidades_del_producto` roja porque la lista trae una
   tercera tupla con `None` de precio.

Restaura y confirma las 163.

- [ ] **Paso 7: Commit**

```bash
git add src/fuentes/solotodo.py tests/test_solotodo.py tests/fixtures/solotodo_entidades_de_producto.json
git commit -m "Fuentes: SoloTodo resuelve identidades y trae el precio de todas las tiendas"
```

---

# Tarea 4: Las tres consultas del almacén

**Archivos:**
- Modificar: `src/almacen/operaciones.py`
- Prueba: `tests/test_operaciones.py`

**Interfaces:**
- Consume: `ProductoVigilado` de `nucleo.comparacion` (Tarea 2); la columna de la Tarea 1.
- Produce: `productos_a_comparar(con, desde, limite) -> list[ProductoVigilado]`,
  `guardar_identidad(con, producto_id, producto_solotodo) -> None`,
  `marcar_comparado(con, producto_id) -> None`. Los llama la Tarea 6.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_operaciones.py


def _producto_con_precio(con, tienda, sku, precio, url=None):
    """Da de alta un producto y le deja una fila de histórico.

    El ayudante `captura()` de este archivo fija la tienda en «paris» y no
    acepta cambiarla, así que la tienda y la URL se ajustan con `replace`. No
    se toca el ayudante: lo usan las pruebas que ya existen.
    """
    nueva = replace(
        captura(precio=precio, sku=sku),
        tienda=tienda,
        url=url or f"https://www.{tienda}.cl/n-{sku}.html",
    )
    producto_id = alta_o_actualiza_producto(con, nueva)
    registrar_si_cambio(con, producto_id, nueva)
    return producto_id


def test_solo_se_comparan_los_productos_revisados_en_este_ciclo(tmp_path):
    con = abrir(tmp_path / "p.db")
    viejo = _producto_con_precio(con, "paris", "V1", 100000, "https://ejemplo/viejo")
    con.execute(
        "UPDATE productos SET ultima_revision = '2000-01-01 00:00:00' WHERE id = ?",
        (viejo,),
    )
    nuevo = _producto_con_precio(con, "paris", "N1", 90000, "https://ejemplo/nuevo")

    a_comparar = productos_a_comparar(con, "2024-01-01 00:00:00", 10)

    assert [p.id for p in a_comparar] == [nuevo]
    assert a_comparar[0].precio_internet == 90000
    assert a_comparar[0].tienda == "paris"


def test_el_tope_corta_cuantos_se_comparan(tmp_path):
    con = abrir(tmp_path / "p.db")
    for i in range(5):
        _producto_con_precio(con, "paris", f"S{i}", 100000 + i, f"https://ejemplo/{i}")

    assert len(productos_a_comparar(con, "2024-01-01 00:00:00", 2)) == 2


def test_un_tope_de_cero_no_devuelve_nada(tmp_path):
    con = abrir(tmp_path / "p.db")
    _producto_con_precio(con, "paris", "S0", 100000)
    assert productos_a_comparar(con, "2024-01-01 00:00:00", 0) == []


# --- Review Focus 4: los nulos van primero ---
def test_el_que_nunca_se_comparo_tiene_preferencia(tmp_path):
    """SQLite ordena los nulos ANTES en ASC, y eso es justo lo que queremos:
    un producto nunca comparado no puede esperar detrás de uno de ayer."""
    con = abrir(tmp_path / "p.db")
    comparado = _producto_con_precio(con, "paris", "C1", 100000, "https://ejemplo/c")
    con.execute(
        "UPDATE productos SET ultima_comparacion = '2026-01-01 00:00:00' WHERE id = ?",
        (comparado,),
    )
    nunca = _producto_con_precio(con, "paris", "N2", 100000, "https://ejemplo/n")

    assert [p.id for p in productos_a_comparar(con, "2024-01-01 00:00:00", 1)] == [nunca]


def test_un_producto_sin_historico_no_se_compara(tmp_path):
    """Sin precio nuestro no hay nada contra lo que comparar."""
    con = abrir(tmp_path / "p.db")
    alta_o_actualiza_producto(con, captura(precio=1, sku="SH"))
    assert productos_a_comparar(con, "2024-01-01 00:00:00", 10) == []


def test_guardar_identidad_y_marcar_comparado(tmp_path):
    con = abrir(tmp_path / "p.db")
    producto_id = _producto_con_precio(con, "paris", "G1", 100000)

    guardar_identidad(con, producto_id, 269594)
    marcar_comparado(con, producto_id)

    fila = con.execute(
        "SELECT producto_solotodo, ultima_comparacion FROM productos WHERE id = ?",
        (producto_id,),
    ).fetchone()
    assert fila["producto_solotodo"] == 269594
    assert fila["ultima_comparacion"] is not None
```

`replace`, `abrir`, `alta_o_actualiza_producto` y `registrar_si_cambio` ya están importados en ese
archivo. Añade a la línea de `almacen.operaciones`: `productos_a_comparar`, `guardar_identidad` y
`marcar_comparado`.

> **El ayudante `captura()` de ese archivo tiene esta firma exacta:**
> `captura(precio=100000, disponible=True, sku="SKU1")`. **No acepta `tienda` ni `url`**, y fija
> `tienda="paris"`. No lo cambies —lo usan las pruebas que ya existen—: ajusta lo que necesites con
> `dataclasses.replace`, como hace `_producto_con_precio`.

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_operaciones.py -v`
Esperado: `ImportError: cannot import name 'productos_a_comparar' from 'almacen.operaciones'`.

- [ ] **Paso 3: Implementar**

Añade a los imports de `src/almacen/operaciones.py`:

```python
from nucleo.comparacion import ProductoVigilado
```

Y al final del archivo:

```python
def productos_a_comparar(
    con: sqlite3.Connection, desde: str, limite: int
) -> list[ProductoVigilado]:
    """Los productos revisados en este ciclo, el menos comparado primero.

    `desde` es la marca de tiempo con la que arrancó el ciclo: comparar un
    precio nuestro de hace días contra uno ajeno de hoy produce avisos falsos
    en las dos direcciones.

    El orden deja primero los que nunca se compararon: SQLite ordena los nulos
    antes que cualquier valor en ASC, y eso es exactamente lo que queremos. No
    lo "arregles" con NULLS LAST, o un producto nuevo no se comparará jamás.

    Puede devolver menos de `limite`: los productos sin histórico se descartan
    después del corte, porque no hay precio nuestro contra el que comparar.
    """
    if limite <= 0:
        return []

    filas = con.execute(
        """
        SELECT p.id, p.tienda, p.sku_externo, p.titulo, p.url, p.producto_solotodo,
               (SELECT h.precio_internet
                  FROM historico_precios h
                 WHERE h.producto_id = p.id
                 ORDER BY h.capturado_el DESC, h.id DESC
                 LIMIT 1) AS precio_internet
          FROM productos p
         WHERE p.ultima_revision >= ?
         ORDER BY p.ultima_comparacion ASC, p.id ASC
         LIMIT ?
        """,
        (desde, limite),
    ).fetchall()

    return [
        ProductoVigilado(
            id=fila["id"],
            tienda=fila["tienda"],
            sku_externo=fila["sku_externo"],
            titulo=fila["titulo"],
            url=fila["url"],
            precio_internet=fila["precio_internet"],
            producto_solotodo=fila["producto_solotodo"],
        )
        for fila in filas
        if fila["precio_internet"] is not None
    ]


def guardar_identidad(
    con: sqlite3.Connection, producto_id: int, producto_solotodo: int
) -> None:
    """Fija el identificador del agregador. Se resuelve una vez y no cambia."""
    con.execute(
        "UPDATE productos SET producto_solotodo = ? WHERE id = ?",
        (producto_solotodo, producto_id),
    )


def marcar_comparado(con: sqlite3.Connection, producto_id: int) -> None:
    """Anota que a este producto ya le tocó, para que el turno rote."""
    con.execute(
        "UPDATE productos SET ultima_comparacion = datetime('now') WHERE id = ?",
        (producto_id,),
    )
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **169 pasadas** (163 + 6).

- [ ] **Paso 5: Falsar dos de las pruebas nuevas**

1. **El orden de los nulos.** Cambia `ORDER BY p.ultima_comparacion ASC` por
   `ORDER BY p.ultima_comparacion DESC`.
   Esperado: `test_el_que_nunca_se_comparo_tiene_preferencia` roja comparando dos ids distintos.
2. **El filtro del ciclo.** Cambia `WHERE p.ultima_revision >= ?` por `WHERE 1 = 1` (deja el
   parámetro, o ajusta la llamada para que no sobre).
   Esperado: `test_solo_se_comparan_los_productos_revisados_en_este_ciclo` roja con **dos** ids en
   la lista en vez de uno.

Restaura y confirma las 169.

- [ ] **Paso 6: Commit**

```bash
git add src/almacen/operaciones.py tests/test_operaciones.py
git commit -m "Almacén: a quién le toca comparar, y cómo se anota que ya le tocó"
```

---

# Tarea 5: El aviso de mejor precio

Una comparación **no tiene `Captura`**: tiene una fila de la base. Por eso el protocolo
`Notificador` gana un segundo método en vez de deformar `Captura` para que quepa.

**Archivos:**
- Modificar: `src/avisos/base.py`, `src/avisos/archivo.py`, `src/avisos/telegram.py`
- Prueba: `tests/test_avisos.py`

**Interfaces:**
- Consume: `ProductoVigilado`, `VeredictoMejorPrecio`, `OfertaAjena` (Tarea 2).
- Produce: `redactar_mejor_precio(producto, veredicto) -> str` y el método
  `Notificador.enviar_mejor_precio(producto, veredicto) -> None`, implementado por los dos
  notificadores. Lo llama la Tarea 6.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_avisos.py

from nucleo.comparacion import OfertaAjena, ProductoVigilado, VeredictoMejorPrecio

PRODUCTO = ProductoVigilado(
    id=1,
    tienda="paris",
    sku_externo="106450999",
    titulo="Notebook IdeaPad Slim 3",
    url="https://www.paris.cl/notebook-106450999.html",
    precio_internet=499990,
    producto_solotodo=269594,
)

VEREDICTO = VeredictoMejorPrecio(
    oferta=OfertaAjena(
        tienda="winpy", precio=399990, url="https://www.winpy.cl/venta/notebook/"
    ),
    ahorro=100000,
    porcentaje=20.0,
)


def test_el_aviso_nombra_las_dos_tiendas_y_el_ahorro():
    texto = redactar_mejor_precio(PRODUCTO, VEREDICTO)
    assert "paris" in texto
    assert "winpy" in texto
    assert "$499.990" in texto
    assert "$399.990" in texto
    assert "$100.000" in texto


def test_el_aviso_enlaza_a_la_tienda_ajena_no_a_la_nuestra():
    """El enlace útil es el de donde está barato, no el de donde ya miramos."""
    texto = redactar_mejor_precio(PRODUCTO, VEREDICTO)
    assert VEREDICTO.oferta.url in texto
    assert PRODUCTO.url not in texto


def test_el_aviso_dice_de_donde_sale_el_precio_ajeno():
    """Nuestro precio es de hoy; el ajeno es de SoloTodo y puede ir rezagado."""
    assert "SoloTodo" in redactar_mejor_precio(PRODUCTO, VEREDICTO)


def test_el_notificador_de_archivo_escribe_el_aviso_de_mejor_precio(tmp_path):
    ruta = tmp_path / "alertas.jsonl"
    NotificadorArchivo(ruta).enviar_mejor_precio(PRODUCTO, VEREDICTO)

    linea = json.loads(ruta.read_text(encoding="utf-8").strip())
    assert linea["regla"] == "mejor_precio"
    assert linea["tienda"] == "paris"
    assert linea["tienda_ajena"] == "winpy"
    assert linea["precio"] == 399990
    assert linea["url"] == VEREDICTO.oferta.url
```

Añade `redactar_mejor_precio` a los imports de `avisos.base` que ya tenga el archivo.

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_avisos.py -v`
Esperado: `ImportError: cannot import name 'redactar_mejor_precio' from 'avisos.base'`.

- [ ] **Paso 3: Implementar el redactor y el protocolo**

En `src/avisos/base.py`, añade el import y, después de `redactar`:

```python
from nucleo.comparacion import ProductoVigilado, VeredictoMejorPrecio
```

```python
def redactar_mejor_precio(
    producto: ProductoVigilado, veredicto: VeredictoMejorPrecio
) -> str:
    """El aviso de que el mismo artículo está más barato en otra tienda.

    Dice de dónde sale cada precio: el nuestro lo capturamos hoy, el ajeno lo
    da el agregador y puede ir rezagado. Y enlaza a la tienda ajena, que es el
    enlace que sirve para algo.
    """
    return "\n".join(
        [
            "💸 Más barato en otra tienda",
            "",
            producto.titulo,
            f"En {producto.tienda}: {pesos(producto.precio_internet)}",
            f"En {veredicto.oferta.tienda}: {pesos(veredicto.oferta.precio)}",
            f"Ahorras {pesos(veredicto.ahorro)} ({veredicto.porcentaje:.0f} %)",
            "",
            "El precio de la otra tienda lo da SoloTodo y puede ir rezagado.",
            "",
            veredicto.oferta.url,
        ]
    )
```

Y amplía el protocolo:

```python
class Notificador(Protocol):
    def enviar(self, captura: Captura, veredicto: Veredicto) -> None: ...

    def enviar_mejor_precio(
        self, producto: ProductoVigilado, veredicto: VeredictoMejorPrecio
    ) -> None: ...
```

- [ ] **Paso 4: Implementar en el notificador de archivo**

En `src/avisos/archivo.py`, añade los imports que falten y el método:

```python
    def enviar_mejor_precio(
        self, producto: ProductoVigilado, veredicto: VeredictoMejorPrecio
    ) -> None:
        registro = {
            "momento": datetime.now(timezone.utc).isoformat(),
            "tienda": producto.tienda,
            "tienda_ajena": veredicto.oferta.tienda,
            "titulo": producto.titulo,
            "url": veredicto.oferta.url,
            "regla": "mejor_precio",
            "precio": veredicto.oferta.precio,
            "precio_nuestro": producto.precio_internet,
            "mensaje": redactar_mejor_precio(producto, veredicto),
        }
        with self.ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
```

- [ ] **Paso 5: Implementar en el notificador de Telegram**

El envío se extrae a un método privado para no duplicarlo — **sin tocar ni una línea de la
protección del token**, que es la parte más delicada del proyecto. En `src/avisos/telegram.py`,
`enviar` queda así y aparecen dos métodos más:

```python
    def enviar(self, captura: Captura, veredicto: Veredicto) -> None:
        self._publicar(redactar(captura, veredicto))

    def enviar_mejor_precio(
        self, producto: ProductoVigilado, veredicto: VeredictoMejorPrecio
    ) -> None:
        self._publicar(redactar_mejor_precio(producto, veredicto))

    def _publicar(self, texto: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        cuerpo = {
            "chat_id": self._chat_id,
            "text": texto,
            "disable_web_page_preview": False,
        }

        tipo_de_fallo = None
        try:
            respuesta = self._sesion.post(url, json=cuerpo, timeout=30)
        except Exception as error:
            tipo_de_fallo = type(error).__name__
        if tipo_de_fallo is not None:
            # El texto (y la excepción encadenada) de las excepciones de
            # requests incluye la URL, y la URL lleva el token incrustado.
            # Se relanza ya fuera del bloque except, cuando Python ya no
            # tiene una excepción "en curso" que encadenar: así el error
            # nuevo no lleva ni __cause__ ni __context__, y el original no
            # puede aparecer ni en un log ni en una traza.
            raise EnvioFallido(f"No se pudo contactar con Telegram ({tipo_de_fallo})")
        if respuesta.status_code != 200:
            # Sin la URL en el mensaje: lleva el token incrustado.
            raise EnvioFallido(f"Telegram respondió {respuesta.status_code}")
```

Añade `redactar_mejor_precio` y los dos tipos a los imports de ese archivo.

> **Cuidado:** las pruebas que fijan que el token no aparece en ningún mensaje de error siguen
> apuntando a `enviar`. Deben seguir en verde **sin tocarlas**. Si alguna se pone roja, lo que está
> mal es la extracción, no la prueba.

- [ ] **Paso 6: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **173 pasadas** (169 + 4).

- [ ] **Paso 7: Falsar una de las pruebas nuevas**

Cambia en `redactar_mejor_precio` la línea `veredicto.oferta.url` por `producto.url`.
Esperado: `test_el_aviso_enlaza_a_la_tienda_ajena_no_a_la_nuestra` roja por **las dos** aserciones
—falta la ajena y sobra la nuestra—, no por un `AttributeError`.

Restaura y confirma las 173.

- [ ] **Paso 8: Commit**

```bash
git add src/avisos tests/test_avisos.py
git commit -m "Avisos: el mensaje de «más barato en otra tienda», con su enlace y su origen"
```

---

# Tarea 6: El paso nuevo del ciclo, el cableado y la sonda

**Archivos:**
- Modificar: `runner.py`, `config/config.yaml`, `README.md`
- Crear: `herramientas/sonda_comparacion.py`
- Prueba: `tests/test_runner.py`

**Interfaces:**
- Consume: todo lo anterior.
- Produce: `ejecutar_comparacion(con, fuente, notificador, config, desde) -> int`.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_runner.py

from nucleo.comparacion import OfertaAjena

CONFIG_CON_COMPARACION = {
    **CONFIG,
    "comparacion": {
        "activa": True,
        "caida_minima_pct": 10,
        "ahorro_minimo_pesos": 10000,
        "maximo_por_ciclo": 25,
        "cooldown_dias": 5,
    },
}


class SoloTodoFalso:
    """Una fuente que responde a las dos preguntas de la comparación."""

    nombre = "solotodo"

    def __init__(self, identidad=None, ofertas=None, falla=False):
        self._identidad = identidad
        self._ofertas = ofertas or []
        self._falla = falla
        self.identidades_pedidas = []
        self.ofertas_pedidas = []

    def identidad_de(self, tienda, sku):
        self.identidades_pedidas.append((tienda, sku))
        return self._identidad

    def ofertas_de(self, producto_solotodo):
        self.ofertas_pedidas.append(producto_solotodo)
        if self._falla:
            raise RuntimeError("la API devolvió HTML")
        return self._ofertas


def _producto_listo(con, precio=100000):
    """Un producto de Paris con identidad ya resuelta y precio en el histórico."""
    unica = captura(sku="P1", tienda="paris", precio=precio)
    producto_id = alta_o_actualiza_producto(con, unica)
    registrar_si_cambio(con, producto_id, unica)
    guardar_identidad(con, producto_id, 269594)
    return producto_id


def test_la_comparacion_avisa_de_una_oferta_mejor(tmp_path):
    con = abrir(tmp_path / "p.db")
    _producto_listo(con)
    avisos = NotificadorFalso()
    fuente = SoloTodoFalso(
        ofertas=[OfertaAjena("winpy", 80000, "https://winpy.cl/x", True)]
    )

    enviadas = ejecutar_comparacion(
        con, fuente, avisos, CONFIG_CON_COMPARACION, "2024-01-01 00:00:00"
    )

    assert enviadas == 1
    assert fuente.ofertas_pedidas == [269594]


def test_la_comparacion_apagada_no_pide_nada(tmp_path):
    con = abrir(tmp_path / "p.db")
    _producto_listo(con)
    fuente = SoloTodoFalso(ofertas=[OfertaAjena("winpy", 1, "https://winpy.cl/x", True)])

    config = {**CONFIG_CON_COMPARACION, "comparacion": {"activa": False}}
    assert ejecutar_comparacion(con, fuente, NotificadorFalso(), config, "2024-01-01") == 0
    assert fuente.ofertas_pedidas == []


def test_la_identidad_se_resuelve_una_sola_vez(tmp_path):
    """Resuelta y guardada, el ciclo siguiente no vuelve a preguntarla."""
    con = abrir(tmp_path / "p.db")
    unica = captura(sku="P2", tienda="paris", precio=100000)
    producto_id = alta_o_actualiza_producto(con, unica)
    registrar_si_cambio(con, producto_id, unica)

    fuente = SoloTodoFalso(identidad=269594, ofertas=[])
    ejecutar_comparacion(con, fuente, NotificadorFalso(), CONFIG_CON_COMPARACION, "2024-01-01")
    ejecutar_comparacion(con, fuente, NotificadorFalso(), CONFIG_CON_COMPARACION, "2024-01-01")

    assert fuente.identidades_pedidas == [("paris", "P2")]
    assert con.execute(
        "SELECT producto_solotodo FROM productos WHERE id = ?", (producto_id,)
    ).fetchone()["producto_solotodo"] == 269594


def test_la_segunda_pasada_no_repite_el_aviso(tmp_path):
    """El cooldown vale igual para esta regla que para las de bajada."""
    con = abrir(tmp_path / "p.db")
    _producto_listo(con)
    fuente = SoloTodoFalso(ofertas=[OfertaAjena("winpy", 80000, "https://winpy.cl/x", True)])
    avisos = NotificadorFalso()

    primera = ejecutar_comparacion(con, fuente, avisos, CONFIG_CON_COMPARACION, "2024-01-01")
    segunda = ejecutar_comparacion(con, fuente, avisos, CONFIG_CON_COMPARACION, "2024-01-01")

    assert (primera, segunda) == (1, 0)


def test_una_fuente_que_estalla_no_tumba_el_paso(tmp_path):
    """Y el producto no se marca: lo reintenta el ciclo siguiente."""
    con = abrir(tmp_path / "p.db")
    producto_id = _producto_listo(con)
    fuente = SoloTodoFalso(falla=True)

    assert ejecutar_comparacion(
        con, fuente, NotificadorFalso(), CONFIG_CON_COMPARACION, "2024-01-01"
    ) == 0
    assert con.execute(
        "SELECT ultima_comparacion FROM productos WHERE id = ?", (producto_id,)
    ).fetchone()["ultima_comparacion"] is None
```

Tres cosas sobre los ayudantes de ese archivo, comprobadas:

- El ayudante `captura()` tiene la firma `captura(precio=89990, sku="S1", tienda="paris")` —
  **`precio`, no `precio_internet`**. Sí acepta `tienda`, al revés que el de `test_operaciones.py`.
- `NotificadorFalso` solo implementa `enviar`. **Añádele** `enviar_mejor_precio`, guardando lo
  recibido en una lista propia (`self.mejores_precios`). Eso no es tocar una prueba existente: es
  ampliar un ayudante para que cumpla el protocolo ampliado, y ninguna prueba de las que hay mira
  ese atributo.
- Los imports del archivo son hoy `from runner import cargar_lista_deseos, ejecutar_ciclo`. Añade
  `ejecutar_comparacion`, y de `almacen.operaciones`: `alta_o_actualiza_producto`,
  `registrar_si_cambio` y `guardar_identidad`.

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_runner.py -v`
Esperado: `ImportError: cannot import name 'ejecutar_comparacion' from 'runner'`.

- [ ] **Paso 3: Implementar el paso**

Añade a los imports de `runner.py`:

```python
from almacen.operaciones import (
    guardar_identidad,
    marcar_comparado,
    productos_a_comparar,
)
from nucleo.comparacion import ReglasComparacion, mejor_oferta
```

(Fúndelos con los `from almacen.operaciones import ...` que ya existan en vez de duplicar la línea.)

Y la función, después de `ejecutar_ciclo`:

```python
def ejecutar_comparacion(con, fuente, notificador, config, desde: str) -> int:
    """Compara contra el resto del retail lo capturado en este ciclo.

    Es un paso aparte a propósito: si el agregador está caído, la captura que
    acaba de guardarse sigue siendo válida. Devuelve cuántos avisos mandó.
    """
    ajustes = config.get("comparacion") or {}
    if not ajustes.get("activa", False):
        return 0

    reglas = ReglasComparacion(
        caida_minima_pct=float(ajustes.get("caida_minima_pct", 10)),
        ahorro_minimo_pesos=int(ajustes.get("ahorro_minimo_pesos", 10000)),
    )
    cooldown = int(ajustes.get("cooldown_dias", config["alertas"]["cooldown_dias"]))
    tope = int(ajustes.get("maximo_por_ciclo", 25))

    enviadas = 0
    for producto in productos_a_comparar(con, desde, tope):
        try:
            identificador = producto.producto_solotodo
            if identificador is None:
                identificador = fuente.identidad_de(producto.tienda, producto.sku_externo)
                if identificador is None:
                    # No hay identidad y no la habrá preguntando otra vez hoy.
                    # Se marca para que el turno rote.
                    marcar_comparado(con, producto.id)
                    continue
                guardar_identidad(con, producto.id, identificador)

            ofertas = fuente.ofertas_de(identificador)
            veredicto = mejor_oferta(
                producto.precio_internet, producto.tienda, ofertas, reglas
            )
            # Se marca aquí, con veredicto o sin él: la comparación se hizo.
            # Si la petición hubiera fallado, estaríamos en el `except` de
            # abajo y NO se marcaría, para reintentarlo en el ciclo siguiente.
            marcar_comparado(con, producto.id)
            if veredicto is None:
                continue

            anterior = ultima_alerta(con, producto.id, "mejor_precio")
            if not debe_notificar(anterior, veredicto.oferta.precio, cooldown):
                continue

            try:
                notificador.enviar_mejor_precio(producto, veredicto)
            except Exception as error:
                # No se registra la alerta: el próximo ciclo lo reintentará.
                registro.warning(
                    "no se pudo avisar del mejor precio de %s (%s); se reintentará",
                    producto.url, error,
                )
                continue

            registrar_alerta(con, producto.id, "mejor_precio", veredicto.oferta.precio)
            enviadas += 1
        except Exception as error:  # noqa: BLE001
            # Con traza, por el mismo motivo que en `ejecutar_ciclo`: el sujeto
            # es el producto, no la fuente, que siempre es la misma.
            registro.warning(
                "no se pudo comparar %s (tienda %s): %s",
                producto.url, producto.tienda, error, exc_info=True,
            )
            continue

    return enviadas
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **178 pasadas** (173 + 5).

- [ ] **Paso 5: Falsar dos de las pruebas nuevas**

1. **El marcado tras un fallo.** Mueve `marcar_comparado(con, producto.id)` a la primera línea del
   `try`.
   Esperado: `test_una_fuente_que_estalla_no_tumba_el_paso` roja porque `ultima_comparacion` ya no
   es `None`.
2. **La identidad perezosa.** Quita la llamada a `guardar_identidad`.
   Esperado: `test_la_identidad_se_resuelve_una_sola_vez` roja con **dos** entradas en
   `identidades_pedidas`, no con un `KeyError`.

Restaura y confirma las 178.

- [ ] **Paso 6: Cablear la configuración y el arranque**

En `config/config.yaml`, una sección nueva al final:

```yaml
comparacion:
  activa: true
  # Se exigen LOS DOS umbrales, no uno: sin el absoluto un mouse de 8.000 pesos
  # avisa por 800, y sin el relativo un notebook de 900.000 avisa por 10.000.
  caida_minima_pct: 10
  ahorro_minimo_pesos: 10000
  # Una petición por producto y por ciclo, al ritmo lento del transporte. Los
  # que llevan más tiempo sin comparar van primero, así que nadie se queda sin
  # turno aunque el tope sea bajo.
  maximo_por_ciclo: 25
  cooldown_dias: 5
```

En `main()`, **antes** de `ejecutar_ciclo` —el instante de arranque tiene que ser anterior a
cualquier `ultima_revision` que el ciclo escriba— y después de él:

```python
    con = abrir(RAIZ / "data" / "tracker.db")
    inicio = con.execute("SELECT datetime('now') AS ahora").fetchone()["ahora"]

    enviadas = ejecutar_ciclo(con, fuentes, vigilados, busquedas, notificador, config)
    registro.info("ciclo terminado: %s alertas enviadas", enviadas)

    comparadas = ejecutar_comparacion(
        con, fuentes["solotodo"], notificador, config, inicio
    )
    registro.info("comparación terminada: %s avisos de mejor precio", comparadas)
    return 0
```

- [ ] **Paso 7: Escribir la sonda**

```python
# herramientas/sonda_comparacion.py
"""Comprueba contra api.solotodo.com que el emparejado sigue funcionando.

No es una prueba automática: toca la red y depende de que el producto exista.
Se ejecuta a mano cuando algo huele mal o antes de dar por buena una entrega.

    python herramientas/sonda_comparacion.py paris 106450999
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.solotodo import SoloTodo                # noqa: E402
from fuentes.transporte import crear_transporte      # noqa: E402
from nucleo.evaluador import pesos                   # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    tienda = sys.argv[1] if len(sys.argv) > 1 else "paris"
    sku = sys.argv[2] if len(sys.argv) > 2 else "106450999"

    fuente = SoloTodo(crear_transporte())

    identificador = fuente.identidad_de(tienda, sku)
    if identificador is None:
        print(f"FALLA: no se resolvió la identidad de {tienda}/{sku}.")
        print("Puede que el sku ya no exista, o que la API haya cambiado de forma.")
        return 1
    print(f"OK: {tienda}/{sku} -> producto {identificador}\n")

    ofertas = fuente.ofertas_de(identificador)
    if not ofertas:
        print(f"FALLA: el producto {identificador} no devolvió ninguna oferta.")
        return 1

    print(f"OK: {len(ofertas)} ofertas\n")
    for oferta in sorted(ofertas, key=lambda o: o.precio):
        estado = "disponible" if oferta.disponible else "agotado"
        print(f"  [{oferta.tienda}] {pesos(oferta.precio)}  ({estado})")
        print(f"    {oferta.url[:88]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Paso 8: Ejecutar la sonda contra la red**

Ejecuta: `python herramientas/sonda_comparacion.py paris 106450999`
Esperado: `OK` con un identificador de producto y una lista de ofertas con precios enteros
plausibles.

Si falla, **no toques las pruebas ni las fixtures**: el fallo está en que la API cambió. Mira la
respuesta a mano, ajusta la fuente, y actualiza la fixture después.

- [ ] **Paso 9: Comprobar la migración sobre la base real**

Este es el criterio de éxito que **no se puede repetir**. Antes de ejecutar nada, copia la base:

```bash
cp data/tracker.db data/tracker.db.antes-de-3
python -c "import sqlite3; c=sqlite3.connect('data/tracker.db.antes-de-3'); print('antes -> productos:', c.execute('SELECT COUNT(*) FROM productos').fetchone()[0], '| historico:', c.execute('SELECT COUNT(*) FROM historico_precios').fetchone()[0])"
```

Luego abre la base real una vez y comprueba que ganó la columna sin perder nada:

```bash
python -c "import sys; sys.path.insert(0,'src'); from almacen.conexion import abrir; c=abrir('data/tracker.db'); print('columnas:', [f['name'] for f in c.execute('PRAGMA table_info(productos)')]); print('despues -> productos:', c.execute('SELECT COUNT(*) FROM productos').fetchone()[0], '| historico:', c.execute('SELECT COUNT(*) FROM historico_precios').fetchone()[0])"
```

Los dos recuentos deben coincidir, y `ultima_comparacion` debe aparecer en la lista.

- [ ] **Paso 10: Ejecutar el ciclo real, dos veces**

```bash
python runner.py
python runner.py
```

Esperado: la primera pasada resuelve identidades para productos de Paris y Falabella —hoy 24 sin
identificador— y puede mandar avisos de mejor precio; la segunda **no repite** esos avisos, por el
cooldown. Compruébalo:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/tracker.db'); print('con identificador:', c.execute('SELECT COUNT(*) FROM productos WHERE producto_solotodo IS NOT NULL').fetchone()[0]); print('comparados:', c.execute('SELECT COUNT(*) FROM productos WHERE ultima_comparacion IS NOT NULL').fetchone()[0]); print('alertas por regla:', c.execute('SELECT regla, COUNT(*) FROM registro_alertas GROUP BY regla').fetchall()); print('historico:', c.execute('SELECT COUNT(*) FROM historico_precios').fetchone()[0])"
```

**El histórico no debe haber crecido por culpa de la comparación**: una comparación nunca escribe
en `historico_precios`. Anota el recuento antes y después de la segunda pasada.

- [ ] **Paso 11: Comprobar que las tiendas de antes siguen bien**

```bash
python herramientas/sonda_paris.py notebook
python herramientas/sonda_falabella.py notebook
python herramientas/sonda_solotodo.py notebook
```

Las tres deben seguir en verde.

- [ ] **Paso 12: Actualizar el README**

En la sección de pruebas, añade la sonda nueva junto a las otras tres. Y en «Cómo está hecho»,
después del párrafo de SoloTodo:

```markdown
Con el identificador de SoloTodo guardado, un segundo paso del ciclo compara lo
capturado hoy contra el precio del mismo artículo en el resto del retail: una
petición por producto trae lo que cuesta en todas las tiendas que el agregador
cubre. Avisa solo cuando la diferencia es grande de las dos maneras a la vez
—al menos un 10 % y al menos 10.000 pesos—, porque un umbral solo deja pasar
ruido: el relativo avisa por 800 pesos de un mouse, y el absoluto por 10.000 de
un notebook de 900.000.

El histórico y el mínimo **no** cambian: siguen siendo por tienda. Un precio
ajeno nunca entra en el histórico, porque no lo capturamos nosotros y puede ir
rezagado; el aviso lo dice y enlaza a la tienda ajena para comprobarlo.
```

- [ ] **Paso 13: Commit**

```bash
git add runner.py config herramientas/sonda_comparacion.py README.md tests/test_runner.py
git commit -m "Cablea la comparación entre tiendas en el ciclo y añade su sonda"
```

---

## Resumen de recuentos

| Tras la tarea | Pruebas |
|---|---|
| (partida) | 142 |
| 1 — la columna | 144 |
| 2 — el núcleo | 157 |
| 3 — las peticiones | 163 |
| 4 — las consultas | 169 |
| 5 — el aviso | 173 |
| 6 — el paso del ciclo | 178 |
