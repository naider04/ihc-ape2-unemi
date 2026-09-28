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
