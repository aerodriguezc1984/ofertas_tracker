# Etapa 4 — El rastreador se muda a la nube, y gana un portal

Fecha: 2026-10-12
Estado: aprobado el diseño en conversación; pendiente de revisión de este documento.
Etapas anteriores: esqueleto, Falabella, SoloTodo y emparejado, las cuatro terminadas y fusionadas.
Punto de partida: **205 pruebas en verde**, 599 productos de 40 tiendas chilenas.

## Lo que la sonda cambió, antes de nada

Igual que en las dos etapas anteriores, se sondeó antes de diseñar. La pregunta era si las tiendas
responden desde un servidor de GitHub, y la respuesta no era la esperada.

Medición del 2026-10-12, desde el runner `20.231.101.34`, con el control tomado el mismo día desde
una conexión doméstica chilena:

| Destino | Desde casa | Desde GitHub |
|---|---|---|
| SoloTodo (API) | sirve | **sirve** — 5 capturas |
| **Paris** (búsqueda) | sirve, 4,5 MB | **403 — BLOQUEADO** |
| Falabella (búsqueda) | sirve | **sirve** — 3 candidatos |
| Falabella (ficha) | sirve | **sirve** — precios etiquetados |

**Paris bloquea las direcciones de centro de datos y Falabella no.** Son dos tiendas parecidas con
políticas opuestas, y no había forma de saberlo sin preguntar. De haber diseñado sobre la suposición
«si funciona desde casa funcionará desde la nube», se habría descubierto con la migración a medias.

La sonda vive en `herramientas/sonda_entorno.py` y se queda: mide el **cuerpo** de la respuesta, no
solo el código, porque un bloqueo no siempre llega como un 403 —a veces es un 200 con una página
puente sin nada que analizar, y llamar a eso «no se pudo analizar» manda a depurar el sitio
equivocado.

## Alcance

### Dentro

- El ciclo corre en GitHub Actions, cada hora, sin depender de ningún equipo encendido.
- El histórico sobrevive entre ejecuciones como **volcado SQL en texto** dentro del repositorio.
- Un **portal web** estático, accesible desde cualquier sitio, con búsqueda, filtros, orden e
  historial de cada producto.
- Dos repositorios: el privado con todo, y uno público con solo la foto de ofertas.
- Paris se desactiva **por configuración**, no se borra.

### Fuera

- **Evadir el bloqueo de Paris.** Rotar direcciones o agentes revierte la decisión raíz del
  proyecto —*no se evade la detección de robots*—, de la que salió todo lo demás. Si algún día se
  revisa, será una decisión explícita y no un parche.
- **Escribir desde el portal.** Solo lee. Ni editar la lista de deseos, ni marcar favoritos, ni
  botones que disparen nada.
- **Autenticación.** El portal público no la lleva: lo que publica son precios de tiendas.
- **Cambiar el motor.** El histórico de variaciones, la comparación entre tiendas, el agrupado por
  artículo y los umbrales se quedan exactamente como están.

## Decisiones y su porqué

### Dos repositorios, no uno

`ofertas_tracker` (privado) guarda el código, el historial, la base y los flujos. Ya existe, con
86 commits, bajo la cuenta `aerodriguezc1984`.

`ofertas-web` (público) recibe solo `index.html` y `datos.json`, y GitHub Pages lo sirve. **Todavía
no existe**: crearlo, activarle Pages y darle al flujo privado permiso para escribir en él son
pasos de la implementación, no supuestos.

GitHub Pages es gratuito **solo en repositorios públicos**. La alternativa de hacer público el
repositorio entero expondría el historial completo y la base; la de pagar una cuenta no compensa
para esto. Publicar únicamente la foto de ofertas es lo mínimo que hace falta para que el portal
exista, y es además lo que está pensado para verse.

Coste aceptado: dos repositorios que mantener y un paso de publicación en el flujo.

### La base viaja como volcado SQL, no como archivo SQLite

Cada ejecución arranca en una máquina nueva. El histórico tiene que persistir en algún sitio, y ese
sitio es el repositorio privado.

**No se commitea el `.db`.** Git no sabe comprimir SQLite: cualquier cambio reescribe páginas
dispersas y el archivo entero cuenta como contenido nuevo. Con 24 ejecuciones diarias, el
repositorio crecería cientos de megas al año.

Un volcado `.sql` en texto cambia solo en las líneas nuevas, git lo delta bien, y tiene una
propiedad que el binario no tiene: **se puede leer y arreglar a mano** si algo se corrompe.

El flujo lo restaura al empezar y lo vuelca al terminar. Si el volcado no cambió, no hay commit —
una ejecución que no encuentra nada no ensucia el historial.

### Paris se desactiva por configuración

En `config/lista_deseos.yaml` su búsqueda queda comentada, con el porqué y la fecha. El adaptador
`src/fuentes/paris.py` **no se toca**: sigue probado, sigue funcionando desde casa, y vuelve con
descomentar dos líneas si algún día Paris deja de bloquear o si el ciclo vuelve a correr en una red
doméstica.

Son 27 productos de 599. SoloTodo sigue trayendo artículos de Paris cuando los tiene indexados; lo
que se pierde es la captura directa y, con ella, el precio de tarjeta de esa tienda.

### El portal no tiene dependencias

HTML, CSS y JavaScript escritos a mano en un solo archivo, como la web de The Division 2. Sin React,
sin Vite, sin cadena de construcción.

No es nostalgia: 599 productos son unos 300 KB de JSON, y filtrarlos en el navegador es instantáneo.
Un armazón de construcción añadiría un ecosistema de dependencias que **caduca** —y este proyecto
lleva cuatro etapas con cuatro dependencias—. Además, el flujo que lo genera no necesita instalar
nada: escribe dos archivos y los publica.

### El portal solo lee, y lee una foto

`datos.json` es una **foto** generada al final de cada ciclo, no una consulta en vivo. No hay
servidor, no hay base de datos accesible desde fuera, no hay forma de que el portal escriba nada.

Eso tiene una consecuencia que conviene decir: lo que ves tiene **como mucho una hora**, y la página
lo dice con su «última sincronización». Es información suficiente para decidir si vas a comprar algo,
que es para lo que sirve.

### El refresco de 30 minutos es barato, no urgente

El ciclo corre cada hora; refrescar cada 30 minutos no descubre nada que no esté. Se mantiene porque
cuesta una línea y garantiza que una pestaña abierta toda la tarde no muestre datos de la mañana.

### Una ejecución a la vez

Dos ciclos simultáneos escribirían la misma base y se pisarían el volcado. El flujo lleva un grupo
de concurrencia que cancela o encola: **nunca dos a la vez**.

## El riesgo que esta etapa acepta a sabiendas

Cada hora son **24 ciclos diarios**. Con Paris fuera, un ciclo son ~90 peticiones:

| Destino | Por ciclo | Por día |
|---|---|---|
| SoloTodo (18 categorías + hasta 40 comparaciones) | 58 | **1.392** |
| Falabella (búsqueda + fichas de confirmación) | ~31 | **744** |

SoloTodo es un proyecto chileno pequeño con una API abierta y gratuita; 1.392 peticiones diarias de
un solo usuario es mucho. Y Falabella es **la única tienda que todavía responde desde la nube**:
744 peticiones diarias desde una IP de centro de datos es el perfil por el que Paris ya bloquea.

Está medido además que los precios no cambian a ese ritmo: dos ciclos separados 49 minutos dieron
cero cambios.

**Mitigación:** la frecuencia es una línea del flujo (`cron`). Si aparece el primer 403 de Falabella
o SoloTodo empieza a responder lento, se baja a cada 6 horas sin tocar código. Queda escrito aquí
para que la decisión se pueda revisar con los números delante.

## Arquitectura

```
  ofertas_tracker (privado)                      ofertas-web (público)
  ┌───────────────────────────────┐              ┌─────────────────────┐
  │ src/, tests/, runner.py       │              │ index.html          │
  │ data/volcado.sql   ← la base  │  publica  →  │ datos.json          │
  │ .github/workflows/ciclo.yml   │              │   (GitHub Pages)    │
  └───────────────────────────────┘              └─────────────────────┘
          cada hora
```

| Archivo | Responsabilidad |
|---|---|
| `src/almacen/volcado.py` | **nuevo** — volcar la base a SQL y restaurarla desde él |
| `src/portal/datos.py` | **nuevo** — de la base al `datos.json` que consume la página |
| `src/portal/plantilla.html` | **nuevo** — el portal entero: marcado, estilos y guion |
| `herramientas/generar_portal.py` | **nuevo** — escribe los dos archivos en una carpeta |
| `config/lista_deseos.yaml` | Paris comentado, con su porqué |
| `.github/workflows/ciclo.yml` | **nuevo** — el ciclo horario y la publicación |
| `herramientas/sonda_entorno.py` | ya existe — se queda como diagnóstico |

Las capas no cambian: `portal` lee de `almacen` y no al revés; `nucleo` sigue sin importar `sqlite3`,
`requests` ni `almacen`.

## Flujo de una ejecución

1. **Restaurar.** Si existe `data/volcado.sql`, crear la base desde él. Si no, base vacía — el
   primer ciclo arranca en frío y es correcto.
2. **Correr el ciclo.** Exactamente `runner.py` como hoy: captura, histórico, alertas, comparación.
3. **Avisar.** Telegram, con el token y el chat desde los Secrets del repositorio.
4. **Volcar.** La base a `data/volcado.sql`. Si el archivo no cambió, no se commitea.
5. **Generar.** `datos.json` e `index.html` a partir de la base.
6. **Publicar.** Los dos archivos al repositorio público.

Los pasos 4, 5 y 6 **solo corren si el paso 2 terminó bien**. Un ciclo que falló a mitad no publica
una foto incompleta ni commitea una base a medias.

## Qué lleva `datos.json`

Por producto: tienda, título, URL, imagen, disponibilidad, precio actual con su fecha, precio
anterior con su fecha, el descuento **entre esas dos lecturas nuestras**, el mínimo histórico de la
ventana de `historico.ventana_minimo_dias` (hoy 90 días), y el identificador de artículo.

El descuento **no es el precio tachado de la tienda**. Ese «antes» es de ellos y miente la mitad de
las veces; el nuestro sale de dos lecturas que hicimos y fechamos. Es la misma invariante que rige
las alertas desde la Etapa 1, y el portal no la relaja.

El cálculo del anterior/actual se hace **en SQL con `LAG()`**, que es la forma natural de expresar
«la lectura previa de este mismo producto» y evita traerse el histórico entero al portal.

Y un bloque de cabecera: cuándo se generó, cuántos productos, cuántas tiendas.

## Qué hace el portal

- **Búsqueda** instantánea por título, sin botón.
- **Filtros**: tienda (multiselección), rango de descuento, rango de precio.
- **Orden**: mayor descuento, bajada más reciente, menor precio.
- **Cada tarjeta**: insignia con el porcentaje, y el antes/después con fechas —
  *$887.990 el 09/10 ➔ $349.990 el 11/10*.
- **Agrupa por artículo**: si el mismo producto está en tres tiendas, se muestra una vez con sus
  tres precios, igual que hace el aviso de Telegram. Los productos **sin** identificador de artículo
  —los que SoloTodo no reconoce— se muestran sueltos, cada uno el suyo: agruparlos por título sería
  adivinar, y este proyecto no empareja por parecido.
- **Refresco** cada 30 minutos, con la hora de la última sincronización visible.
- **Responsivo**: se usa desde el móvil, que es el caso real.

## Errores

- **Una fuente falla** → ya está resuelto: se registra y el ciclo sigue con las demás.
- **El ciclo falla entero** → no se vuelca, no se publica, no se commitea. La foto anterior sigue
  siendo la última buena, y GitHub avisa del fallo por correo.
- **El volcado sale vacío o corrupto** → no se commitea. Un volcado vacío donde antes había 599
  productos es un fallo, no un ciclo tranquilo.
- **La publicación falla** → el ciclo ya guardó el histórico; la foto se publicará en la siguiente.

## Pruebas

Ninguna toca la red. Contando desde las 205 actuales:

| Bloque | Qué fija |
|---|---|
| `test_volcado.py` | ida y vuelta: volcar una base con datos y restaurarla da la misma base. Un volcado de base vacía no borra el histórico anterior |
| `test_portal_datos.py` | el `datos.json`: el anterior y el actual con sus fechas, el descuento calculado, el agrupado por artículo, un producto con una sola lectura (sin «anterior») |
| `test_capas.py` | sigue en verde: `portal` no es importado por `nucleo` ni por `fuentes` |

Cada prueba nueva se valida rompiendo a propósito lo que dice medir, y comprobando que se pone roja
**por el motivo correcto**.

El portal en sí —el HTML y su guion— no lleva pruebas automáticas: se comprueba abriéndolo. Igual
que las sondas, está declarado como tal y no se disfraza de cubierto.

## Criterios de éxito

1. La suite en verde, ninguna prueba toca la red.
2. Un ciclo completo en GitHub Actions termina bien y commitea el volcado.
3. Restaurar desde el volcado sobre una máquina limpia da los mismos recuentos que la base local.
4. El portal se abre desde un móvil fuera de casa y muestra las ofertas con su antes/después.
5. Buscar, filtrar y ordenar responden al instante sobre los 599 productos.
6. Un segundo ciclo **no** manda los mismos avisos: el descanso sigue funcionando sobre la base
   restaurada.
7. Paris no aparece en los registros como error: aparece como desactivada.

## Riesgos conocidos

| Riesgo | Qué pasa | Qué lo acota |
|---|---|---|
| Falabella empieza a bloquear como Paris | se pierde la captura directa; queda SoloTodo | bajar la frecuencia es una línea; la sonda lo diagnostica |
| 1.392 peticiones diarias a SoloTodo | podrían limitarnos o bloquearnos | misma línea; y es el motivo por el que esto queda escrito |
| El volcado crece | el repositorio engorda con los años | es texto y git lo delta; revisable cuando pase de unos megas |
| Dos ejecuciones a la vez | se pisan la base | grupo de concurrencia en el flujo |
| La base local y la de la nube divergen | dos verdades | **la nube manda**; la local pasa a ser copia de trabajo |

## Siguiente paso

Etapa 5 — operación: rotación de logs y exportación a Excel, lo único que quedó pendiente de la
planificación original.
