"""
ihc.tema - Constantes visuales del simulador.

Decision de diseño ligada a la teoria: el color no puede ser el UNICO codigo
que distingue el avion automatico del manual (heuristica de Nielsen
"visibilidad del estado" y buenas practicas de accesibilidad para daltonismo).
Por eso cada avion tiene ademas una silueta y una etiqueta distintas.
"""

from __future__ import annotations

# --- Lienzo y paneles ----------------------------------------------------
FONDO = "#0b1220"
FONDO_PANEL = "#111c2e"
FONDO_ALT = "#16233a"
BORDE = "#24354f"
TEXTO = "#e8eef7"
TEXTO_TENUE = "#93a4bd"
TEXTO_TITULO = "#ffffff"

# --- Capas del mapa ------------------------------------------------------
AGUA = "#0e2a47"
COSTA = "#3d6f9e"
PAIS = "#16304d"
PAIS_HOVER = "#22507d"
ETIQUETA_PAIS = "#6f8db0"

# --- Cuadricula de meridianos y paralelos ---------------------------------
# Clara a proposito: la capa va encima de la imagen de fondo, que es brillante
# (mar de (1,104,174) y tierra de (98,147,35)), y una linea oscura se perderia
# sobre ella. La jerarquia la dan el grosor y el trazo, no el tono: la malla de
# 30 grados va continua, la de 15 con puntos suspensivos, como en cartografia.
REJILLA_MAYOR = "#e2ecf8"
REJILLA_MENOR = "#b9cee6"
REJILLA_ETIQUETA = "#f2f7ff"
# Globo de la esquina: disco casi negro para que la esfera se lea sobre el mapa
# y su malla, mas clara, se distinga de la rejilla plana que tiene debajo.
ESFERA_FONDO = "#08131f"
ESFERA_MALLA = "#5c86b4"
ESFERA_MALLA_FUERTE = "#a8c6e4"
ESFERA_BORDE = "#31506f"

# --- Vuelo automatico (naranja) y manual (azul): distinguishable en
#     escala de grises y para las formas de daltonismo mas comunes.
AUTO = "#ff9f1c"
AUTO_OSCURO = "#c26a00"
MANUAL = "#2ec4b6"
MANUAL_OSCURO = "#127a70"
RUTA_AUTO = "#ff9f1c"
RUTA_MANUAL = "#2ec4b6"
RUTA_PLANIFICADA = "#8fa6c4"
ALERTA = "#ef476f"
EXITO = "#06d6a0"

# --- Tipografia ----------------------------------------------------------
FUENTE_TITULO = ("DejaVu Sans", 13, "bold")
FUENTE_TITULO_S = ("DejaVu Sans", 10, "bold")
FUENTE_TEXTO = ("DejaVu Sans", 9)
FUENTE_MONO = ("DejaVu Sans Mono", 9)
FUENTE_MONO_S = ("DejaVu Sans Mono", 8)
FUENTE_PEQUENA = ("DejaVu Sans", 8)
FUENTE_ETIQUETA = ("DejaVu Sans", 7, "bold")

# --- Geometria de las primitivas ----------------------------------------
TAMANO_AVION = 11          # semi-envergadura en px de pantalla
TAMANO_PUNTO_AEROPUERTO = 3
RADIO_SELECCION = 9
GROSOR_RUTA = 2

# --- Tiempos (ms) --------------------------------------------------------
MS_PASO_VUELO = 24         # periodo del tick del vuelo automatico
MS_PASO_TELEMETRIA = 120   # frecuencia de refresco de los paneles
MS_REPETICION_TECLA = 40   # cadencia de movimiento con el teclado
MS_ANTICIPO_TECLA = 300    # retardo inicial al mantener una tecla

# --- Ruta por defecto del vuelo de demostracion ---------------------------
# Solo origen y destino, como el resto de la aplicacion. Antes eran ocho
# paradas (UIO-BOG-SCL-JNB-DXB-MAD-MIA-UIO) y cada una aparecia en el mapa con
# su marcador numerado, contra el requisito de mostrar unicamente los dos
# puntos elegidos. El arco Quito-Madrid sigue cruzando el Atlantico, que es lo
# que hacia falta para ver el corte de la proyeccion.
RUTA_DEMOSTRACION = ("UIO", "MAD")
ORIGEN_POR_DEFECTO = "UIO"
