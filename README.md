# Simulador de Posicionamiento de Aeronaves

Practica 2 de Interaccion Humano-Computador (Unidad 2: modelos para el diseno de
interfaces). Version 2.0, hgora sobre `simulador_de_posicionamiento_interactivo.py`.

La version 2.0 corrige los defectos de la muestra del docente y anade
capacidades de navegacion y medicion que permiten comparar, con datos, el
control manual contra el vuelo automatico.

## Que hace y en que se diferencia de la muestra

| Aspecto | Muestra original | Version 2.0 |
|---|---|---|
| Posicion de un aeropuerto | Estimada a ojo sobre la imagen | Coordenadas reales de OurAirports (4.568 aeropuertos) |
| Paises | Solo el contorno dibujado en la imagen | Capa vectorial real de Natural Earth 50m, 242 paises |
| Distancias | Senaladas por el estudiante | `haversine` sobre coordenadas reales, en km y millas |
| Proyeccion | Lienzo estirado a 1000x507 | Equirectangular declarada, con la relacion de aspecto preservada |
| Interaccion | Avion que "salta" al cursor | Arrastre que conserva el punto de agarre |
| Encuadre | Zoom con la rueda, a ojo | Automatico: la ruta se encuadra al planificarla |
| Busqueda | No existia | Buscador con acentos, alias en espanol y localizacion |
| Capas | 1.171 aeropuertos siempre visibles | Solo el origen y el destino de la ruta |
| Modelo de tarea | No habia modelo | Bucle de planificacion, ejecucion, verificacion (GOMS-like) |
| Evidencia | Ninguna | Telemetria por modo y comparativa de eficiencia en pantalla |
| Tamano de ventana | Alto fijo que se salia de la pantalla | Se ajusta a la pantalla del usuario |
| Pruebas | Ninguna | 90 pruebas automaticas |

## Requisitos

- Python 3.11 o superior (probado en 3.14)
- `tkinter` (viene con Python; en Linux: `sudo apt install python3-tk`)
- Dependencias de Python: `pip install -r requirements.txt`
- `ghostscript`, solo para regenerar las capturas: `sudo apt install ghostscript`

El simulador ya no dibuja ninguna imagen de fondo: la capa vectorial de
Natural Earth es el mapa. Pillow solo hace falta para
`herramientas/calibrar_mapa.py`, que compara esa imagen antigua con los paises
para auditar de donde salio la proyeccion, y se puede borrar.

## Puesta en marcha

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python simulador_de_posicionamiento_interactivo.py
```

La primera ejecucion funciona con los datos ya incluidos en `data/`. Para
descargar y normalizar los datos desde cero (hace falta internet):

```bash
.venv/bin/python herramientas/preparar_datos.py
```

## Uso

1. Busque un aeropuerto en la barra superior: por ciudad (`Quito`), por pais en
   espanol (`Japon`), por nombre (`Sydney`) o por codigo IATA (`UIO`).
2. Pulse **Ir**: el mapa se centra y acerca sobre ese aeropuerto. Los botones
   **Usar como origen/destino** rellenan el campo correspondiente.
3. Con origen y destino rellenos, pulse **Planificar vuelo**: la ruta se dibuja
   como arco de gran circulo.
4. Pulse **Iniciar vuelo automatico** y observe el avion, el rumbo y la
   distancia del panel.
5. Repita el trayecto arrastrando el avion con el raton o con `W A S D`.
6. Consulte **Comparativa de eficiencia** al terminar cada trayecto.

### El encuadre es automático

No hay zoom con la rueda. Al pulsar **Planificar vuelo**, la vista calcula sola
la escala y el desplazamiento necesarios para que **origen y destino queden
visibles a la vez**, y lo mismo ocurre al arrancar. `R` o el botón **Encuadrar
ruta** lo recalculan cuando se quiera.

El acercamiento tiene tres límites:

| Situación | Escala | Resultado |
|---|---|---|
| Ruta que cruza el Atlántico (Quito → Madrid) | 4,43x | Los dos extremos se ven separados por 374 px de mapa |
| Ruta corta (Quito → Guayaquil) | 6,00x | El tope, para no perder el contexto del continente |
| Ruta que rodea el mundo | 1,00x | El mapa entero, sin encoger la tierra por debajo de su tamaño real |

El límite de 6x importa: sin él, dos aeropuertos a 30 km de distancia separarían
sus puntos hasta ocupar la pantalla y el usuario perdería la referencia.

Para que el encuadre funcione al cruzar el Atlántico, el mundo se repite
horizontalmente. La proyección va de −30° a +330°, así que Quito (281°) y Madrid
(26°) quedan a 1.426 px de distancia en un mapa de 1.800 px. `caja_de_ruta`
desplaza la continuidad al cruzar el corte, de modo que la caja mide la
distancia real de la trayectoria.

### Cuántos aeropuertos se dibujan

Solo el **origen** y el **destino**, con su etiqueta. Al principio había un menú
**Mostrar** con cuatro opciones, pero ya no hace falta: con el encuadre
automático la vista se ajusta a los dos puntos de la ruta, y dibujar 1.171
aeropuerto solo añadía elementos al lienzo sin aportar información.

### Controles

| Entrada | Efecto |
|---|---|
| Escribir en el buscador | Filtra los resultados (retardo de 180 ms) |
| `Intro` o doble clic en un resultado | Localiza y centra ese aeropuerto |
| `W A S D` o flechas | Mueve el avion (mantener pulsado repite cada 40 ms) |
| Arrastrar el avion | Mueve el avion conservando el punto de agarre |
| `R` | Reencuadra la ruta (zoom automatico) |
| **Encuadrar ruta** | Igual que `R`, con el boton |
| `Esc` | Detiene el vuelo |

## Como esta organizado el codigo

```
simulador_de_posicionamiento_interactivo.py   punto de entrada
muestra_basica_profesor.py                    muestra original, para comparar
ihc/
  app.py            interfaz, bucle de eventos, modelo de tarea
  geo.py            haversine, rumbos, grandes circulos
  proyeccion.py     proyeccion, calibracion y encuadre automatico
  datos.py          carga de aeropuertos y paises, con modo degradado
  telemetria.py     mediciones, estadisticos y comparativa de eficiencia
  tema.py           paleta, fuentes y tiempos
herramientas/
  preparar_datos.py         descarga y normaliza los datos
  calibrar_mapa.py          audita la proyeccion contra la imagen antigua
  verificar_georreferenciado.py  comprueba que el mapa es fiel
  capturar_evidencia.py     genera las capturas del manual
tests/                      90 pruebas automaticas
data/                       datos ya procesados (funciona sin internet)
capturas/                   imagenes generadas para el documento
```

## Herramientas de verificacion

```bash
.venv/bin/python -m pytest tests/ -q                        # 90 pruebas
.venv/bin/python herramientas/verificar_georreferenciado.py # fidelidad del mapa
.venv/bin/python herramientas/calibrar_mapa.py              # audita la imagen antigua
.venv/bin/python herramientas/capturar_evidencia.py         # regenera capturas
```

`verificar_georreferenciado.py` proyecta cada aeropuerto grande con la misma
cadena que usa la aplicacion y comprueba si cae dentro del poligono de su
pais. Es la forma objetiva de demostrar que el mapa esta correctamente
colocado, algo que una captura de pantalla no puede probar.

## Decisiones tecnicas que conviene conocer

- **Sin hilos.** Toda la animacion se programa con `root.after()`, de modo que
  Tk solo se modifica desde el hilo principal.
- **Distancias geodesicas, no de pantalla.** El panel usa `haversine`; los
  pixeles se usan solo para dibujar. En proyeccion equirectangular la escala
  varia con la latitud (la herramienta muestra una desviacion media del 4,7 %),
  asi que medir en pixeles daria resultados erroneos.
- **Sin internet en tiempo de ejecucion.** Los CSV y el GeoJSON se procesan una
  vez y quedan cacheados en `data/`.
- **Modo degradado.** Si falta `data/aeropuertos.csv`, la aplicacion arranca con
  doce aeropuertos de ejemplo y lo avisa en la consola, en lugar de fallar.
- **Un solo lienzo, sin fugas.** Cada elemento creado lleva la etiqueta `todo`,
  porque `tags="paises"` *sustituye* la lista de etiquetas: sin anadirla,
  `delete("todo")` no borraba nada y el lienzo acumulaba 15.000 elementos. Con
  la correccion, un redibujo completo pasa de 154 ms a unos 30 ms.
- **Etiquetas caras.** El halo de cada etiqueta son cinco elementos del lienzo.
  Por eso el nombre de un aeropuerto solo se dibuja cuando es relevante (ruta,
  busqueda o seleccion) y el resto aparece como punto a secas.
- **La ventana se ajusta a la pantalla.** La altura del mapa se calcula al
  arrancar: pantalla menos barra, buscador, paneles y consola
  (`dimensiones_ventana` en `ihc/app.py`). Con un alto fijo la ventana pedia
  812 px y en un portatil de 1366x768 los paneles y la consola quedaban
  cortados. El ancho se limita a 1500 px para que en pantallas grandes no quede
  el mapa de lado a lado.
- **El orden de las coordenadas es la trampa del mapa.** GeoJSON escribe cada
  par como (longitud, latitud) y `Mapa.geo_a_mapa` espera (latitud,
  longitud). Al pasarlo tal cual, cada pais se dibujaba girado 90 grados: Japon y
  Australia se salian del mapa por arriba y Ecuador aparecia en el Atlantico, a
  1.400 px de sus propios aeropuertos. Solo el 2,5 % de los aeropuertos grandes
  caia dentro del pais que se dibujaba. El intercambio vive en
  `Mapa.anillo_a_mapa` y hay dos pruebas que lo vigilan.
- **Los anillos se descartan por tamano en pantalla, no en grados**
  (`LADO_MINIMO_PX`). Con la vista del mundo entero, 724 anillos son motas de 2 o
  3 px y cada uno es un objeto del lienzo que hay que crear en cada fotograma. A
  8 px se dibujan 193 y el arrastre va a 25 fotogramas por segundo; a 4 px son
  254 y baja a 21. Al acercarse aparecen Alaska, Hawai o las Canarias con su
  contorno entero, porque el filtro esta en pixeles de pantalla.
- **Los vertices se simplifican al cargar, no al dibujar.** Natural Earth 50m
  trae 99.613 vertices para 242 paises y todos se dibujan en cada fotograma.
  `simplificar_anillo` (Douglas-Peucker con pila explicita, porque hay anillos
  de mas de mil puntos) los deja en 10.361 con 0,2 grados de desviacion, que son
  6 px con el acercamiento maximo. `data/paises.json` conserva el original.
- **El resumen de datos no puede quedarse con los anillos mas grandes.** Antes
  guardaba los cuatro con mas vertices de cada pais, y en 50m Estados Unidos
  tiene 127 poligonos: Hawai se caia de los cuatro primeros. Ahora conserva
  siempre el mayor (para que un pais enano no desaparezca) y todos los que
  ocupan medio grado o mas, unos 55 km.
- **Acercar el mapa no es repetirlo.** Sin acercar, la ventana del lienzo (2.886 px en
  un monitor de 1366) es mas ancha que el mundo (1.800), y pintar una segunda
  copia del planeta solo llenaba los bordes de oceano. `Mapa.repeticiones_activas()`
  solo repite cuando hace falta, al cruzar el corte del Atlantico.
- **Medir por capa-engaña.** Si se llama a `root.update()` entre capas, cada
  medida incluye el repintado de lo que ya hay en el lienzo y todas parecen
  caras. El tiempo real es el del redibujo completo; para repartir el coste hay
  que cronometrar la *creacion* de los items sin repintar.

