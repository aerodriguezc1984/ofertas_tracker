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

No tocan la red. Para comprobar contra las tiendas de verdad:

```
python herramientas/sonda_paris.py notebook
python herramientas/sonda_falabella.py notebook
```

## Cómo está hecho

Cada tienda es una `Fuente` que devuelve `Captura`. Las que leen JSON-LD heredan
de `FuenteJsonLd`, que hace el andamiaje común —bucle, deduplicado, corte por
límite— y les deja tres ganchos: la URL de búsqueda, cómo sacar candidatos de
una página de resultados, y cómo leer una ficha.

Una búsqueda en Falabella cuesta **una** petición: su página de resultados trae
los productos dentro. A cambio, sus precios vienen sin etiquetar y se infieren
del orden, así que antes de alertar —o de escribir en el histórico— se confirman
contra la ficha. Un precio adivinado no dispara un aviso ni contamina el mínimo
histórico.

El histórico guarda **variaciones**, no pasadas: una fila solo cuando el precio o
el stock cambian.

No se evade la detección de robots. Si una tienda bloquea, queda registrada y el
ciclo sigue con las demás.

El diseño está en `docs/specs/` y el plan en `docs/plans/`.
