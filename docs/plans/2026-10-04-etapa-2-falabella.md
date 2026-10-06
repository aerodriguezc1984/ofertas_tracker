# Etapa 2 — Falabella y la fuente base: plan de implementación

> **Para agentes ejecutores:** SUB-SKILL OBLIGATORIA: usa
> `superpowers:subagent-driven-development` (recomendada) o
> `superpowers:executing-plans` para ejecutar este plan tarea a tarea. Los pasos
> usan casillas (`- [ ]`) para el seguimiento.

**Objetivo:** añadir Falabella como segunda tienda, con su matriz de tres precios, extrayendo por
el camino la fuente base de la que Paris y Falabella sean casos finos.

**Arquitectura:** `FuenteJsonLd` se queda con el andamiaje que se repite —bucle de `obtener`, salto
ante tienda bloqueada, deduplicado, corte por límite— y delega tres ganchos a cada tienda. El
normalizador genérico aprende lo que las tiendas reales publican de verdad (bloques escapados,
`ItemList`, valores con entidades). Lo específico de Falabella —SKU en la URL, anclaje al
`sellerSkuId`— vive en su clase.

**Tecnologías:** Python 3.12, SQLite, `requests`, `PyYAML`, `python-dotenv`, `pytest`.

**Spec:** `docs/specs/2026-10-04-etapa-2-falabella-design.md`

**Punto de partida:** rama `etapa-2-falabella` desde `main` @ `89c3dc1`. **74 pruebas en verde.**

## Restricciones globales

- Python 3.12. Dependencias permitidas: `requests`, `PyYAML`, `python-dotenv`, `pytest`. Nada más.
- **Todo en español**: identificadores, docstrings, comentarios y mensajes de commit.
- **El dinero es `int` de pesos chilenos.** Ningún `float` toca un precio.
- **Ninguna prueba accede a la red.** Las fuentes reciben su transporte por inyección.
- **Sin evasión de anti-bot.** Cabecera honesta, sin rotación, ritmo lento.
- **Ningún secreto en logs ni mensajes de error.**
- **Las capas no se cruzan**: `nucleo` no importa `sqlite3`, `requests` ni `almacen`; `fuentes` no
  importa `sqlite3`. Lo vigila `tests/test_capas.py`, que debe seguir en verde.
- **Las pruebas existentes de Paris no se tocan.** Son la prueba de que la base no rompió nada.
- Cada prueba nueva se valida rompiendo a propósito lo que dice medir.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/fuentes/base.py` | + `Candidato`, + `Captura.precios_etiquetados` |
| `src/almacen/operaciones.py` | `registrar_si_cambio` compara también `tarjeta` |
| `src/nucleo/normalizador.py` | desescapado condicional, `ItemList`, valores con entidades, `a_entero` público |
| `src/fuentes/jsonld.py` | **nuevo** — `FuenteJsonLd`, el andamiaje común |
| `src/fuentes/paris.py` | adelgaza a sus tres ganchos |
| `src/fuentes/falabella.py` | **nuevo** — búsqueda y ficha de Falabella |
| `runner.py` | confirma las capturas inferidas antes de alertar; registra la fuente |
| `herramientas/sonda_falabella.py` | **nuevo** — sonda manual contra el sitio real |

---

### Tarea 1: Las dos ampliaciones de contrato

Dos cambios pequeños del mismo tipo: ensanchar algo que ya existe. Van juntos porque ninguno
tiene sentido entregarlo solo.

**Archivos:**
- Modificar: `src/fuentes/base.py`, `src/almacen/operaciones.py`
- Prueba: `tests/test_operaciones.py` (añadir un caso), `tests/test_base.py` (nuevo)

**Interfaces:**
- Produce:
  - `fuentes.base.Captura.precios_etiquetados: bool = True`
  - `fuentes.base.Candidato(referencia: Referencia, captura: Captura | None = None)`, dataclass congelada

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# tests/test_base.py
from fuentes.base import Candidato, Captura, Referencia


def test_una_captura_se_considera_etiquetada_por_defecto():
    """Solo las fuentes que infieren precios marcan lo contrario."""
    c = Captura(
        tienda="paris", sku_externo="S1", titulo="N",
        url="https://www.paris.cl/n-S1.html", precio_internet=1000,
    )
    assert c.precios_etiquetados is True


def test_un_candidato_puede_no_traer_captura():
    """Paris devuelve enlaces que hay que seguir; Falabella, datos ya leídos."""
    c = Candidato(referencia=Referencia(tienda="paris", url="https://www.paris.cl/n-S1.html"))
    assert c.captura is None
```

```python
# añadir al final de tests/test_operaciones.py


def test_el_historico_crece_si_cambia_la_tarjeta(tmp_path):
    """La tarjeta cambia y el precio no: el histórico debe enterarse igual."""
    con = abrir(tmp_path / "p.db")
    con_cmr = Captura(
        tienda="falabella", sku_externo="F1", titulo="Notebook",
        url="https://www.falabella.com/falabella-cl/product/1/x/1",
        precio_internet=100000, precio_tarjeta=90000, tarjeta="CMR",
    )
    pid = alta_o_actualiza_producto(con, con_cmr)
    assert registrar_si_cambio(con, pid, con_cmr) is True

    con_otra = replace(con_cmr, tarjeta="CENCOSUD")
    assert registrar_si_cambio(con, pid, con_otra) is True

    # La tercera llamada es la que da valor a las dos primeras: sin ella, esta
    # prueba pasaría también con el SELECT y la tupla desalineados, porque dos
    # tuplas de distinta longitud nunca son iguales y la función devolvería
    # `True` siempre.
    assert registrar_si_cambio(con, pid, con_otra) is False
    assert con.execute("SELECT COUNT(*) FROM historico_precios").fetchone()[0] == 2
```

Añade `from dataclasses import replace` a los imports de ese archivo de pruebas.

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_base.py tests/test_operaciones.py -v`
Esperado: `test_una_captura_se_considera_etiquetada_por_defecto` falla con `AttributeError`, y
`test_el_historico_crece_si_cambia_la_tarjeta` falla porque devuelve `False` y hay 1 fila.

- [ ] **Paso 3: Implementar**

En `src/fuentes/base.py`, añade el campo **al final** de `Captura` (los campos con valor por
defecto van después, y añadirlo al final evita romper cualquier construcción posicional):

```python
    ean: str | None = None
    # Falso solo cuando los precios se han inferido del orden en que la tienda
    # los lista, sin etiqueta que diga cuál es cuál. El orquestador confirma
    # contra la ficha antes de alertar o de escribir en el histórico.
    precios_etiquetados: bool = True
```

Y la dataclass nueva, junto a `Referencia`:

```python
@dataclass(frozen=True)
class Candidato:
    """Lo que una búsqueda encuentra: dónde mirar y lo que ya se sabe de ahí.

    Unas tiendas devuelven enlaces que hay que seguir (`captura` a None); otras
    traen los productos dentro de la propia página de resultados.
    """

    referencia: Referencia
    captura: Captura | None = None
```

En `src/almacen/operaciones.py`, dentro de `registrar_si_cambio`, añade `tarjeta_asociada` a la
consulta y `captura.tarjeta` a la tupla, **en la misma posición**:

```python
        SELECT precio_internet, precio_normal, precio_tarjeta, tarjeta_asociada, disponible
```

```python
    nuevo = (
        captura.precio_internet,
        captura.precio_normal,
        captura.precio_tarjeta,
        captura.tarjeta,
        int(captura.disponible),
    )
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **77 pasadas** (74 + 2 de `test_base.py` + 1 de `test_operaciones.py`).

- [ ] **Paso 5: Commit**

```bash
git add src/fuentes/base.py src/almacen/operaciones.py tests/test_base.py tests/test_operaciones.py
git commit -m "Contrato: capturas con precios inferidos, y la tarjeta cuenta en el histórico"
```

---

### Tarea 2: El normalizador aprende lo que las tiendas publican de verdad

Cuatro cosas que el lector genérico no sabía, todas de schema.org o de HTML, ninguna de Falabella.

**Archivos:**
- Modificar: `src/nucleo/normalizador.py`
- Prueba: `tests/test_normalizador.py`

**Interfaces:**
- Produce:
  - `nucleo.normalizador.a_entero(valor) -> int | None` (era `_a_entero`, ahora pública)
  - `nucleo.normalizador.productos_ld_json(html: str) -> list[dict]`
  - `bloques_ld_json` desescapa el bloque **solo si** el texto literal no es JSON válido
  - `a_captura` desescapa los valores de texto y descarta un `ean` que valga `"null"`

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_normalizador.py
from nucleo.normalizador import a_entero, productos_ld_json

ESCAPADO = (
    '<script type="application/ld+json">'
    "{&quot;@type&quot;:&quot;Product&quot;,&quot;name&quot;:&quot;Escapado&quot;,"
    "&quot;sku&quot;:&quot;E1&quot;,&quot;offers&quot;:{&quot;price&quot;:&quot;1000&quot;}}"
    "</script>"
)

# Bloque VÁLIDO cuyo texto contiene una entidad: desescaparlo lo rompería,
# porque `&quot;` se convertiría en una comilla real dentro de la cadena.
CON_ENTIDAD = (
    '<script type="application/ld+json">'
    '{"@type":"Product","name":"Monitor 27&quot; 4K","sku":"M1",'
    '"offers":{"price":"1000"}}'
    "</script>"
)

LISTA = (
    '<script type="application/ld+json">'
    '{"@type":"ItemList","itemListElement":['
    '{"@type":"ListItem","position":1,"item":{"@type":"Product","name":"Uno","sku":"U1"}},'
    '{"@type":"ListItem","position":2,"item":{"@type":"Product","name":"Dos","sku":"D1"}}'
    "]}</script>"
)


def test_un_bloque_escapado_con_entidades_se_recupera():
    c = a_captura(ESCAPADO, "https://t.cl/e.html", "tienda")
    assert c is not None and c.sku_externo == "E1"


def test_un_bloque_valido_con_entidades_no_se_rompe():
    """Desescapar a ciegas convertiría `&quot;` en comilla y partiría el JSON."""
    c = a_captura(CON_ENTIDAD, "https://t.cl/m.html", "tienda")
    assert c is not None
    assert c.titulo == 'Monitor 27" 4K'


def test_productos_ld_json_encuentra_los_de_un_itemlist():
    assert [p["sku"] for p in productos_ld_json(LISTA)] == ["U1", "D1"]


def test_productos_ld_json_encuentra_los_de_primer_nivel():
    assert [p["sku"] for p in productos_ld_json(CON_ENTIDAD)] == ["M1"]


def test_un_ean_que_vale_null_se_descarta():
    """Falabella publica literalmente la cadena "null" cuando no tiene gtin."""
    html = (
        '<script type="application/ld+json">'
        '{"@type":"Product","name":"X","sku":"S1","gtin13":"null",'
        '"offers":{"price":"1000"}}'
        "</script>"
    )
    c = a_captura(html, "https://t.cl/x.html", "tienda")
    assert c is not None and c.ean is None


def test_a_entero_es_publica():
    assert a_entero("229.990") == 229990
```

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_normalizador.py -v`
Esperado: FALLA con `ImportError: cannot import name 'a_entero'`.

- [ ] **Paso 3: Implementar**

Añade `import html as htmlmod` arriba. Renombra `_a_entero` a `a_entero` (y sus dos usos dentro de
`a_captura`). Luego:

```python
def bloques_ld_json(html: str) -> list[dict]:
    """Todos los objetos JSON-LD de la página. Los ilegibles se descartan."""
    objetos: list[dict] = []
    for crudo in _BLOQUE.findall(html):
        texto = crudo.strip()
        try:
            dato = json.loads(texto)
        except json.JSONDecodeError:
            # Algunas tiendas sirven el bloque escapado con entidades (&quot;).
            # Se desescapa SOLO si el texto literal no era JSON: hacerlo a
            # ciegas rompería un bloque válido cuyo contenido lleve `&quot;`
            # dentro de una cadena, que es lo que publica Falabella.
            try:
                dato = json.loads(htmlmod.unescape(texto))
            except json.JSONDecodeError:
                continue
        for item in dato if isinstance(dato, list) else [dato]:
            if isinstance(item, dict):
                objetos.append(item)
    return objetos


def productos_ld_json(html: str) -> list[dict]:
    """Los `Product` de la página: los de primer nivel y los de un `ItemList`."""
    productos: list[dict] = []
    for objeto in bloques_ld_json(html):
        if _tipo_es(objeto, "Product"):
            productos.append(objeto)
            continue
        if not _tipo_es(objeto, "ItemList"):
            continue
        for elemento in objeto.get("itemListElement") or []:
            if not isinstance(elemento, dict):
                continue
            item = elemento.get("item") if _tipo_es(elemento, "ListItem") else elemento
            if isinstance(item, dict) and _tipo_es(item, "Product"):
                productos.append(item)
    return productos


def _texto(valor) -> str:
    """Un campo de texto del JSON-LD, con sus entidades HTML resueltas.

    El bloque entero no se desescapa (rompería el JSON), pero el contenido de
    un campo sí puede traerlas: Falabella publica `Monitor 27&quot; 4K`.
    """
    return htmlmod.unescape(str(valor or "")).strip()
```

En `a_captura`, sustituye el recorrido por `productos_ld_json`, usa `_texto` para título y SKU, y
descarta el `ean` inservible:

```python
def a_captura(html: str, url: str, tienda: str) -> Captura | None:
    """La Captura de la ficha, o None si la página no da datos utilizables."""
    for objeto in productos_ld_json(html):
        ofertas = objeto.get("offers") or {}
        if isinstance(ofertas, list):
            ofertas = ofertas[0] if ofertas else {}

        precio = a_entero(ofertas.get("price"))
        if precio is None:
            continue

        sku = _texto(objeto.get("sku"))
        if not sku:
            continue

        imagen = objeto.get("image")
        if isinstance(imagen, list):
            imagen = imagen[0] if imagen else None

        disponibilidad = str(ofertas.get("availability") or "")
        disponible = "outofstock" not in disponibilidad.lower().replace("/", "")

        # Algunas tiendas publican la cadena "null" en vez de omitir el campo.
        ean = _texto(objeto.get("gtin13") or objeto.get("gtin14") or objeto.get("gtin"))
        if ean.lower() in ("", "null", "none"):
            ean = None

        return Captura(
            tienda=tienda,
            sku_externo=sku,
            titulo=_texto(objeto.get("name")),
            url=url,
            precio_internet=precio,
            precio_normal=a_entero(objeto.get("listPrice")),
            disponible=disponible,
            imagen_url=imagen if isinstance(imagen, str) else None,
            ean=ean,
        )
    return None
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **83 pasadas** (77 + 6). Las pruebas de Paris siguen intactas y en verde.

- [ ] **Paso 5: Commit**

```bash
git add src/nucleo/normalizador.py tests/test_normalizador.py
git commit -m "Normalizador: bloques escapados, ItemList, entidades en los valores y el ean que dice null"
```

---

### Tarea 3: La fuente base, y Paris encima de ella

El criterio de que esta tarea salió bien es que **las pruebas de Paris no cambian ni una línea** y
siguen pasando.

**Archivos:**
- Crear: `src/fuentes/jsonld.py`
- Modificar: `src/fuentes/paris.py`
- Prueba: `tests/test_jsonld.py` (nuevo). **No toques `tests/test_paris.py`.**

**Interfaces:**
- Consume: `Candidato`, `Captura`, `Referencia`, `Transporte`, `TiendaBloqueada`, `a_captura`.
- Produce: `fuentes.jsonld.FuenteJsonLd` con los ganchos `url_de_busqueda(termino) -> str`,
  `candidatos(html) -> list[Candidato]`, `captura_de_ficha(html, url) -> Captura | None`, y los
  métodos comunes `obtener(referencias) -> list[Captura]` y `buscar(termino, limite) -> list[Captura]`.

- [ ] **Paso 1: Escribir la prueba que falla**

```python
# tests/test_jsonld.py
"""La base hace el andamiaje; cada tienda pone tres ganchos."""

from fuentes.base import Candidato, Captura, Referencia
from fuentes.jsonld import FuenteJsonLd
from fuentes.transporte import TiendaBloqueada


def captura(sku="S1", url="https://t.cl/a.html"):
    return Captura(tienda="prueba", sku_externo=sku, titulo="X", url=url, precio_internet=1000)


class FuenteDePrueba(FuenteJsonLd):
    nombre = "prueba"
    BASE = "https://t.cl"

    def __init__(self, transporte, candidatos_fijos):
        super().__init__(transporte)
        self._fijos = candidatos_fijos

    def url_de_busqueda(self, termino):
        return f"{self.BASE}/buscar?q={termino}"

    def candidatos(self, html):
        return list(self._fijos)

    def captura_de_ficha(self, html, url):
        return captura(url=url) if html == "ficha" else None


def test_un_candidato_con_captura_no_cuesta_una_peticion_de_ficha():
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return "busqueda"

    fuente = FuenteDePrueba(traer, [
        Candidato(referencia=Referencia("prueba", "https://t.cl/a.html"), captura=captura()),
    ])
    capturas = fuente.buscar("x", limite=5)

    assert len(capturas) == 1
    assert pedidas == ["https://t.cl/buscar?q=x"]  # solo la búsqueda


def test_un_candidato_sin_captura_provoca_la_peticion_de_su_ficha():
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return "busqueda" if "buscar" in url else "ficha"

    fuente = FuenteDePrueba(traer, [
        Candidato(referencia=Referencia("prueba", "https://t.cl/a.html")),
    ])
    capturas = fuente.buscar("x", limite=5)

    assert len(capturas) == 1
    assert pedidas == ["https://t.cl/buscar?q=x", "https://t.cl/a.html"]


def test_la_base_deduplica_y_corta_por_limite():
    def traer(url):
        return "busqueda"

    repetido = Candidato(referencia=Referencia("prueba", "https://t.cl/a.html"), captura=captura())
    otro = Candidato(referencia=Referencia("prueba", "https://t.cl/b.html"), captura=captura(sku="S2", url="https://t.cl/b.html"))
    tercero = Candidato(referencia=Referencia("prueba", "https://t.cl/c.html"), captura=captura(sku="S3", url="https://t.cl/c.html"))

    capturas = FuenteDePrueba(traer, [repetido, repetido, otro, tercero]).buscar("x", limite=2)

    # Afirmar CUÁLES vuelven, no cuántos: sin deduplicado volverían dos veces
    # la misma y el recuento seguiría dando 2.
    assert [c.url for c in capturas] == ["https://t.cl/a.html", "https://t.cl/b.html"]


def test_un_limite_de_cero_no_elige_ningun_candidato():
    """El corte va antes de aceptar: `limite=0` no devuelve nada."""

    def traer(url):
        return "busqueda"

    uno = Candidato(referencia=Referencia("prueba", "https://t.cl/a.html"), captura=captura())
    assert FuenteDePrueba(traer, [uno]).buscar("x", limite=0) == []


def test_una_busqueda_bloqueada_devuelve_vacio():
    def traer(url):
        raise TiendaBloqueada("403")

    assert FuenteDePrueba(traer, []).buscar("x", limite=5) == []


def test_una_ficha_bloqueada_no_tumba_las_demas():
    def traer(url):
        if url.endswith("rota.html"):
            raise TiendaBloqueada("404")
        return "ficha"

    fuente = FuenteDePrueba(traer, [])
    capturas = fuente.obtener([
        Referencia("prueba", "https://t.cl/rota.html"),
        Referencia("prueba", "https://t.cl/buena.html"),
    ])
    assert len(capturas) == 1


def test_una_ficha_sin_datos_utilizables_se_descarta():
    fuente = FuenteDePrueba(lambda url: "vacia", [])
    assert fuente.obtener([Referencia("prueba", "https://t.cl/a.html")]) == []
```

- [ ] **Paso 2: Ejecutar y comprobar que falla**

Ejecuta: `python -m pytest tests/test_jsonld.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'fuentes.jsonld'`.

- [ ] **Paso 3: Implementar**

```python
# src/fuentes/jsonld.py
"""Andamiaje común de las fuentes que leen JSON-LD.

Lo que se repite de tienda a tienda no es el patrón de enlace sino el bucle: el
salto ante una tienda bloqueada, el descarte de lo que no da datos utilizables,
el deduplicado por URL conservando el orden y el corte por límite. Eso vive
aquí; cada tienda aporta tres ganchos.

No es una jerarquía obligatoria. `Fuente` sigue siendo el protocolo que define
una fuente, y una tienda que no encaje en este molde puede implementarlo por su
cuenta en vez de torcer la base para que quepa.
"""

import logging

from fuentes.base import Candidato, Captura, Referencia, Transporte
from fuentes.transporte import TiendaBloqueada

registro = logging.getLogger(__name__)


class FuenteJsonLd:
    nombre: str = ""
    BASE: str = ""

    def __init__(self, transporte: Transporte) -> None:
        self._traer = transporte

    # --- Los tres ganchos que cada tienda implementa ---

    def url_de_busqueda(self, termino: str) -> str:
        raise NotImplementedError

    def candidatos(self, html: str) -> list[Candidato]:
        """Los productos que anuncia una página de resultados.

        Devuelve todos los que encuentre, en orden y sin deduplicar: de eso se
        encarga `buscar`.
        """
        raise NotImplementedError

    def captura_de_ficha(self, html: str, url: str) -> Captura | None:
        raise NotImplementedError

    # --- Lo común, que ninguna tienda reescribe ---

    def obtener(self, referencias: list[Referencia]) -> list[Captura]:
        capturas: list[Captura] = []
        for referencia in referencias:
            try:
                html = self._traer(referencia.url)
            except TiendaBloqueada as error:
                registro.warning(
                    "%s: no se pudo leer %s (%s)", self.nombre, referencia.url, error
                )
                continue

            captura = self.captura_de_ficha(html, referencia.url)
            if captura is None:
                registro.warning(
                    "%s: sin datos utilizables en %s", self.nombre, referencia.url
                )
                continue
            capturas.append(captura)
        return capturas

    def buscar(self, termino: str, limite: int) -> list[Captura]:
        url = self.url_de_busqueda(termino)
        try:
            html = self._traer(url)
        except TiendaBloqueada as error:
            registro.warning(
                "%s: búsqueda bloqueada para %r (%s)", self.nombre, termino, error
            )
            return []

        vistos: list[str] = []
        elegidos: list[Candidato] = []
        for candidato in self.candidatos(html):
            # El corte va ANTES de aceptar nada: con `limite=0` no se elige
            # ninguno, igual que hacía el antiguo `vistas[:limite]`.
            if len(elegidos) >= limite:
                break
            if candidato.referencia.url in vistos:
                continue
            vistos.append(candidato.referencia.url)
            elegidos.append(candidato)

        # El corte por límite sucede ANTES de pedir ninguna ficha: es lo que
        # hace barata una búsqueda en una tienda que trae 56 productos de golpe.
        capturas: list[Captura] = []
        for candidato in elegidos:
            if candidato.captura is not None:
                capturas.append(candidato.captura)
            else:
                capturas.extend(self.obtener([candidato.referencia]))
        return capturas
```

Y `src/fuentes/paris.py` queda así, entero:

```python
"""Fuente de paris.cl: se lee raspando el HTML.

La ficha publica un bloque JSON-LD con nombre, SKU y precio, así que el trabajo
real lo hace el normalizador genérico y el andamiaje lo hace la fuente base.
Aquí solo vive lo propio de Paris: la forma de su URL de búsqueda y la de sus
enlaces a ficha.
"""

import re
from urllib.parse import urlencode

from fuentes.base import Candidato, Captura, Referencia
from fuentes.jsonld import FuenteJsonLd
from nucleo.normalizador import a_captura

# Las fichas de Paris son rutas del tipo /slug-con-guiones-SKU.html
_ENLACE_FICHA = re.compile(r'href="(/[a-z0-9][a-z0-9\-]{8,90}\.html)"', re.IGNORECASE)


class Paris(FuenteJsonLd):
    nombre = "paris"
    BASE = "https://www.paris.cl"

    def url_de_busqueda(self, termino: str) -> str:
        return f"{self.BASE}/search?{urlencode({'q': termino})}"

    def candidatos(self, html: str) -> list[Candidato]:
        """Paris anuncia enlaces, no datos: hay que seguir cada ficha."""
        return [
            Candidato(referencia=Referencia(tienda=self.nombre, url=self.BASE + ruta))
            for ruta in _ENLACE_FICHA.findall(html)
        ]

    def captura_de_ficha(self, html: str, url: str) -> Captura | None:
        return a_captura(html, url, self.nombre)
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **90 pasadas** (83 + 7). **Las 6 de `tests/test_paris.py` siguen pasando sin haberlas
tocado** — ese es el criterio de esta tarea. Si alguna falla, la base cambió un comportamiento que
debía conservar: arréglala en la base, no en la prueba.

- [ ] **Paso 5: Commit**

```bash
git add src/fuentes/jsonld.py src/fuentes/paris.py tests/test_jsonld.py
git commit -m "Fuentes: extrae la base de JSON-LD y deja Paris en sus tres ganchos"
```

---

### Tarea 4: Falabella — la búsqueda

**Archivos:**
- Crear: `src/fuentes/falabella.py`, `tests/fixtures/falabella_busqueda.html`
- Prueba: `tests/test_falabella.py` (nuevo)

La *fixture* reproduce lo verificado el 2026-10-04: un único bloque JSON-LD **escapado con
entidades**, con un `ItemList` cuyos productos **no traen `sku`** y llevan dos o tres ofertas
**sin etiquetar**.

**Interfaces:**
- Consume: `FuenteJsonLd`, `Candidato`, `Captura`, `Referencia`, `productos_ld_json`, `a_entero`.
- Produce: `fuentes.falabella.Falabella(transporte)` con `nombre = "falabella"`.

- [ ] **Paso 1: Escribir la fixture y la prueba que falla**

```html
<!-- tests/fixtures/falabella_busqueda.html -->
<html><body>
<script type="application/ld+json">
{&quot;@context&quot;:&quot;https://schema.org&quot;,&quot;@type&quot;:&quot;ItemList&quot;,&quot;itemListElement&quot;:[{&quot;@type&quot;:&quot;ListItem&quot;,&quot;position&quot;:1,&quot;item&quot;:{&quot;@type&quot;:&quot;Product&quot;,&quot;name&quot;:&quot;Notebook con tres precios&quot;,&quot;url&quot;:&quot;https://www.falabella.com/falabella-cl/product/80676157/notebook-tres/80676157&quot;,&quot;image&quot;:&quot;https://media.falabella.com/a.jpg&quot;,&quot;offers&quot;:[{&quot;@type&quot;:&quot;Offer&quot;,&quot;price&quot;:&quot;419990&quot;},{&quot;@type&quot;:&quot;Offer&quot;,&quot;price&quot;:&quot;439990&quot;},{&quot;@type&quot;:&quot;Offer&quot;,&quot;price&quot;:&quot;549990&quot;}]}},{&quot;@type&quot;:&quot;ListItem&quot;,&quot;position&quot;:2,&quot;item&quot;:{&quot;@type&quot;:&quot;Product&quot;,&quot;name&quot;:&quot;Notebook con dos precios&quot;,&quot;url&quot;:&quot;https://www.falabella.com/falabella-cl/product/80726514/notebook-dos/80726514&quot;,&quot;offers&quot;:[{&quot;@type&quot;:&quot;Offer&quot;,&quot;price&quot;:&quot;679990&quot;},{&quot;@type&quot;:&quot;Offer&quot;,&quot;price&quot;:&quot;1069990&quot;}]}}]}
</script>
</body></html>
```

```python
# tests/test_falabella.py
from pathlib import Path

from fuentes.falabella import Falabella

FIXTURES = Path(__file__).parent / "fixtures"
BUSQUEDA = (FIXTURES / "falabella_busqueda.html").read_text(encoding="utf-8")

TRES = "https://www.falabella.com/falabella-cl/product/80676157/notebook-tres/80676157"
DOS = "https://www.falabella.com/falabella-cl/product/80726514/notebook-dos/80726514"


def test_la_url_de_busqueda_usa_el_parametro_de_falabella():
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return "<html></html>"

    Falabella(traer).buscar("notebook 16gb", limite=5)
    assert pedidas[0] == (
        "https://www.falabella.com/falabella-cl/search?Ntt=notebook+16gb"
    )


def test_la_busqueda_no_pide_ninguna_ficha():
    """El ItemList ya trae los productos: una petición, no dieciséis."""
    pedidas = []

    def traer(url):
        pedidas.append(url)
        return BUSQUEDA

    capturas = Falabella(traer).buscar("notebook", limite=10)
    assert len(capturas) == 2
    assert len(pedidas) == 1


def test_el_sku_sale_de_la_url():
    capturas = Falabella(lambda u: BUSQUEDA).buscar("notebook", limite=10)
    assert [c.sku_externo for c in capturas] == ["80676157", "80726514"]


def test_con_tres_ofertas_la_mas_barata_es_la_de_tarjeta():
    c = Falabella(lambda u: BUSQUEDA).buscar("notebook", limite=10)[0]
    assert c.precio_tarjeta == 419990
    assert c.precio_internet == 439990
    assert c.precio_normal == 549990
    assert c.tarjeta == "CMR"


def test_con_dos_ofertas_no_hay_precio_de_tarjeta():
    c = Falabella(lambda u: BUSQUEDA).buscar("notebook", limite=10)[1]
    assert c.precio_tarjeta is None
    assert c.tarjeta is None
    assert c.precio_internet == 679990
    assert c.precio_normal == 1069990


def test_los_precios_de_la_busqueda_quedan_marcados_como_inferidos():
    """Nada de lo que salga de aquí puede alertar sin confirmarse."""
    capturas = Falabella(lambda u: BUSQUEDA).buscar("notebook", limite=10)
    assert all(c.precios_etiquetados is False for c in capturas)


def test_un_producto_sin_sku_en_la_url_se_descarta():
    html = (
        '<script type="application/ld+json">'
        '{"@type":"ItemList","itemListElement":[{"@type":"ListItem","item":'
        '{"@type":"Product","name":"Sin sku","url":"https://www.falabella.com/raro",'
        '"offers":[{"price":"1000"},{"price":"2000"}]}}]}'
        "</script>"
    )
    assert Falabella(lambda u: html).buscar("x", limite=5) == []
```

- [ ] **Paso 2: Ejecutar y comprobar que falla**

Ejecuta: `python -m pytest tests/test_falabella.py -v`
Esperado: FALLA con `ModuleNotFoundError: No module named 'fuentes.falabella'`.

- [ ] **Paso 3: Implementar**

```python
# src/fuentes/falabella.py
"""Fuente de falabella.com.

Dos cosas la separan de Paris, y las dos están aquí y no en la capa genérica:
su búsqueda devuelve los productos dentro de un `ItemList` —una petición en vez
de una por resultado—, y sus precios vienen sin etiquetar, así que cuál es el de
tarjeta se infiere del orden y se confirma después contra la ficha.
"""

import re
from urllib.parse import urlencode

from fuentes.base import Candidato, Captura, Referencia
from fuentes.jsonld import FuenteJsonLd
from nucleo.normalizador import a_entero, productos_ld_json

# Las fichas son /falabella-cl/product/<id>/<slug>/<id>
_SKU_EN_URL = re.compile(r"/product/(\d+)/")


class Falabella(FuenteJsonLd):
    nombre = "falabella"
    BASE = "https://www.falabella.com/falabella-cl"
    TARJETA = "CMR"

    def url_de_busqueda(self, termino: str) -> str:
        return f"{self.BASE}/search?{urlencode({'Ntt': termino})}"

    def candidatos(self, html: str) -> list[Candidato]:
        candidatos: list[Candidato] = []
        for producto in productos_ld_json(html):
            url = str(producto.get("url") or "").strip()
            sku = self._sku_de(url)
            if not sku:
                continue
            captura = self._captura_inferida(producto, url, sku)
            if captura is None:
                continue
            candidatos.append(
                Candidato(
                    referencia=Referencia(tienda=self.nombre, url=url, sku_externo=sku),
                    captura=captura,
                )
            )
        return candidatos

    @staticmethod
    def _sku_de(url: str) -> str | None:
        encontrado = _SKU_EN_URL.search(url)
        return encontrado.group(1) if encontrado else None

    def _captura_inferida(self, producto: dict, url: str, sku: str) -> Captura | None:
        """Qué precio es cuál, deducido del orden en que vienen.

        La búsqueda lista las ofertas sin decir cuál es cuál. Ordenadas de
        menor a mayor: con tres, la más barata es la de tarjeta y la más cara
        la tachada; con dos, no hay precio de tarjeta; con una, es el único
        precio y no hay nada tachado. La captura sale marcada como NO
        etiquetada y el orquestador la confirma antes de alertar.
        """
        ofertas = producto.get("offers") or []
        if isinstance(ofertas, dict):
            ofertas = [ofertas]
        precios = sorted(
            p
            for p in (a_entero(o.get("price")) for o in ofertas if isinstance(o, dict))
            if p is not None
        )

        if len(precios) >= 3:
            tarjeta, internet, normal = precios[0], precios[1], precios[-1]
        elif len(precios) == 2:
            tarjeta, internet, normal = None, precios[0], precios[1]
        elif len(precios) == 1:
            tarjeta, internet, normal = None, precios[0], None
        else:
            return None

        titulo = str(producto.get("name") or "").strip()
        if not titulo:
            return None

        imagen = producto.get("image")
        if isinstance(imagen, list):
            imagen = imagen[0] if imagen else None

        return Captura(
            tienda=self.nombre,
            sku_externo=sku,
            titulo=titulo,
            url=url,
            precio_internet=internet,
            precio_normal=normal,
            precio_tarjeta=tarjeta,
            tarjeta=self.TARJETA if tarjeta is not None else None,
            imagen_url=imagen if isinstance(imagen, str) else None,
            precios_etiquetados=False,
        )

    def captura_de_ficha(self, html: str, url: str) -> Captura | None:
        raise NotImplementedError("llega en la Tarea 5")
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest tests/test_falabella.py -v`
Esperado: 7 pasadas. Y la suite entera: **96 pasadas** (89 + 7).

- [ ] **Paso 5: Commit**

```bash
git add src/fuentes/falabella.py tests/test_falabella.py tests/fixtures/falabella_busqueda.html
git commit -m "Fuentes: la búsqueda de Falabella, una petición y los precios inferidos del orden"
```

---

### Tarea 5: Falabella — la ficha, anclada al SKU

La tarea más delicada del plan. Una ficha de Falabella contiene **varias** listas `prices`: las de
los carruseles de promoción y la del producto. Coger la primera devuelve el precio de otro
producto, y eso no falla: miente.

**Archivos:**
- Modificar: `src/fuentes/falabella.py`
- Crear: `tests/fixtures/falabella_ficha.html`
- Prueba: `tests/test_falabella.py`

**Interfaces:**
- Produce: `Falabella.captura_de_ficha(html, url) -> Captura | None` con `precios_etiquetados=True`.

- [ ] **Paso 1: Escribir la fixture y las pruebas que fallan**

La *fixture* es el caso que importa: **un bloque de promoción primero, con otro SKU, y el real
después**. Reproduce lo verificado el 2026-10-04 — incluido el `&quot;` dentro del nombre y el
`gtin13` que vale la cadena `"null"`.

```html
<!-- tests/fixtures/falabella_ficha.html -->
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","@id":"https://www.falabella.com/falabella-cl/product/80676157/notebook-tres/80676157","sku":"80676157","name":"Notebook 15,6&quot; Full HD","description":"Notebook 15,6&quot; Full HD","url":"https://www.falabella.com/falabella-cl/product/80676157/notebook-tres/80676157","productID":"80676157","gtin13":"null","image":["https://media.falabella.com/a.jpg"],"brand":{"@type":"Brand","name":"HP"},"offers":[{"@type":"Offer","priceCurrency":"CLP","availability":"https://schema.org/InStock","price":"439990","sku":"80676157"}]}
</script>
</head><body>
<script>
window.__PROMO__ = {"prices":[{"type":"cmrPrice","price":["299.990"]},{"type":"internetPrice","price":["319.990"]},{"type":"normalPrice","price":["429.990"]}],"offerings":[{"sellerSkuId":"99999999"}]};
window.__PRODUCTO__ = {"prices":[{"type":"cmrPrice","price":["419.990"]},{"type":"internetPrice","price":["439.990"]},{"type":"normalPrice","price":["549.990"]}],"offerings":[{"sellerId":"FALABELLA_CHILE","offeringId":"80676157","sellerSkuId":"80676157"}]};
</script>
</body></html>
```

```python
# añadir a tests/test_falabella.py
FICHA = (FIXTURES / "falabella_ficha.html").read_text(encoding="utf-8")


def test_la_ficha_ancla_los_precios_al_sku_correcto():
    """La fixture trae antes un bloque de promoción de OTRO producto.

    Si el anclaje falla, salen 299.990 / 319.990 / 429.990, que son de un
    producto distinto. Es el fallo que no rompe nada: solo miente.
    """
    c = Falabella(lambda u: FICHA).obtener([Referencia("falabella", TRES)])[0]
    assert c.precio_tarjeta == 419990
    assert c.precio_internet == 439990
    assert c.precio_normal == 549990
    assert c.tarjeta == "CMR"


def test_la_ficha_da_precios_etiquetados():
    c = Falabella(lambda u: FICHA).obtener([Referencia("falabella", TRES)])[0]
    assert c.precios_etiquetados is True


def test_la_ficha_toma_titulo_sku_y_stock_del_json_ld():
    c = Falabella(lambda u: FICHA).obtener([Referencia("falabella", TRES)])[0]
    assert c.titulo == 'Notebook 15,6" Full HD'
    assert c.sku_externo == "80676157"
    assert c.disponible is True
    assert c.ean is None          # el gtin13 vale la cadena "null"


def test_una_ficha_sin_bloque_anclado_se_descarta():
    """Mejor ninguna captura que la del producto de al lado."""
    solo_promo = FICHA.replace('"sellerSkuId":"80676157"', '"sellerSkuId":"11111111"')
    assert Falabella(lambda u: solo_promo).obtener([Referencia("falabella", TRES)]) == []
```

Añade `from fuentes.base import Referencia` a los imports del archivo de pruebas.

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_falabella.py -v`
Esperado: FALLA con `NotImplementedError: llega en la Tarea 5`.

- [ ] **Paso 3: Implementar**

Añade arriba `from dataclasses import replace`, `import html as htmlmod`, y amplía el import del
normalizador a `from nucleo.normalizador import a_captura, a_entero, productos_ld_json`.

A nivel de módulo, junto a `_SKU_EN_URL`, añade:

```python
# Dentro del JSON incrustado de la ficha, cada precio dice de qué tipo es.
_PRECIO_ETIQUETADO = re.compile(
    r'"type":"(cmrPrice|internetPrice|normalPrice)","price":\["([\d.]+)"\]'
)
```

Y dentro de la clase, sustituye el `captura_de_ficha` provisional por estos dos métodos:

```python
    def captura_de_ficha(self, html: str, url: str) -> Captura | None:
        """El JSON-LD da título, SKU y stock; el JSON incrustado, los tres precios.

        OJO con el desescapado: el bloque JSON-LD es válido tal cual y
        desescaparlo lo ROMPE (su nombre lleva `&quot;` dentro de la cadena),
        mientras que el JSON incrustado de los precios sí viene escapado. Por
        eso `a_captura` recibe el HTML crudo y el anclaje, el desescapado.
        """
        base = a_captura(html, url, self.nombre)
        if base is None:
            return None

        etiquetados = self._precios_anclados(htmlmod.unescape(html), base.sku_externo)
        if "internetPrice" not in etiquetados:
            return None

        tarjeta = etiquetados.get("cmrPrice")
        return replace(
            base,
            precio_internet=etiquetados["internetPrice"],
            precio_normal=etiquetados.get("normalPrice"),
            precio_tarjeta=tarjeta,
            tarjeta=self.TARJETA if tarjeta is not None else None,
            precios_etiquetados=True,
        )

    @staticmethod
    def _precios_anclados(texto: str, sku: str) -> dict[str, int]:
        """Los precios DEL producto, no los del carrusel de al lado.

        Una ficha trae varias listas `prices`. Buscar hacia delante desde la
        primera captura la de una promoción, que es de otro producto. Así que
        se ancla al `sellerSkuId` que toca y se retrocede hasta el `"prices":[`
        más cercano: esa es la lista del producto.
        """
        anclas = f'"sellerSkuId":"{re.escape(sku)}"'
        for encontrado in re.finditer(anclas, texto):
            inicio = texto.rfind('"prices":[', 0, encontrado.start())
            if inicio == -1:
                continue
            pares = _PRECIO_ETIQUETADO.findall(texto[inicio : encontrado.start()])
            if pares:
                return {
                    tipo: valor
                    for tipo, valor in (
                        (t, a_entero(v)) for t, v in pares
                    )
                    if valor is not None
                }
        return {}
```

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest tests/test_falabella.py -v`
Esperado: 11 pasadas. Suite entera: **100 pasadas** (96 + 4).

- [ ] **Paso 5: Demostrar que el anclaje es real**

> [!warning] Cuidado con elegir la mutación
> Cambiar solo `rfind` por `find` **no rompe nada**, y conviene saber por qué: la
> ventana se ensancha hasta abarcar el bloque de promoción Y el real, y el
> diccionario por comprensión se queda con el último valor de cada clave, que
> resulta ser el bueno. El `rfind` del código sí es necesario —acota la ventana
> al bloque correcto— pero esa mutación concreta no lo demuestra.

Sustituye `_precios_anclados` entera por la versión que encarna el defecto, «lee la
primera lista de precios de la página»:

```python
    @staticmethod
    def _precios_anclados(texto: str, sku: str) -> dict[str, int]:
        inicio = texto.find('"prices":[')
        fin = texto.find("]", inicio)
        pares = _PRECIO_ETIQUETADO.findall(texto[inicio:fin])
        return {tipo: a_entero(valor) for tipo, valor in pares}
```

y ejecuta
`python -m pytest tests/test_falabella.py::test_la_ficha_ancla_los_precios_al_sku_correcto -v`.
**Debe FALLAR** con 299990 en vez de 419990. Restaura y comprueba que vuelve a pasar. Las dos
salidas van al informe: sin ellas, esa prueba es decorativa.

- [ ] **Paso 6: Commit**

```bash
git add src/fuentes/falabella.py tests/test_falabella.py tests/fixtures/falabella_ficha.html
git commit -m "Fuentes: la ficha de Falabella, con los precios anclados a su sellerSkuId"
```

---

### Tarea 6: El orquestador confirma antes de alertar

**Archivos:**
- Modificar: `runner.py`
- Prueba: `tests/test_runner.py`

**Interfaces:**
- Consume: `Captura.precios_etiquetados`, `Fuente.obtener`.
- Produce: `_procesar` confirma contra la ficha cualquier captura con `precios_etiquetados=False`
  **antes** de escribir nada o de alertar.

- [ ] **Paso 1: Escribir las pruebas que fallan**

```python
# añadir a tests/test_runner.py


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
    `_procesar` dejando exactamente el mismo estado observable.
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
    assert avisos.enviados == []
```

Añade `import logging` y `from fuentes.base import Captura` a los imports si no están ya.

- [ ] **Paso 2: Ejecutar y comprobar que fallan**

Ejecuta: `python -m pytest tests/test_runner.py -v`
Esperado: `test_una_captura_inferida_que_no_cumple_no_escribe_nada` falla (hoy el producto se da
de alta igualmente) y `..._se_confirma_y_alerta_con_el_dato_exacto` falla (hoy alerta con 89990).

- [ ] **Paso 3: Implementar**

En `runner.py`, dentro de `_procesar`, **antes** de `alta_o_actualiza_producto`, intercala la
confirmación. El bucle queda así:

```python
    for captura in capturas:
        try:
            if not captura.precios_etiquetados:
                # Filtro barato: se evalúa el dato inferido SIN escribir nada.
                # Si no promete una oferta, se descarta sin gastar una petición.
                # Sin histórico, `evaluar` solo puede responder a reglas de
                # precio absoluto. Un producto descubierto con una regla de
                # solo descuento se descarta, y es correcto: tampoco podría
                # alertar, porque la guarda de arranque en frío lo impediría.
                if evaluar(captura, reglas, None, 0.0, dias_minimos) is None:
                    continue
                captura = _confirmada(captura, fuente)
                if captura is None:
                    continue

            producto_id = alta_o_actualiza_producto(con, captura)
            ...
```

y la función auxiliar, junto a `_procesar`:

```python
def _confirmada(captura, fuente):
    """La captura leída de la ficha, o None si no se pudo leer.

    Un precio inferido del orden en que la tienda lista sus ofertas no puede
    disparar una alerta —mandaría al usuario a pagar más de lo que decía el
    aviso— ni entrar en el histórico, donde contaminaría el mínimo que sostiene
    todas las alertas de descuento.
    """
    referencia = Referencia(
        tienda=captura.tienda, url=captura.url, sku_externo=captura.sku_externo
    )
    try:
        exactas = fuente.obtener([referencia])
    except Exception as error:  # noqa: BLE001
        registro.warning("no se pudo confirmar %s: %s", captura.url, error, exc_info=True)
        return None

    if not exactas:
        registro.warning("no se pudo confirmar %s: la ficha no dio datos", captura.url)
        return None
    return exactas[0]
```

`_procesar` necesita la fuente, así que su firma pasa a
`_procesar(con, capturas, reglas, notificador, config, fuente)` y las dos llamadas de
`ejecutar_ciclo` le pasan `fuente`.

La reevaluación con el dato exacto no hace falta a mano: la captura confirmada sigue el camino
normal y `evaluar` vuelve a decidir sobre ella más abajo, ya con el mínimo histórico real.

- [ ] **Paso 4: Ejecutar y comprobar que pasan**

Ejecuta: `python -m pytest -v`
Esperado: **104 pasadas** (100 + 4).

- [ ] **Paso 5: Commit**

```bash
git add runner.py tests/test_runner.py
git commit -m "Orquestador: un precio inferido se confirma antes de alertar o de entrar al histórico"
```

---

### Tarea 7: Cableado y sonda manual

**Archivos:**
- Modificar: `runner.py` (registrar la fuente), `config/lista_deseos.yaml`, `README.md`
- Crear: `herramientas/sonda_falabella.py`

- [ ] **Paso 1: Registrar la fuente y añadir una búsqueda**

En `runner.py`, importa `from fuentes.falabella import Falabella` y amplía el diccionario de
`main()`:

```python
    fuentes = {"paris": Paris(transporte), "falabella": Falabella(transporte)}
```

En `config/lista_deseos.yaml`, añade a `busquedas`:

```yaml
  - termino: notebook 16gb
    tienda: falabella
    reglas:
      precio_maximo: 400000
      permitir_precio_tarjeta: false
```

- [ ] **Paso 2: Escribir la sonda**

```python
# herramientas/sonda_falabella.py
"""Comprueba contra falabella.com que el raspado sigue funcionando.

No es una prueba automática: toca la red y depende de que haya productos. Se
ejecuta a mano cuando algo huele mal o antes de dar por buena una entrega.

Comprueba las dos mitades: que la búsqueda devuelve candidatos con precios
inferidos, y que la ficha de uno de ellos devuelve los tres precios ETIQUETADOS
anclados a su propio SKU — que es la parte frágil del adaptador.

    python herramientas/sonda_falabella.py "notebook"
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fuentes.base import Referencia                 # noqa: E402
from fuentes.falabella import Falabella             # noqa: E402
from fuentes.transporte import crear_transporte     # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    termino = sys.argv[1] if len(sys.argv) > 1 else "notebook"

    falabella = Falabella(crear_transporte())
    inferidas = falabella.buscar(termino, limite=3)

    if not inferidas:
        print(f"FALLA: la búsqueda de {termino!r} no devolvió nada.")
        print("Puede que Falabella haya cambiado su ItemList o esté bloqueando.")
        return 1

    print(f"OK: {len(inferidas)} candidatos para {termino!r} (precios inferidos)\n")
    for c in inferidas:
        print(f"  {c.titulo[:58]}")
        print(f"    sku={c.sku_externo}  tarjeta={c.precio_tarjeta}  "
              f"internet={c.precio_internet}  normal={c.precio_normal}")

    primera = inferidas[0]
    print(f"\nConfirmando la primera contra su ficha...")
    exactas = falabella.obtener([
        Referencia(tienda="falabella", url=primera.url, sku_externo=primera.sku_externo)
    ])
    if not exactas:
        print("FALLA: la ficha no devolvió datos utilizables.")
        print("Lo más probable: el anclaje al sellerSkuId ya no encuentra el bloque.")
        return 1

    e = exactas[0]
    print(f"OK: ficha leída, precios etiquetados={e.precios_etiquetados}")
    print(f"    tarjeta={e.precio_tarjeta}  internet={e.precio_internet}  normal={e.precio_normal}")
    if (primera.precio_tarjeta, primera.precio_internet) != (e.precio_tarjeta, e.precio_internet):
        print("\nAVISO: la inferencia del orden NO coincidió con las etiquetas de la ficha.")
        print("No es un fallo —por eso se confirma— pero conviene saberlo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Paso 3: Ejecutarla contra la red**

Ejecuta: `python herramientas/sonda_falabella.py notebook`
Esperado: `OK` en las dos mitades, con precios de seis o siete cifras y
`precios etiquetados=True` en la ficha.

Si falla, **no toques las pruebas ni las fixtures**: el fallo está en que Falabella cambió. Mira la
página a mano, ajusta el adaptador y actualiza la *fixture* después.

- [ ] **Paso 4: Ejecutar el ciclo real y comprobar que Paris sigue viva**

```bash
python herramientas/sonda_paris.py notebook
python runner.py
python runner.py
```

Esperado: la sonda de Paris sigue en verde (la fuente base no rompió la tienda que ya funcionaba);
la primera pasada da de alta productos de las dos tiendas; la segunda **no añade filas al histórico
ni manda alertas**. Compruébalo:

```bash
python -c "import sqlite3; c=sqlite3.connect('data/tracker.db'); print('productos:', c.execute('SELECT COUNT(*) FROM productos').fetchone()[0]); print('por tienda:', c.execute('SELECT tienda, COUNT(*) FROM productos GROUP BY tienda').fetchall()); print('historico:', c.execute('SELECT COUNT(*) FROM historico_precios').fetchone()[0])"
```

- [ ] **Paso 5: Actualizar el README**

En la sección de pruebas, añade la sonda nueva:

```
python herramientas/sonda_paris.py notebook
python herramientas/sonda_falabella.py notebook
```

Y en «Cómo está hecho», sustituye el párrafo de las fuentes por:

```markdown
Cada tienda es una `Fuente` que devuelve `Captura`. Las que leen JSON-LD heredan
de `FuenteJsonLd`, que hace el andamiaje común —bucle, deduplicado, corte por
límite— y les deja tres ganchos: la URL de búsqueda, cómo sacar candidatos de
una página de resultados, y cómo leer una ficha.

Una búsqueda en Falabella cuesta **una** petición: su página de resultados trae
los productos dentro. A cambio, sus precios vienen sin etiquetar y se infieren
del orden, así que antes de alertar —o de escribir en el histórico— se confirman
contra la ficha. Un precio adivinado no dispara un aviso ni contamina el mínimo
histórico.
```

- [ ] **Paso 6: Commit**

```bash
git add runner.py config/lista_deseos.yaml herramientas/sonda_falabella.py README.md
git commit -m "Cablea Falabella en el ciclo y añade su sonda manual"
```

---

## Qué queda fuera

- **Etapa 2b**: abc.cl (sin sondear) y SoloTodo (un agregador, no una tienda: tensionará la
  interfaz `Fuente` de otro modo).
- **Etapa 3**: emparejar el mismo producto entre tiendas. Nota útil que sale de esta etapa:
  Falabella publica `gtin13`, aunque en el producto sondeado valiera `"null"`. Si otros sí lo
  traen, el emparejado por código de barras deja de ser imposible — Paris no publica ninguno.
- **Etapa 4**: Excel, rotación de logs, Programador de tareas.
