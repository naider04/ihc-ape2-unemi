"""
ihc.app - Ventana principal del Simulador de Posicionamiento Interactivo.

La clase esta organizada siguiendo el enfoque basado en modelos de la asignatura:

    presentacion : _construir_interfaz, _dibujar_*, _actualizar_paneles
    dialogo      : los metodos publicos son acciones del usuario; cada una
                   valida, cambia el estado y refresca la presentacion
    dominio      : la simulacion (ruta geodesica, vuelo automatico, control
                   manual) y la telemetria asociada

Decisiones de interaccion justificadas con la teoria de la unidad 2:

  * Manipulacion directa: el avion manual se toma y suelta con el puntero
    (`tag_bind(<B1-Motion>)`) conservando el punto de agarre.
  * Restricciones: el avion no puede abandonar el area del mapa.
  * Visibilidad del estado: consola y paneles muestran siempre distancia,
    tiempo, modo activo y posicion.
  * Codigo redundante: automatico = naranja y avion macizo; manual = turquesa y
    avion delineado. La distincion no depende solo del color.
  * Consistencia y control del usuario: pausa, detencion, reinicio de la
    medicion y exportacion de resultados.
  * La simulacion usa `after()` (bucle de eventos) y NO hilos: Tk no es seguro
    entre hilos. La muestra pintaba desde un `threading.Thread`, fuente de
    errores intermitentes de Tcl.
"""

from __future__ import annotations

import json
import math
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING, Sequence

from . import cuadricula, geo, tema
from .datos import FuenteDatos, Aeropuerto, datos
from .proyeccion import Limites, Mapa, Proyeccion, TransformacionVista
from .telemetria import Cronometro, Medicion, Registro

if TYPE_CHECKING:
    # Pillow solo se necesita si hay capa de fondo, y se importa mas abajo, al
    # dibujar. Aqui solo es para el tipo de la anotacion.
    from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent

# Valores por defecto. Se sustituyen automaticamente por los que produce
# `herramientas/calibrar_mapa.py` (data/calibracion_mapa.json), que ajusta la
# proyeccion al mapa base real: equirectangular con longitud inicial -30°.
LONGITUD_IZQUIERDA = -30.0
ANCHO_LONGITUD = 360.0
LATITUD_SUPERIOR = 90.0
LATITUD_INFERIOR = -90.0
# Tamano del lienzo del mapa en pixeles de proyeccion. El mapa es vectorial,
# asi que ya no hay imagen que dimensionar: es el espacio de trabajo de
# `geo_a_mapa` y del ancho de una vuelta del mundo.
TAMANO_MAPA = (1800, 913)
PASO_TECLADO_PX = 14.0
# Lado minimo en pantalla de un anillo de pais para dibujarlo. Natural Earth 50m
# trae 724 anillos y en la vista del mundo entero la mayoria son de 2 o 3 px: no
# aportan nada y cada uno es un objeto del lienzo que hay que crear en cada
# fotograma, que es lo que mas tarda. Medido: con 4 px se dibujan 254 anillos y el
# arrastre va a 21 fotogramas por segundo; con 8 px son 193 y va a 25. Al acercarse
# aparecen Alaska, Hawai o las Canarias con su contorno entero, porque el filtro
# esta en pixeles de pantalla y no en grados.
LADO_MINIMO_PX = 8.0
MAX_LATITUD_MOVIL = 84.0
TECLAS_MOVIMIENTO = {"w", "a", "s", "d", "up", "down", "left", "right"}

# Acercamiento maximo del encuadre automatico. Sin tope, dos airports a 30 km
# se separarian hasta ocupar la pantalla y se perderia el contexto.
ESCALA_MAXIMA_AUTOMATICA = 6.0
# Tamano de ventana: se calcula contra la pantalla real, no de forma fija.
ANCHO_MINIMO_VENTANA = 960
ANCHO_MAXIMO_VENTANA = 1500
ALT_MINIMO_LIENZO = 300
ALTO_MAXIMO_LIENZO = 640
MAXIMO_RESULTADOS = 8
MS_ESPERA_BUSQUEDA = 180

# --- capa de fondo en imagen --------------------------------------------
# Imagen de fondo del mapa. Se redimensiona automaticamente a TAMANO_MAPA
# al cargar, por lo que cualquier resolucion es valida.
FONDO_MAPA = RAIZ / "imagen.png"
# Cuantos reescalados se guardan a la vez. Pillow necesita entre 15 y 150 ms
# por cada uno, segun el tamano, y eso no puede ir en cada fotograma. Solo hace
# falta al cambiar el encuadre: al arrastrar el tamano no cambia y sale de la
# cache. Dos bastan para no repetir trabajo entre reencuadrar la ruta y
# seleccionar un aeropuerto, que son los dos encuadres que se usan.
FONDOS_EN_CACHE = 2
# A partir de este acercamiento la imagen de 1800 px de ancho se veria tan
# ampliada que no compensaria: se sigue con el mar plano y las costas de vector.
MAXIMO_AMPLIACION_FONDO = 8.0  # cubre hasta el zoom maximo automatico (6x)

# Rotulos de la cuadricula: separacion minima en pantalla entre dos lineas de 30
# grados. Por debajo de 60 px el borde se llena de letras pegadas y el mapa se lee
# peor que sin rotulos, asi que las etiquetas se apagan y solo quedan las lineas.
# Se mide en pixeles de pantalla y no en grados porque el ancho del lienzo cambia
# con la ventana: los mismos 30 grados ocupan 150 px a 1x y 47 px en un lienzo
# estrecho, que es justo donde molestan.
SEPARACION_MIN_ETIQUETAS_PX = 60.0


def tamano_fondo(kx: float, ky: float) -> tuple[int, int] | None:
    """Tamano en pixeles de pantalla de una vuelta del mundo, o None si no se dibuja.

    Se separa del dibujado para poder comprobarlo sin abrir una ventana. La
    decision tiene dos partes: por debajo de un pixel no hay nada que teach y por
    encima de `MAXIMO_AMPLIACION_FONDO` la imagen se veria tan estirada que no
    compensaria el trabajo de reescalarla.

    El tamano sale exacto, nunca redondeado a una rejilla: con 4 px de error el
    fondo se estiraba hasta un 1,4 % y la costa se separaba de la linea varios
    grados en el borde opuesto de la lamina. Al arrastrar la vista el tamano no
    cambia, y por eso esto sale de la cache sin volver a trabajar.
    """
    ancho = TAMANO_MAPA[0] * kx
    if ancho <= 1.0 or ancho > TAMANO_MAPA[0] * MAXIMO_AMPLIACION_FONDO:
        return None
    return (int(round(ancho)), int(round(TAMANO_MAPA[1] * ky)))


def limites_calibrados() -> Limites:
    """Lee la calibracion generada por la herramienta; si no existe, usa la base."""
    ruta = RAIZ / "data" / "calibracion_mapa.json"
    if not ruta.exists():
        return Limites(LONGITUD_IZQUIERDA, LONGITUD_IZQUIERDA + ANCHO_LONGITUD,
                       LATITUD_SUPERIOR, LATITUD_INFERIOR)
    try:
        datos_cal = json.loads(ruta.read_text(encoding="utf-8"))
        return Limites(datos_cal["lon_izquierda"],
                       datos_cal["lon_izquierda"] + datos_cal["longitud_grados"],
                       datos_cal["latitud_superior"], datos_cal["latitud_inferior"])
    except (OSError, KeyError, ValueError):
        return Limites(LONGITUD_IZQUIERDA, LONGITUD_IZQUIERDA + ANCHO_LONGITUD,
                       LATITUD_SUPERIOR, LATITUD_INFERIOR)


def dimensiones_ventana(ancho_pantalla: int, alto_pantalla: int, espacio_fijo: int
                        ) -> tuple[int, int, int]:
    """Calcula (ancho, alto, alto del lienzo) para que quepa en la pantalla.

    Se separa de la interfaz para poder comprobarlo sin abrir una ventana.
    `espacio_fijo` es lo que ocupan la barra, el buscador, los tres paneles y la
    consola, es decir, todo menos el mapa. Los 96 px reservados cubren la barra
    de titulo y la barra de tareas, que no forman parte del area de Tk.
    """
    alto_lienzo = max(ALT_MINIMO_LIENZO,
                      min(ALTO_MAXIMO_LIENZO, alto_pantalla - 96 - espacio_fijo))
    ancho = min(ANCHO_MAXIMO_VENTANA, max(ANCHO_MINIMO_VENTANA, ancho_pantalla - 60))
    alto = min(alto_pantalla - 40, espacio_fijo + alto_lienzo)
    return ancho, alto, alto_lienzo


class SimuladorMapa:
    """Mapa, ruta, dos aviones y la medicion de su eficiencia."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.fuente: FuenteDatos = datos()
        self.registro = Registro()
        self.reloj_auto = Cronometro()
        self.reloj_manual = Cronometro()

        # --- estado de la simulacion ---------------------------------
        self.ruta: list[Aeropuerto] = []
        self.segmento = 0
        self.progreso = 0.0
        self.vuelo_en_curso = False
        self.vuelo_pausado = False
        self._id_tick: str | None = None
        self._id_bucle_manual: str | None = None
        self._id_refresco: str | None = None

        self.manual_lat = 0.0
        self.manual_lon = -60.0
        self.manual_ultima_pos: tuple[float, float] | None = None
        self.rumbo_manual = 90.0
        self.distancia_manual_km = 0.0
        self.teclas_pulsadas: set[str] = set()
        self.acciones = 0
        self.correcciones = 0
        self.arrastrando = False
        self._offset_arrastre = (0.0, 0.0)
        self._posicion_inicializada = False
        # Cuadricula de meridianos y paralelos: apagada al arrancar, se enciende
        # con el boton o con G. `ihc.cuadricula` deja el motivo en el docstring.
        self.ver_cuadricula = False
        # La malla en pixeles de mapa se calcula una vez: no depende de la vista.
        self._cache_rejilla: list[cuadricula.LineaRejilla] | None = None
        self.velocidad_sim: float = 1.0  # multiplicador de velocidad de la simulacion
        self.auto_lat: float = 0.0
        self.auto_lon: float = 0.0
        # --- buscador y encuadre automatico -------------------------
        self.resultados: list[Aeropuerto] = []
        self.seleccionado: Aeropuerto | None = None
        self._id_busqueda: str | None = None
        # Cache de contornos ya convertidos a pixeles de mapa.
        self._cache_angulos: dict[int, tuple[int, list[tuple[float, float]]]] = {}
        # Capa de fondo en imagen: la original y los reescalados ya hechos.
        self._fondo_original: Image.Image | None = None
        self._fondo_cache: dict[tuple[int, int], tk.PhotoImage] = {}
        self._fondo_foto: tk.PhotoImage | None = None
        root.title("Simulador de Posicionamiento Interactivo  ·  Auto vs Manual")

        self._construir_interfaz()
        self.mapa.encajar(self.ancho_lienzo, self.alto_lienzo, margen=8)
        self._poblar_ruta_demo()
        if self.ruta:
            origen = self.ruta[0]
            self.manual_lat, self.manual_lon = geo.punto_sobre_arco(
                origen.lat, origen.lon, 90.0, 900.0)
        self.manual_ultima_pos = (self.manual_lat, self.manual_lon)
        self._dibujar_todo()
        self._actualizar_paneles()
        self._enlazar_eventos()
        self._avisos_carga()
        self._ajustar_al_escritorio()

    def _ajustar_al_escritorio(self) -> None:
        """Encaja la ventana en la pantalla del usuario.

        La altura del lienzo no es fija: se calcula como la pantalla menos la
        barra, el buscador, los tres paneles y la consola. Con un alto fijo de
        560 px la ventana pedia 812 px y en un portatil de 768 px los paneles y
        la consola quedaban fuera de la pantalla.
        """
        self.root.update_idletasks()
        # Todo lo que verticalmente no es el mapa.
        fijo = max(0, self.root.winfo_reqheight() - self.lienzo.winfo_reqheight())
        ancho, alto, alto_lienzo = dimensiones_ventana(
            self.root.winfo_screenwidth(), self.root.winfo_screenheight(), fijo)
        self.lienzo.configure(height=alto_lienzo)
        self.root.update_idletasks()
        x = max(0, (self.root.winfo_screenwidth() - ancho) // 2)
        self.root.geometry(f"{ancho}x{alto}+{x}+0")
        self.root.minsize(ANCHO_MINIMO_VENTANA, min(700, fijo + ALT_MINIMO_LIENZO))
        self.mapa.encajar(self.lienzo.winfo_width(), self.lienzo.winfo_height(),
                          margen=8)
        self._dibujar_todo()

    # ==================================================================
    # PRESENTACION: interfaz
    # ==================================================================
    def _construir_interfaz(self) -> None:
        self.ancho_lienzo, self.alto_lienzo = 1000, 560
        # El mapa es vectorial: se dibujan los contornos de los paises en el
        # sistema de coordenadas de la proyeccion, sin imagen de fondo. El
        # tamano sigue siendo el de la proyeccion, porque es el espacio en el
        # que trabajan `geo_a_mapa` y la repeticion del mundo.
        self.mapa = Mapa(
            Proyeccion(limites_calibrados(), *TAMANO_MAPA),
            TAMANO_MAPA,
        )

        contenedor = tk.Frame(self.root, bg=tema.FONDO)
        contenedor.pack(fill="both", expand=True)

        # --- barra de herramientas -----------------------------------
        barra = tk.Frame(contenedor, bg=tema.FONDO_PANEL, pady=6)
        barra.pack(fill="x")

        self._boton(barra, "Ayuda", self.mostrar_ayuda, tipo="secundario")
        self.boton_cuadricula = self._boton(barra, "Cuadrícula", self.alternar_cuadricula,
                                            tipo="secundario")
        self._separador(barra)
        tk.Label(barra, text="Anim.:", bg=tema.FONDO_PANEL, fg=tema.TEXTO_TENUE,
                 font=tema.FUENTE_PEQUENA).pack(side="left")
        self.escala_velocidad = tk.Scale(
            barra, from_=1, to=10, orient="horizontal", length=90, showvalue=True,
            bg=tema.FONDO_PANEL, fg=tema.TEXTO, troughcolor=tema.FONDO_ALT,
            highlightthickness=0, bd=0, sliderlength=14, font=tema.FUENTE_PEQUENA,
            command=lambda v: setattr(self, "velocidad_sim", float(v)))
        self.escala_velocidad.set(1)
        self.escala_velocidad.pack(side="left", padx=(0, 6))
        self._separador(barra)
        tk.Label(barra, text="Vel. avión:", bg=tema.FONDO_PANEL, fg=tema.TEXTO_TENUE,
                 font=tema.FUENTE_PEQUENA).pack(side="left")
        self.entrada_velocidad = self._entrada(barra, "850", 5)
        tk.Label(barra, text="km/h", bg=tema.FONDO_PANEL, fg=tema.TEXTO_TENUE,
                 font=tema.FUENTE_PEQUENA).pack(side="left", padx=(2, 0))
        # Botones de vuelo en la derecha (se empaquetan de derecha a izquierda)
        self.boton_iniciar = self._boton(barra, "Iniciar vuelo automático", self.iniciar_vuelo,
                                         lado="right")
        self.boton_pausar = self._boton(barra, "Pausar", self.alternar_pausa,
                                        deshabilitado=True, lado="right")
        self.boton_reiniciar_vuelo = self._boton(barra, "Reiniciar vuelo",
                                                  self.reiniciar_vuelo,
                                                  tipo="secundario", deshabilitado=True,
                                                  lado="right")

        # --- fila de puntos de ruta -----------------------------------
        fila_ruta = tk.Frame(contenedor, bg=tema.FONDO_PANEL, pady=4)
        fila_ruta.pack(fill="x")

        tk.Label(fila_ruta, text="Ruta:", bg=tema.FONDO_PANEL, fg=tema.TEXTO_TENUE,
                 font=tema.FUENTE_PEQUENA).pack(side="left", padx=(10, 4))
        self.marco_puntos = tk.Frame(fila_ruta, bg=tema.FONDO_PANEL)
        self.marco_puntos.pack(side="left")
        self.entradas_puntos: list[tk.Entry] = []
        self.flechas_puntos: list[tk.Label] = []
        for codigo in tema.RUTA_DEMOSTRACION:
            self._crear_entrada_punto(codigo)
        self._boton(fila_ruta, "+", self.agregar_entrada_punto, tipo="secundario")
        self._boton(fila_ruta, "−", self.quitar_entrada_punto, tipo="secundario")
        self._boton(fila_ruta, "Buscar ruta", self.buscar_ruta, tipo="secundario")

        # --- dropdown flotante compartido para los campos de ruta -----
        self._resultados_dropdown: list[Aeropuerto] = []
        self._entrada_activa: tk.Entry | None = None
        self._dropdown = tk.Toplevel(self.root)
        self._dropdown.withdraw()
        self._dropdown.overrideredirect(True)
        self._dropdown.wm_attributes("-topmost", True)
        self._dropdown.wm_transient(self.root)
        self._lista_dropdown = tk.Listbox(
            self._dropdown, height=7, bg=tema.FONDO_ALT, fg=tema.TEXTO,
            font=tema.FUENTE_PEQUENA, selectbackground=tema.AUTO,
            selectforeground=tema.FONDO, activestyle="none",
            exportselection=False, relief="flat",
            highlightthickness=1, highlightbackground=tema.BORDE, width=42)
        self._lista_dropdown.pack(fill="both", expand=True)
        self._lista_dropdown.bind("<ButtonRelease-1>", self._elegir_de_dropdown)
        self._lista_dropdown.bind("<Return>", self._elegir_de_dropdown)
        self._lista_dropdown.bind("<Escape>", lambda _e: self._ocultar_dropdown())
        self._lista_dropdown.bind("<Up>", self._dropdown_subir)

        # --- buscador y filtro ----------------------------------------
        # Dibujar los 4.568aderos a la vez costaba 100 ms por redibujo y
        # 15.000 elementos en el lienzo. El buscador resuelve las dos cosas:
        # localizar un aeropuerto concreto y no dibujarlo todo.
        fila_busqueda = tk.Frame(contenedor, bg=tema.FONDO_PANEL)
        fila_busqueda.pack(fill="x")

        tk.Label(fila_busqueda, text="Buscar aeropuerto", bg=tema.FONDO_PANEL,
                 fg=tema.TEXTO_TENUE, font=tema.FUENTE_PEQUENA
                 ).pack(side="left", padx=(10, 4))
        self.entrada_busqueda = self._entrada(fila_busqueda, "", 26)
        self.entrada_busqueda.bind("<KeyRelease>", self._al_escribir_busqueda)
        self.entrada_busqueda.bind("<Return>", lambda _e: self._elegir_resultado())
        self.entrada_busqueda.bind("<Escape>", lambda _e: self._ocultar_resultados())

        self.lista_resultados = tk.Listbox(
            fila_busqueda, height=5, bg=tema.FONDO_ALT, fg=tema.TEXTO,
            font=tema.FUENTE_PEQUENA, highlightthickness=1,
            highlightbackground=tema.BORDE, highlightcolor=tema.BORDE,
            selectbackground=tema.AUTO, selectforeground=tema.FONDO,
            activestyle="none", exportselection=False, relief="flat")
        self.lista_resultados.pack(side="left", padx=(10, 10), fill="both", expand=True)
        self.lista_resultados.bind("<Double-Button-1>", lambda _e: self._elegir_resultado())
        self.lista_resultados.bind("<Return>", lambda _e: self._elegir_resultado())
        self.lista_resultados.bind("<FocusOut>", lambda _e: None)
        self.lista_resultados.pack_forget()

        # --- mapa ----------------------------------------------------
        marco = tk.Frame(contenedor, bg=tema.FONDO, pady=6)
        marco.pack(fill="both", expand=True)
        self.lienzo = tk.Canvas(marco, width=self.ancho_lienzo, height=self.alto_lienzo,
                                bg=tema.FONDO, highlightthickness=1,
                                highlightbackground=tema.BORDE, cursor="crosshair")
        self.lienzo.pack(fill="both", expand=True)

        # --- telemetria ----------------------------------------------
        paneles = tk.Frame(contenedor, bg=tema.FONDO, pady=6)
        paneles.pack(fill="x")
        self.panel_auto = self._panel(paneles, "VUELO AUTOMATICO", tema.AUTO)
        self.panel_manual = self._panel(paneles, "CONTROL MANUAL", tema.MANUAL)
        self._boton(self.panel_manual["marco"], "Reiniciar medición",
                    self.reiniciar_medicion, tipo="secundario")

        # --- consola -------------------------------------------------
        self.consola = tk.Label(contenedor, text="", anchor="w", bg=tema.FONDO_PANEL,
                                fg=tema.TEXTO_TENUE, font=tema.FUENTE_PEQUENA,
                                padx=10, pady=4)
        self.consola.pack(fill="x")

    @staticmethod
    def _separador(padre: tk.Widget) -> None:
        tk.Frame(padre, bg=tema.BORDE, width=1, height=22).pack(side="left", fill="y", padx=10)

    def _selector(self, padre: tk.Widget, texto: str, opciones: Sequence[tuple[str, str]],
                  comando) -> tk.Menubutton:
        """Menu desplegable con la piel del tema, para elegir entre pocas opciones."""
        boton = tk.Menubutton(padre, text=texto, bg=tema.FONDO_ALT, fg=tema.TEXTO,
                              activebackground=tema.BORDE, activeforeground=tema.TEXTO,
                              font=tema.FUENTE_PEQUENA, relief="raised", bd=1,
                              indicatoron=1, highlightthickness=0, padx=8)
        menu = tk.Menu(boton, tearoff=0, bg=tema.FONDO_ALT, fg=tema.TEXTO,
                       activebackground=tema.AUTO, activeforeground=tema.FONDO,
                       font=tema.FUENTE_PEQUENA, bd=0)
        for etiqueta, clave in opciones:
            menu.add_command(label=etiqueta,
                             command=lambda c=clave: comando(c))
        boton.configure(menu=menu, state="normal")
        return boton

    def _boton(self, padre: tk.Widget, texto: str, comando, tipo: str = "primario",
               deshabilitado: bool = False, activo: bool = False,
               lado: str = "left") -> tk.Button:
        fondo, tinta = ((tema.AUTO_OSCURO, "#ffe0b2") if tipo == "primario"
                        else (tema.FONDO_ALT, tema.TEXTO))
        boton = tk.Button(
            padre, text=texto, command=comando, font=tema.FUENTE_TEXTO, bg=fondo, fg=tinta,
            activebackground=tema.BORDE, activeforeground=tema.TEXTO, relief="flat", bd=0,
            padx=11, pady=5, cursor="hand2", highlightthickness=0, takefocus=False,
        )
        if deshabilitado:
            boton.configure(state="disabled", bg=tema.FONDO_ALT, fg=tema.TEXTO_TENUE)
        if activo:
            boton.configure(relief="sunken", bg=tema.BORDE)
        boton.pack(side=lado, padx=3)
        return boton

    def _entrada(self, padre: tk.Widget, valor: str, ancho: int) -> tk.Entry:
        entrada = tk.Entry(padre, width=ancho, font=tema.FUENTE_MONO, justify="center",
                           bg=tema.FONDO_ALT, fg=tema.TEXTO, insertbackground=tema.TEXTO,
                           relief="flat", highlightthickness=1, highlightbackground=tema.BORDE)
        entrada.insert(0, valor)
        entrada.pack(side="left", padx=4, ipady=3)
        return entrada

    def _panel(self, padre: tk.Widget, titulo: str, color: str) -> dict:
        marco = tk.Frame(padre, bg=tema.FONDO_PANEL, highlightthickness=1,
                         highlightbackground=tema.BORDE, padx=12, pady=6)
        marco.pack(side="left", fill="both", expand=True, padx=4)
        tk.Label(marco, text=titulo, bg=tema.FONDO_PANEL, fg=color,
                 font=tema.FUENTE_TITULO_S, anchor="w").pack(fill="x")
        texto = tk.Label(marco, text="", bg=tema.FONDO_PANEL, fg=tema.TEXTO,
                         font=tema.FUENTE_MONO, justify="left", anchor="w")
        texto.pack(fill="x", pady=(4, 0))
        return {"marco": marco, "texto": texto}

    # ==================================================================
    # PRESENTACION: recursos graficos
    # ==================================================================

    def _dibujar_todo(self) -> None:
        """Redibuja el lienzo completo y vuelve a enlazar los eventos del avion."""
        self.lienzo.delete("todo")
        self._dibujar_fondo()
        if self.ver_cuadricula:
            self._dibujar_cuadricula()
        self._dibujar_paises()
        self._dibujar_ruta()
        self._dibujar_aeropuertos()
        self._dibujar_aviones()
        if self.ver_cuadricula:
            self._dibujar_esfera()
        self._enlazar_eventos_avion()

    def _dibujar_cuadricula(self) -> None:
        """Meridianos y paralelos de la proyeccion, con su rotulo.

        Encaja entre el mar y los paises, no al final: la malla es una
        referencia de coordenadas y si fuera de la costa competiria por la misma
        linea. Lo que no puede es tapar el mapa, asi que va con trazo fino y con
        la jerarquia habitual de cartografia: continua cada 30 grados, punteada
        cada 15.

        Los puntos se guardan en pixeles de mapa, que no cambian con la vista, y
        en cada fotograma solo se aplica la transformada `pantalla = x*k + c`. Es
        el mismo truco que usa `_dibujar_paises` con los contornos, y por el
        mismo motivo: convertir 2.300 puntos en cada redibujo costaria mas que
        dibujarlos.
        """
        if self._cache_rejilla is None:
            proyeccion = self.mapa.proyeccion
            self._cache_rejilla = cuadricula.rejilla(proyeccion, proyeccion.limites)
        kx, ky, cx, cy = self.mapa.coeficientes_pantalla()
        copias = self.mapa.copias_de_x(0.0, self.mapa.ancho_mundo)
        # Las lineas se dibujan siempre, sean cuales sean: son finas y no
        # ensucian. Lo que se apaga al alejar es el rotulo, que a 30 grados por
        # debajo de 60 px deja de distinguirse de la linea que rotula.
        paso_px = (self.mapa.ancho_mundo / self.mapa.proyeccion.limites.ancho
                   * cuadricula.PASO_LON) * kx
        con_etiquetas = paso_px >= SEPARACION_MIN_ETIQUETAS_PX
        for linea in self._cache_rejilla:
            # Un paralelo es una horizontal en la pantalla: si cae fuera del
            # alto del lienzo no hay nada que dibujar ni que rotular.
            y_primero = linea.puntos[0][1] * ky + cy
            if linea.eje == "lat" and not (0.0 <= y_primero <= self.alto_lienzo):
                continue
            for vuelta in copias:
                puntos = [(px * kx + cx + vuelta * kx, py * ky + cy) for px, py in linea.puntos]
                if self._fuera_de_pantalla(puntos):
                    continue
                menor = linea.clase == "menor"
                self.lienzo.create_line(
                    *[c for punto in puntos for c in punto],
                    fill=tema.REJILLA_MENOR if menor else tema.REJILLA_MAYOR,
                    width=1, dash=(3, 5) if menor else (),
                    tags=("todo", "cuadricula"))
                if con_etiquetas and not menor:
                    self._etiqueta_cuadricula(linea, puntos[0])

    def _etiqueta_cuadricula(self, linea: cuadricula.LineaRejilla,
                            primero: tuple[float, float]) -> None:
        """Rotula un meridiano en el borde superior y un paralelo en el izquierdo.

        El borde se toma del mapa y se recorta a la ventana: al desplazar la
        vista el mapa puede quedarse a medias fuera, y el rotulo tiene que
        pegarse al borde que se ve o aparecer en mitad del oceano.
        """
        x, y = primero
        x0, y0, ancho, alto = self.mapa.rect_mapa
        if linea.eje == "lon":
            if not (0.0 <= x <= self.ancho_lienzo):
                return
            self._texto(x, min(max(y0, 4.0), self.alto_lienzo - 4.0),
                        cuadricula.texto_etiqueta(linea), tema.REJILLA_ETIQUETA,
                        tema.FUENTE_PEQUENA, "cuadricula")
        elif 0.0 <= y <= self.alto_lienzo:
            self._texto(min(max(x0, 4.0), self.ancho_lienzo - 4.0), y,
                        cuadricula.texto_etiqueta(linea), tema.REJILLA_ETIQUETA,
                        tema.FUENTE_PEQUENA, "cuadricula", ancla="w")

    def _dibujar_fondo(self) -> None:
        """Fondo del lienzo: el oceano, el borde de la lamina y la capa de imagen.

        Sin imagen, esto es lo que habia: un rectangulo de mar y el borde del
        mapa. Las costas las dibuja `_dibujar_paises` en vector, y como salen de
        Natural Earth y comparten la proyeccion con los puntos, no pueden
        desfasarse entre si.

        La imagen de fondo, si esta, va encima del rectangulo y debajo de los
        paises. Sale de `generar_fondo.py`, que la dibuja con esta misma
        proyeccion, de modo que su costa y la linea del vector van superpuestas.

        El contorno del mapa se repasa al final, en un rectangulo aparte: la
        imagen es opaca y, dibujada despues, se comeria el borde.
        """
        x, y, ancho, alto = self.mapa.rect_mapa
        self.lienzo.create_rectangle(0, 0, self.ancho_lienzo, self.alto_lienzo,
                                     fill=tema.FONDO, outline="", tags=("todo", "base"))
        self.lienzo.create_rectangle(x, y, x + ancho, y + alto, fill=tema.AGUA,
                                     outline="", tags=("todo", "base"))
        self._dibujar_fondo_imagen()
        self.lienzo.create_rectangle(x, y, x + ancho, y + alto, fill="",
                                     outline=tema.BORDE, tags=("todo", "base"))

    def _dibujar_fondo_imagen(self) -> None:
        """Capa de fondo en imagen, repetida en cada vuelta del mundo visible.

        La imagen mide lo mismo que el mapa en pixeles de proyeccion y se coloca
        con la misma matriz que usa `_dibujar_paises`, pantalla = x * kx + cx, de
        modo que la costa de la imagen y la linea del vector van superpuestas sin
        ningun ajuste. Se repite por el mismo motivo que los contornos: al
        desplazar la vista hacia el corte del Atlantico, una sola vuelta dejaria
        medio lienzo sin imagen.
        """
        if self._fondo_original is None and not self._cargar_fondo():
            return
        kx, ky, cx, cy = self.mapa.coeficientes_pantalla()
        ancho_mapa = float(TAMANO_MAPA[0])
        clave = tamano_fondo(kx, ky)
        if clave is None:
            return
        foto = self._fondo_cache.get(clave)
        if foto is None:
            foto = self._re_escalar_fondo(clave)
            if foto is None:
                return
        for vuelta in self.mapa.copias_de_x(0.0, ancho_mapa):
            x = vuelta * kx + cx
            if x > self.ancho_lienzo or x + clave[0] < 0.0:
                continue
            self.lienzo.create_image(x, cy, image=foto, anchor="nw",
                                     tags=("todo", "fondo"))

    def _cargar_fondo(self) -> bool:
        """Abre la imagen de fondo una sola vez. Dice si se pudo.

        Opcional a proposito: sin Pillow, o sin el fichero, la app sigue
        arrancando con el mar plano de siempre. Una dependencia que impide
        abrir la app es peor que un fondo que falta.

        El tamano se comprueba contra `TAMANO_MAPA` y, si no coincide, no se
        dibuja. Un fondo de otra proporcion se veria estirado y sus costas se
        separarian de las lineas al final de la lamina; es justo lo que
        `verificar_fondo.py` rechaza, asi que aqui tampoco se disimula.
        """
        if self._fondo_original is not None:
            return True
        if not FONDO_MAPA.exists():
            return False
        try:
            from PIL import Image
        except ImportError:
            return False
        with Image.open(FONDO_MAPA) as abierta:
            imagen = abierta.convert("RGB")
        if imagen.size != TAMANO_MAPA:
            imagen = imagen.resize(TAMANO_MAPA, Image.LANCZOS)
        self._fondo_original = imagen
        return True

    def _re_escalar_fondo(self, clave: tuple[int, int]) -> tk.PhotoImage | None:
        """PhotoImage del fondo al tamano pedido, guardada en la cache.

        El tamano se pide exacto a proposito: quantized, un fondo con 4 px de
        error se estiraba hasta 1,4 % y la costa se separaba de la linea varios
        grados en el borde opuesto. Al arrastrar la vista el tamano no cambia y
        esto sale de la cache; solo se paga al reencuadrar.
        """
        if self._fondo_original is None:
            return None
        from PIL import Image, ImageTk

        # El reescalado mas reciente se guarda tambien suelto: si la cache
        #otationa, el objeto sigue vivo mientras haya un elemento del lienzo que
        # lo use, y un PhotoImage que se recoge deja un hueco en blanco.
        self._fondo_foto = ImageTk.PhotoImage(
            self._fondo_original.resize(clave, Image.BILINEAR))
        self._fondo_cache[clave] = self._fondo_foto
        while len(self._fondo_cache) > FONDOS_EN_CACHE:
            self._fondo_cache.pop(next(iter(self._fondo_cache)))
        return self._fondo_foto

    def _dibujar_paises(self) -> None:
        """Capa vectorial real: los contornos de los 242 paises de Natural Earth 50m.

        Es la unica capa del mapa. Las posiciones se derivan de las mismas
        coordenadas que dibujan los puntos, asi que ambos no pueden
        desalinearse entre si. Cada contorno se repite en todas las copias del
        mundo visibles; si solo se dibujara en su posicion original, al
        desplazar la vista hacia el corte del Atlantico apareceria oceano sin
        costa.

        Los anillos se filtran por tamano en pantalla: con la vista del mundo
        entero se dibujan los grandes y se omiten las motas de 2 px, y al
        acercarse van apareciendo los pequenos.
        """
        escala_pantalla = self.mapa.vista.escala * self.mapa.escala_imagen
        y_sup, y_inf = self.mapa.rango_y_visible()
        kx, ky, cx, cy = self.mapa.coeficientes_pantalla()

        for pais in self.fuente.paises:
            for anillo in pais.anillos:
                if len(anillo) < 3:
                    continue
                puntos_mapa, ancho, alto = self._geometria_de_anillo(anillo)
                if max(ancho, alto) * escala_pantalla < LADO_MINIMO_PX:
                    continue
                xs = [p[0] for p in puntos_mapa]
                ys = [p[1] for p in puntos_mapa]
                if max(ys) < y_sup or min(ys) > y_inf:
                    continue
                for vuelta in self.mapa.copias_de_x(min(xs), max(xs)):
                    if vuelta:
                        desplazado = (kx, ky, cx + vuelta * kx, cy)
                    else:
                        desplazado = (kx, ky, cx, cy)
                    puntos = [(px * desplazado[0] + desplazado[2],
                               py * desplazado[1] + desplazado[3])
                              for px, py in puntos_mapa]
                    if self._fuera_de_pantalla(puntos):
                        continue
                    self.lienzo.create_line(*[c for punto in puntos for c in punto],
                                            fill=tema.COSTA, width=1,
                                            tags=("todo", "paises"))

    def _geometria_de_anillo(
        self, anillo: Sequence[Sequence[float]]
    ) -> tuple[list[tuple[float, float]], float, float]:
        """Anillo en pixeles de mapa con su caja envolvente, cacheados.

        Los contornos no cambian entre fotogramas, y convertir de (lat, lon) a
        pixeles cuesta unas 0,15 ms por punto. Sin la cache, esa sola conversion
        era lo que mas tiempo consumia del redibujo completo. La caja
        envolvente se guarda en el mismo sitio porque el nivel de detalle y el
        descarte por pantalla la necesitan en cada fotograma.
        """
        clave = id(anillo)
        guardado = self._cache_angulos.get(clave)
        if guardado is not None and guardado[0] == len(anillo):
            return guardado[1], guardado[2], guardado[3]
        puntos = self.mapa.anillo_a_mapa(anillo)
        xs = [p[0] for p in puntos]
        ys = [p[1] for p in puntos]
        caja = (min(xs), min(ys), max(xs), max(ys))
        self._cache_angulos[clave] = (len(anillo), puntos, caja[2] - caja[0], caja[3] - caja[1])
        return puntos, caja[2] - caja[0], caja[3] - caja[1]


    def _dibujar_ruta(self) -> None:
        """Trayectoria de la ruta: arcos de gran circulo, no rectas en el lienzo.

        Los puntos se dibujan en la copia del mundo mas cercana a la vista.
        Sin eso, una ruta que cruza el Atlantico (Quito → Madrid) se veria como
        una linea recta de borde a borde, porque en la proyeccion sus dos
        extremos quedan a 1.426 pixeles de distancia siendo el mapa de 1.800.
        """
        if len(self.ruta) < 2:
            return
        puntos: list[tuple[float, float]] = []
        for origen, destino in zip(self.ruta, self.ruta[1:]):
            for k in range(41):
                punto = geo.interpolar((origen.lat, origen.lon),
                                       (destino.lat, destino.lon), k / 40.0)
                puntos.append(self.mapa.a_pantalla(punto.lat, punto.lon, repetir=True))
        # Dibujar por tramos: si la ruta salta entre copias del mundo, un solo
        # `create_line` cruzaria el mapa entero de lado a lado.
        for tramo in self._tramos_de_ruta(puntos):
            if len(tramo) < 2:
                continue
            self.lienzo.create_line(*[c for punto in tramo for c in punto],
                                    fill=tema.RUTA_PLANIFICADA, width=tema.GROSOR_RUTA,
                                    dash=(4, 3), tags=("todo", "ruta"))
        # Solo las paradas intermedias llevan marcador numerado. El primer y el
        # ultimo punto los dibuja `_dibujar_aeropuestos` como origen y destino,
        # con su etiqueta; marcarlos aqui tambien los duplicaba.
        for indice, aeropuerto in enumerate(self.ruta[1:-1], start=2):
            x, y = self.mapa.a_pantalla(aeropuerto.lat, aeropuerto.lon, repetir=True)
            self.lienzo.create_oval(x - 3.5, y - 3.5, x + 3.5, y + 3.5, fill=tema.TEXTO,
                                    outline=tema.FONDO, tags=("todo", "ruta"))
            self._texto(x, y - 12, f"{indice}. {aeropuerto.iata}", tema.TEXTO,
                        tema.FUENTE_ETIQUETA, "ruta")

    def _tramos_de_ruta(self, puntos: Sequence[tuple[float, float]]
                        ) -> list[list[tuple[float, float]]]:
        """Parte la polilinea donde salta de una copia del mundo a otra."""
        ancho = self.mapa.ancho_mundo * self.mapa.vista.escala * self.mapa.escala_imagen
        if ancho <= 0:
            return [list(puntos)]
        tramos: list[list[tuple[float, float]]] = [[puntos[0]]]
        for anterior, punto in zip(puntos, puntos[1:]):
            if abs(punto[0] - anterior[0]) > ancho / 2.0:
                tramos.append([punto])
            else:
                tramos[-1].append(punto)
        return tramos

    def _dibujar_aeropuertos(self) -> None:
        """Dibuja los aeropuertos de la ruta y los resultados de busqueda (top 5)."""
        # --- puntos de la ruta -----------------------------------------
        for aeropuerto in self._aeropuertos_visibles():
            x, y = self.mapa.a_pantalla(aeropuerto.lat, aeropuerto.lon, repetir=True)
            es_origen = bool(self.ruta) and aeropuerto.iata == self.ruta[0].iata
            r = tema.TAMANO_PUNTO_AEROPUERTO + 1.5
            self.lienzo.create_oval(
                x - r, y - r, x + r, y + r,
                fill=tema.EXITO if es_origen else tema.RUTA_PLANIFICADA,
                outline=tema.FONDO, tags=("todo", "aeropuerto"))
            etiqueta = f"{aeropuerto.iata} · {'origen' if es_origen else 'destino'}"
            self._texto(x, y + r + 5, etiqueta, tema.EXITO, tema.FUENTE_PEQUENA,
                        "aeropuerto")
        # --- resultados del buscador (top 5) ---------------------------
        iatas_ruta = {a.iata for a in self.ruta}
        x0, y0, ancho, alto = self.mapa.rect_mapa
        for i, aeropuerto in enumerate(self.resultados[:5], start=1):
            if aeropuerto.iata in iatas_ruta:
                continue
            x, y = self.mapa.a_pantalla(aeropuerto.lat, aeropuerto.lon, repetir=True)
            if not (x0 - 12 <= x <= x0 + ancho + 12 and y0 - 12 <= y <= y0 + alto + 12):
                continue
            r = tema.TAMANO_PUNTO_AEROPUERTO + 0.5
            self.lienzo.create_oval(
                x - r, y - r, x + r, y + r,
                fill=tema.ALERTA, outline=tema.FONDO, tags=("todo", "aeropuerto"))
            self._texto(x, y + r + 5,
                        f"{i}. {aeropuerto.iata}",
                        tema.ALERTA, tema.FUENTE_ETIQUETA, "aeropuerto")
        # --- aeropuerto seleccionado (clic en lista) -------------------
        sel = self.seleccionado
        if sel is not None and sel.iata not in iatas_ruta:
            x, y = self.mapa.a_pantalla(sel.lat, sel.lon, repetir=True)
            r = tema.TAMANO_PUNTO_AEROPUERTO + 3
            self.lienzo.create_oval(
                x - r, y - r, x + r, y + r,
                fill=tema.TEXTO_TITULO, outline=tema.AUTO, width=1.5,
                tags=("todo", "aeropuerto"))
            self._texto(x, y + r + 5,
                        f"{sel.iata} · {sel.ciudad}",
                        tema.TEXTO_TITULO, tema.FUENTE_PEQUENA, "aeropuerto")

    def _aeropuertos_visibles(self) -> list[Aeropuerto]:
        """Solo se dibujan el origen y el destino de la ruta.

        Antes se dibujaban hasta 1.171 aeropuertos grandes y el buscador
        anadia sus resultados. Con el encuadre automatico, la vista ya se
        ajusta a los dos puntos de la ruta, asi que el resto solo anade
        elementos al lienzo sin aportar informacion: la diferencia se nota
        justo en la fluidez, que es lo que reporto el usuario.
        """
        x0, y0, ancho, alto = self.mapa.rect_mapa
        visibles: list[Aeropuerto] = []
        for aeropuerto in self._aeropazgos_destacados():
            if not any(a.iata == aeropuerto.iata for a in visibles):
                visibles.append(aeropuerto)
        fuera = []
        for aeropuerto in visibles:
            x, y = self.mapa.a_pantalla(aeropuerto.lat, aeropuerto.lon, repetir=True)
            if x0 - 8 <= x <= x0 + ancho + 8 and y0 - 8 <= y <= y0 + alto + 8:
                fuera.append(aeropuerto)
        return fuera

    def _aeropazgos_destacados(self) -> list[Aeropuerto]:
        """Los dos unicos que se dibujan: el origen y el destino de la ruta.

        Ni las paradas intermedias, ni los resultados del buscador, ni el
        aeropuerto seleccionado aparte. Es el requisito pedido: en el mapa solo
        aparecen los dos puntos que se han elegido como origen y destino. El
        buscador muestra sus resultados en su propia lista, asi que no se pierde
        esa informacion.
        """
        if not self.ruta:
            return []
        extremos = [self.ruta[0], self.ruta[-1]]
        if extremos[0] is extremos[1]:
            return [extremos[0]]
        return extremos

    def _fuera_de_pantalla(self, puntos: Sequence[tuple[float, float]]) -> bool:
        if not puntos:
            return True
        xs = [p[0] for p in puntos]
        ys = [p[1] for p in puntos]
        return (max(xs) < 0 or min(xs) > self.ancho_lienzo
                or max(ys) < 0 or min(ys) > self.alto_lienzo)

    def _texto(self, x: float, y: float, texto: str, color: str, fuente, etiqueta: str,
               ancla: str = "center") -> None:
        """Texto con halo oscuro: garantiza legibilidad sobre cualquier color de mapa.

        El halo son cuatro elementos del lienzo mas el texto. Solo lo llevan las
        etiquetas que se pintan sobre el mapa; las que van en los paneles usan
        widgets de Tk y no pasan por aqui.
        """
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            self.lienzo.create_text(x + dx, y + dy, text=texto, fill=tema.FONDO,
                                    font=fuente, anchor=ancla, tags=("todo", etiqueta))
        self.lienzo.create_text(x, y, text=texto, fill=color, font=fuente, anchor=ancla,
                                tags=("todo", etiqueta))

    # --- el globo de la esquina: la misma malla, pero sobre la esfera ----
    def _dibujar_esfera(self) -> None:
        """Miniatura de la esfera, en la esquina inferior derecha.

        Es la otra mitad de la cuadrícula. El mapa es el cilindro desarrollado, y
        ahi los meridianos y los paralelos son rectos; aqui son arcos, porque la
        rejilla se dibuja con la proyeccion ortografica. Ver las dos a la vez es
        lo que explica la deformacion sin tener que decirla: el mapa es el
        cilindro desarrollado y el globo es la esfera, y las latitudes altas
        aparecen estiradas en el primero.

        Va en un globo aparte y no superpuesta al mapa a proposito. Dibujada
        encima, la curva de un meridiano caeria a grados de la costa que dice
        representar y pareceria un error de dibujo, no la proyeccion de la esfera.

        El globo se centra en lo que se esta mirando (`centro_de_vista`), de modo
        que gira al desplazar el mapa, y los dos puntos de la ruta se marcan
        encima cuando caen en la cara visible.
        """
        sitio = cuadricula.colocar_esfera(self.ancho_lienzo, self.alto_lienzo,
                                          self.mapa.rect_mapa)
        if sitio is None:
            return
        cx, cy, radio = sitio
        centro = (cx, cy)
        lat0, lon0 = cuadricula.centro_de_vista(self.mapa)
        # El disco va primero y es opaco: la esfera tiene que leerse por encima
        # de los paises, no mezclarse con ellos.
        self.lienzo.create_oval(cx - radio, cy - radio, cx + radio, cy + radio,
                                fill=tema.ESFERA_FONDO, outline=tema.ESFERA_BORDE,
                                width=1, tags=("todo", "esfera"))
        for linea in cuadricula.rejilla_esfera(lat0, lon0, radio, centro):
            fuerte = linea.clase in ("ecuator", "central")
            self.lienzo.create_line(
                *[c for punto in linea.puntos for c in punto],
                fill=tema.ESFERA_MALLA_FUERTE if fuerte else tema.ESFERA_MALLA,
                width=1, tags=("todo", "esfera"))
        self._puntos_en_la_esfera(cx, cy, radio, centro, lat0, lon0)
        self.lienzo.create_text(cx, cy + radio + 9, text="esfera · ortográfica",
                                fill=tema.TEXTO_TENUE, font=tema.FUENTE_PEQUENA,
                                tags=("todo", "esfera"))

    def _puntos_en_la_esfera(self, cx: float, cy: float, radio: float, centro: tuple[float, float],
                             lat0: float, lon0: float) -> None:
        """Marca sobre el globo el centro de la vista y los dos puntos de ruta.

        El centro de la vista es la cruz pequena: dice hacia donde mira el mapa
        plano, y por eso el globo se entiende como "la parte de la esfera que
        estas viendo". Origen y destino mantienen sus colores, que ya son el
        codigo de posicion del avion, para no obligar a mirar la leyenda otra vez.
        """
        self.lienzo.create_line(cx - 4, cy, cx + 4, cy, fill=tema.TEXTO,
                                tags=("todo", "esfera"))
        self.lienzo.create_line(cx, cy - 4, cx, cy + 4, fill=tema.TEXTO,
                                tags=("todo", "esfera"))
        for indice, aeropuerto in enumerate(self._aeropazgos_destacados()):
            punto = cuadricula.ortografica(aeropuerto.lat, aeropuerto.lon,
                                          lat0, lon0, radio, centro)
            if punto is None:
                continue
            color = tema.EXITO if indice == 0 else tema.RUTA_PLANIFICADA
            self.lienzo.create_oval(punto[0] - 2, punto[1] - 2, punto[0] + 2, punto[1] + 2,
                                    fill=color, outline=tema.ESFERA_FONDO,
                                    tags=("todo", "esfera"))

    # --- primitivas graficas: los dos aviones -------------------------
    @staticmethod
    def _geometria_avion(x: float, y: float, radio: float,
                         orientacion: float) -> list[tuple[float, float]]:
        """Silueta de avion (morro, alas, cola) rotada segun el rumbo.

        El morro apunta al norte con 0 grados; la rotacion usa las funciones
        trigonometricas del lienzo, de modo que el avion "mira" al destino.
        """
        forma = [(0.0, -1.0),      # nariz
                 (-0.10, -0.35),
                 (-0.65, 0.05),    # ala izquierda
                 (-0.70, 0.18),
                 (-0.15, 0.05),
                 (-0.22, 0.85),    # cola izquierda
                 (0.0, 0.75),
                 (0.22, 0.85),     # cola derecha
                 (0.15, 0.05),
                 (0.70, 0.18),     # ala derecha
                 (0.65, 0.05),
                 (0.10, -0.35)]
        rad = math.radians(orientacion)
        cos, sen = math.cos(rad), math.sin(rad)
        return [(x + (dx * cos - dy * sen) * radio, y + (dx * sen + dy * cos) * radio)
                for dx, dy in forma]

    def _crear_avion(self, x: float, y: float, color: str, relleno: str,
                     orientacion: float) -> tuple[int, int]:
        """Crea el avion con `create_polygon` y un area de agarre invisible.

        El circulo de 11 px de radio duplica el area del objetivo: mejora el
        tiempo de acquisicion (ley de Fitts) y evita fallos de arrastre, que
        es el error de interaccion mas frecuente al mover un objeto pequeno.
        """
        puntos = self._geometria_avion(x, y, tema.TAMANO_AVION, orientacion)
        avion = self.lienzo.create_polygon(*[c for punto in puntos for c in punto],
                                          fill=relleno, outline=color, width=1.5,
                                          tags=("todo", "avion"))
        area = self.lienzo.create_oval(x - 11, y - 11, x + 11, y + 11, fill="",
                                       outline="", tags=("todo", "area_avion"))
        return avion, area

    def _dibujar_aviones(self) -> None:
        if self.ruta:
            origen = self.ruta[0]
            punto = geo.punto_sobre_arco(origen.lat, origen.lon, 90.0, 900.0)
        else:
            punto = (self.manual_lat, self.manual_lon)
        x, y = self.mapa.a_pantalla(punto.lat, punto.lon, repetir=True)
        self.avion_auto, self.area_auto = self._crear_avion(x, y, tema.AUTO, tema.AUTO, 90)
        self._texto(x, y + 16, "AUTO", tema.AUTO, tema.FUENTE_ETIQUETA, "avion")

        mx, my = self.mapa.a_pantalla(self.manual_lat, self.manual_lon, repetir=True)
        self.avion_manual, self.area_manual = self._crear_avion(
            mx, my, tema.MANUAL, tema.FONDO_PANEL, 90)
        self._texto(mx, my + 16, "MANUAL", tema.MANUAL, tema.FUENTE_ETIQUETA, "avion")

    def _ubicar_avion(self, item: int, area: int, x: float, y: float, rumbo: float) -> None:
        self.lienzo.coords(item, *[c for punto in
                                    self._geometria_avion(x, y, tema.TAMANO_AVION, rumbo)
                                    for c in punto])
        self.lienzo.coords(area, x - 11, y - 11, x + 11, y + 11)

    # ==================================================================
    # DIALOGO: acciones del usuario
    # ==================================================================
    def _enlazar_eventos(self) -> None:
        self.root.bind("<KeyPress>", self._al_teclar)
        self.root.bind("<KeyRelease>", self._al_soltar_tecla)
        self.root.bind("<Escape>", lambda _e: self.detener_vuelo())
        self.lienzo.bind("<Configure>", self._al_redimensionar)

    def _enlazar_eventos_avion(self) -> None:
        """Reenlaza el arrastre tras cada redibujo (los items anteriores mueren)."""
        for etiqueta in (self.avion_manual, self.area_manual):
            self.lienzo.tag_bind(etiqueta, "<ButtonPress-1>", self.iniciar_arrastre)
            self.lienzo.tag_bind(etiqueta, "<B1-Motion>", self.arrastrar)
            self.lienzo.tag_bind(etiqueta, "<ButtonRelease-1>", self.terminar_arrastre)

    def buscar_ruta(self) -> None:
        """Lee los campos de puntos, valida los códigos IATA y construye la ruta."""
        codigos = [e.get().strip().upper() for e in self.entradas_puntos]
        codigos = [c for c in codigos if c]  # descartar campos vacíos
        if len(codigos) < 2:
            self._consola("Introduce al menos dos códigos de aeropuerto.", error=True)
            return
        puntos: list[Aeropuerto] = []
        for codigo in codigos:
            resultado = self.fuente.buscar(codigo, 1)
            if not resultado:
                self._consola(f"Código no reconocido: {codigo}. Usa el código IATA (UIO, MAD, JFK).",
                              error=True)
                return
            puntos.append(resultado[0])
        iatas = [p.iata for p in puntos]
        if len(iatas) != len(set(iatas)):
            self._consola("Hay puntos duplicados en la ruta.", error=True)
            return
        self.detener_vuelo()
        self.ruta = puntos
        self.segmento = 0
        self.progreso = 0.0
        origen = self.ruta[0]
        lat, lon = geo.punto_sobre_arco(origen.lat, origen.lon, 90.0, 900.0)
        self.manual_lat, self.manual_lon = lat, lon
        self.manual_ultima_pos = (lat, lon)
        self.distancia_manual_km = 0.0
        self.acciones = 0
        self.correcciones = 0
        self.rumbo_manual = 90.0
        escala = self.mapa.encuadrar_puntos([(a.lat, a.lon) for a in self.ruta],
                                             ESCALA_MAXIMA_AUTOMATICA)
        self._dibujar_todo()
        self._actualizar_paneles()
        distancia = geo.longitud_ruta([(a.lat, a.lon) for a in self.ruta])
        paradas = " → ".join(a.iata for a in self.ruta)
        self._consola(f"Ruta: {paradas} · {geo.formatear_distancia(distancia)} · "
                      f"encuadrada en {escala:.2f}x.")

    def _poblar_ruta_demo(self) -> None:
        encontrados = (self.fuente.por_iata(c) for c in tema.RUTA_DEMOSTRACION)
        self.ruta = [a for a in encontrados if a is not None]
        self.mapa.encuadrar_puntos([(a.lat, a.lon) for a in self.ruta],
                                   ESCALA_MAXIMA_AUTOMATICA)

    def iniciar_vuelo(self) -> None:
        if len(self.ruta) < 2:
            self._consola("Defina origen y destino para volar.", error=True)
            return
        self.detener_vuelo()
        self.registro.reiniciar()
        self.segmento = 0
        self.progreso = 0.0
        self.vuelo_en_curso = True
        self.vuelo_pausado = False
        self.reloj_auto.reiniciar()
        self.reloj_auto.iniciar()
        self._activar_controles(True)
        self._consola("Vuelo automatico: " + " → ".join(a.iata for a in self.ruta) + ".")
        self._programar_tick()

    def alternar_pausa(self) -> None:
        if not self.vuelo_en_curso:
            return
        self.vuelo_pausado = not self.vuelo_pausado
        if self.vuelo_pausado:
            self.reloj_auto.pausar()
            self.boton_pausar.configure(text="Reanudar")
            self._consola("Vuelo en pausa.")
        else:
            self.reloj_auto.iniciar()
            self.boton_pausar.configure(text="Pausar")
            self._consola("Vuelo reanudado.")
            self._programar_tick()

    def detener_vuelo(self) -> None:
        if self._id_tick is not None:
            self.root.after_cancel(self._id_tick)
            self._id_tick = None
        if self.vuelo_en_curso:
            self.reloj_auto.pausar()
            self.registro.agregar(self._medicion_auto())
        self.vuelo_en_curso = False
        self.vuelo_pausado = False
        self._activar_controles(False)
        self._actualizar_paneles()

    def reiniciar_vuelo(self) -> None:
        """Vuelve el avion automatico al primer punto sin borrar la ruta."""
        if not self.ruta or len(self.ruta) < 2:
            self._consola("No hay ruta definida.", error=True)
            return
        self.detener_vuelo()
        self.segmento = 0
        self.progreso = 0.0
        self.auto_lat = self.ruta[0].lat
        self.auto_lon = self.ruta[0].lon
        self._dibujar_todo()
        self._actualizar_paneles()
        self._consola(f"Vuelo reiniciado en {self.ruta[0].iata}.")

    def reiniciar_medicion(self) -> None:
        self.detener_vuelo()
        self.registro.reiniciar()
        self.reloj_manual.reiniciar()
        self.distancia_manual_km = 0.0
        self.acciones = 0
        self.correcciones = 0
        self.manual_ultima_pos = (self.manual_lat, self.manual_lon)
        self._actualizar_paneles()
        self._consola("Mediciones reiniciadas.")

    def alternar_cuadricula(self) -> None:
        """Enciende o apaga la rejilla de meridianos y paralelos (boton o G).

        El boton queda hundido mientras la capa esta puesta, que es la misma
        pista de estado que usan los demas controles: el color no es el unico
        codigo, y un boton que parece pulsado es mas rapido de leer que un
        boton con otro texto.

        La capa nace apagada porque compite con la costa de la imagen de fondo, y
        decidir que se veria mejor por defecto es una llamada de diseño, no un
        detalle: con la cuadrícula puesta el mapa se lee como un mapa
        coordenado, y sin ella como un mapa para orientarse.
        """
        self.ver_cuadricula = not self.ver_cuadricula
        self.boton_cuadricula.configure(
            relief="sunken" if self.ver_cuadricula else "flat",
            bg=tema.BORDE if self.ver_cuadricula else tema.FONDO_ALT)
        self._dibujar_todo()
        self._consola("Cuadrícula " + ("visible: malla de 30° y globo." if self.ver_cuadricula
                                       else "oculta."))

    def mostrar_ayuda(self) -> None:
        messagebox.showinfo(
            "Como usar el simulador",
            "BUSCADOR\n"
            "  Escriba el nombre de una ciudad, un pais o el codigo IATA\n"
            "  (por ejemplo: Quito, Japon, UIO). Los paises tambien se\n"
            "  aceptan en espanol. Pulse Ir para verlo en el mapa.\n"
            "  «Usar como origen/destino» rellena el campo correspondiente.\n\n"
            "VUELO AUTOMATICO\n"
            "  1. Escriba el codigo IATA de origen y de destino.\n"
            "  2. Pulse «Planificar vuelo» y luego «Iniciar vuelo automatico».\n\n"
            "CONTROL MANUAL\n"
            "  Teclado: W A S D o las flechas.\n"
            "  Puntero: arrastre el avion; conserva el punto de agarre.\n\n"
            "MAPA\n"
            "  El acercamiento es automatico: al planificar la ruta, la\n"
            "  vista se encuadra sola para que origen y destino se vean.\n"
            "  R lo recalcula cuando se quiera.\n"
            "  Solo se dibujan el origen y el destino.\n"
            "  «Cuadrícula» (o G) superpone los meridianos y paralelos cada\n"
            "  30 grados y rotula 0°, 30°, 60°… En la esquina aparece la\n"
            "  esfera con la misma malla, curvada: el mapa es esa esfera\n"
            "  desplegada, y en el desplegado las lineas salen rectas.\n\n"
            "OTRAS TECLAS\n"
            "  Esc  detener el vuelo        R  encuadrar la ruta\n"
            "  G    cuadrícula on/off\n\n"
            "Las distancias se calculan con haversine sobre las coordenadas\n"
            "reales de cada aeropuerto, no sobre pixeles del monitor.")

    def _al_escribir_busqueda(self, _evento: tk.Event) -> None:
        """Filtra mientras se escribe, pero sin redibujar en cada pulsación.

        El retardo de 180 ms evita que teclear "madrid" genere seis busquedas
        y seis redibujados; es la misma idea del Debounce del modelo de
        presentacion.
        """
        if self._id_busqueda is not None:
            self.root.after_cancel(self._id_busqueda)
        self._id_busqueda = self.root.after(MS_ESPERA_BUSQUEDA, self._buscar)

    def _buscar(self) -> None:
        self._id_busqueda = None
        texto = self.entrada_busqueda.get().strip()
        if not texto:
            self._ocultar_resultados()
            return
        self.resultados = self.fuente.buscar(texto, limite=MAXIMO_RESULTADOS)
        self.lista_resultados.delete(0, "end")
        for aeropuerto in self.resultados:
            self.lista_resultados.insert(
                "end", f"{aeropuerto.iata}  {aeropuerto.ciudad or aeropuerto.nombre}"
                       f"  ·  {aeropuerto.pais}")
        if self.resultados:
            self.lista_resultados.pack(side="left", padx=(10, 10), fill="both", expand=True)
            self.lista_resultados.selection_set(0)
            # Encuadra para mostrar los resultados junto con la ruta actual
            puntos = [(a.lat, a.lon) for a in self.ruta]
            puntos += [(a.lat, a.lon) for a in self.resultados[:5]]
            self.mapa.encuadrar_puntos(puntos, ESCALA_MAXIMA_AUTOMATICA)
        else:
            self.lista_resultados.pack_forget()
        self._dibujar_todo()
        if self.resultados:
            self._consola(f"{len(self.resultados)} coincidencias para «{texto}».")
        else:
            self._consola(f"Sin coincidencias para «{texto}». Pruebe nombre, ciudad o IATA.",
                          error=True)

    def _ocultar_resultados(self) -> None:
        self.resultados = []
        self.lista_resultados.delete(0, "end")
        self.lista_resultados.pack_forget()
        # Vuelve al encuadre de la ruta cuando se limpia la busqueda
        if self.ruta:
            self.mapa.encuadrar_puntos([(a.lat, a.lon) for a in self.ruta],
                                       ESCALA_MAXIMA_AUTOMATICA)
        self._dibujar_todo()

    def _elegir_resultado(self) -> None:
        """Selecciona la coincidencia señalada y lleva la vista hasta ella."""
        seleccion = self.lista_resultados.curselection()
        if not seleccion:
            if self.resultados:
                self.lista_resultados.selection_set(0)
                self.seleccionar_aeropuerto(self.resultados[0])
            return
        self.seleccionar_aeropuerto(self.resultados[seleccion[0]])

    def seleccionar_aeropuerto(self, aeropuerto: Aeropuerto) -> None:
        self.seleccionado = aeropuerto
        if any(a.iata == aeropuerto.iata for a in self.ruta):
            self.mapa.encuadrar_puntos([(a.lat, a.lon) for a in self.ruta],
                                       ESCALA_MAXIMA_AUTOMATICA)
        self._dibujar_todo()
        self._consola(f"Aeropuerto localizado: {aeropuerto.etiqueta} · {aeropuerto.pais} "
                      f"· {aeropuerto.lat:+.3f}, {aeropuerto.lon:+.3f}")

    def _crear_entrada_punto(self, codigo: str = "") -> tk.Entry:
        """Crea un campo de texto con búsqueda en vivo para un punto de la ruta."""
        if self.entradas_puntos:  # flecha entre campos
            flecha = tk.Label(self.marco_puntos, text="→", bg=tema.FONDO_PANEL,
                              fg=tema.TEXTO_TENUE, font=tema.FUENTE_TEXTO)
            flecha.pack(side="left", padx=2)
            self.flechas_puntos.append(flecha)
        entry = tk.Entry(
            self.marco_puntos, width=7, font=tema.FUENTE_MONO, justify="center",
            bg=tema.FONDO_ALT, fg=tema.TEXTO, insertbackground=tema.TEXTO,
            relief="flat", highlightthickness=1, highlightbackground=tema.BORDE)
        entry.insert(0, codigo.upper())
        entry.pack(side="left", padx=4, ipady=3)
        entry.bind("<Return>", lambda _e: self.buscar_ruta())
        entry.bind("<KeyRelease>",
                   lambda e, ent=entry: self._al_escribir_en_punto(ent, e))
        entry.bind("<FocusOut>",
                   lambda _e: self.root.after(150, self._ocultar_dropdown))
        entry.bind("<Down>", lambda _e: self._foco_a_dropdown())
        self.entradas_puntos.append(entry)
        return entry

    def agregar_entrada_punto(self) -> None:
        """Añade un nuevo campo de punto vacío a la fila de ruta."""
        entry = self._crear_entrada_punto()
        entry.focus_set()
        self._consola(f"Punto {len(self.entradas_puntos)} añadido — escribe el código IATA.")

    def quitar_entrada_punto(self) -> None:
        """Quita el último campo de punto (mínimo 2)."""
        if len(self.entradas_puntos) <= 2:
            self._consola("La ruta necesita al menos dos puntos.", error=True)
            return
        self.entradas_puntos.pop().destroy()
        if self.flechas_puntos:
            self.flechas_puntos.pop().destroy()
        self._consola(f"Punto eliminado. Quedan {len(self.entradas_puntos)} puntos.")

    # ------------------------------------------------------------------
    # Búsqueda en vivo en los campos de ruta
    # ------------------------------------------------------------------
    def _al_escribir_en_punto(self, entry: tk.Entry, evento) -> None:
        """Busca aeropuertos mientras el usuario escribe; muestra el dropdown."""
        tecla = (evento.keysym or "").lower()
        if tecla in ("return", "down", "up", "escape", "tab"):
            return
        texto = entry.get().strip()
        if len(texto) < 1:
            self._ocultar_dropdown()
            return
        resultados = self.fuente.buscar(texto, 8)
        if resultados:
            self._mostrar_dropdown(entry, resultados)
        else:
            self._ocultar_dropdown()

    def _mostrar_dropdown(self, entry: tk.Entry,
                          resultados: list[Aeropuerto]) -> None:
        """Posiciona y rellena el dropdown bajo el campo activo."""
        self._entrada_activa = entry
        self._resultados_dropdown = resultados
        self._lista_dropdown.delete(0, "end")
        for a in resultados:
            self._lista_dropdown.insert("end", f"{a.iata}  –  {a.ciudad}, {a.pais}")
        entry.update_idletasks()
        x = entry.winfo_rootx()
        y = entry.winfo_rooty() + entry.winfo_height() + 2
        ancho = max(300, entry.winfo_width() * 5)
        alto = min(len(resultados), 7) * 20 + 6
        self._dropdown.geometry(f"{ancho}x{alto}+{x}+{y}")
        self._dropdown.deiconify()
        self._dropdown.lift()

    def _ocultar_dropdown(self) -> None:
        self._dropdown.withdraw()
        self._entrada_activa = None
        self._resultados_dropdown = []

    def _foco_a_dropdown(self) -> None:
        """Mueve el foco al dropdown si hay resultados."""
        if self._resultados_dropdown:
            self._lista_dropdown.focus_set()
            self._lista_dropdown.selection_set(0)

    def _dropdown_subir(self, evento) -> str | None:
        """Cuando el cursor sube mas alla del primer item, devuelve el foco al campo."""
        sel = self._lista_dropdown.curselection()
        if sel and sel[0] == 0 and self._entrada_activa is not None:
            self._entrada_activa.focus_set()
            return "break"  # evita que el Listbox siga procesando la tecla
        return None

    def _elegir_de_dropdown(self, _evento=None) -> None:
        """Rellena el campo activo con el aeropuerto seleccionado."""
        sel = self._lista_dropdown.curselection()
        if not sel or not self._resultados_dropdown:
            return
        aeropuerto = self._resultados_dropdown[sel[0]]
        if self._entrada_activa is not None:
            self._entrada_activa.delete(0, "end")
            self._entrada_activa.insert(0, aeropuerto.iata)
            self._entrada_activa.focus_set()
        self._ocultar_dropdown()
        self._consola(f"{aeropuerto.iata}  {aeropuerto.etiqueta} · {aeropuerto.pais}")

    # ==================================================================
    # DOMINIO: vuelo automatico
    # ==================================================================
    def _distancia_restante(self) -> float:
        """Kilometros pendientes desde la posicion actual del avion automatico."""
        if not self.vuelo_en_curso or len(self.ruta) < 2:
            return 0.0
        origen = self.ruta[self.segmento]
        destino = self.ruta[self.segmento + 1]
        tramo_km = geo.haversine(origen.lat, origen.lon, destino.lat, destino.lon)
        restante = tramo_km * (1.0 - min(1.0, self.progreso))
        for i in range(self.segmento + 1, len(self.ruta) - 1):
            restante += geo.haversine(
                self.ruta[i].lat, self.ruta[i].lon,
                self.ruta[i + 1].lat, self.ruta[i + 1].lon)
        return max(0.0, restante)

    def _velocidad_avion_kmh(self) -> float:
        """Lee el campo de velocidad del avión; devuelve 850 si el valor no es valido."""
        try:
            v = float(self.entrada_velocidad.get())
            return max(50.0, min(50_000.0, v))
        except ValueError:
            return 850.0

    def _tiempo_estimado(self, distancia_km: float) -> str:
        """Tiempo de vuelo realista a partir de distancia y velocidad configurada."""
        v = self._velocidad_avion_kmh()
        if v <= 0 or distancia_km <= 0:
            return "—"
        horas = distancia_km / v
        h = int(horas)
        m = int((horas - h) * 60)
        return f"{h} h {m:02d} min"

    def _programar_tick(self) -> None:
        if self._id_tick is not None:
            self.root.after_cancel(self._id_tick)
        self._id_tick = self.root.after(tema.MS_PASO_VUELO, self._tick)

    def _tick(self) -> None:
        """Un paso de la animacion, programado desde el bucle de eventos de Tk."""
        self._id_tick = None
        if not self.vuelo_en_curso or self.vuelo_pausado:
            return
        origen = self.ruta[self.segmento]
        destino = self.ruta[self.segmento + 1]
        tramo_km = geo.haversine(origen.lat, origen.lon, destino.lat, destino.lon)
        duracion = max(1.5, tramo_km / self._velocidad_avion_kmh())
        self.progreso += tema.MS_PASO_VUELO / 1000.0 / duracion * self.velocidad_sim

        while self.progreso >= 1.0 and self.segmento < len(self.ruta) - 2:
            self.progreso -= 1.0
            self.segmento += 1
            origen, destino = self.ruta[self.segmento], self.ruta[self.segmento + 1]

        punto = geo.interpolar((origen.lat, origen.lon), (destino.lat, destino.lon),
                               min(1.0, self.progreso))
        self.auto_lat, self.auto_lon = punto.lat, punto.lon
        rumbo = geo.rumbo_inicial(punto.lat, punto.lon, destino.lat, destino.lon)
        x, y = self.mapa.a_pantalla(punto.lat, punto.lon, repetir=True)
        self._ubicar_avion(self.avion_auto, self.area_auto, x, y, rumbo)

        self._programar_refresco()  # actualiza paneles en cada tick

        if self.progreso >= 1.0:
            self.vuelo_en_curso = False
            self.reloj_auto.pausar()
            self.registro.agregar(self._medicion_auto())
            self._activar_controles(False)
            self._consola("Vuelo automatico completado: destino alcanzado.")
            self._actualizar_paneles()
            return
        self._programar_tick()

    def _medicion_auto(self) -> Medicion:
        return Medicion(
            modo="AUTO",
            distancia_km=geo.longitud_ruta([(a.lat, a.lon) for a in self.ruta]),
            tiempo_s=self.reloj_auto.transcurrido,
            tramos=max(0, len(self.ruta) - 1),
            acciones=len(self.ruta),
            ruta=[a.iata for a in self.ruta],
        )

    # ==================================================================
    # DOMINIO: control manual
    # ==================================================================
    def _al_teclar(self, evento: tk.Event) -> str | None:
        tecla = (evento.keysym or "").lower()
        if tecla == "g":
            self.alternar_cuadricula()
            return "break"
        if tecla in TECLAS_MOVIMIENTO:
            if tecla not in self.teclas_pulsadas:
                self.acciones += 1
            self.teclas_pulsadas.add(tecla)
            if self._id_bucle_manual is None:
                self.reloj_manual.iniciar()
                self._bucle_manual()
            return "break"
        return None

    def _al_soltar_tecla(self, evento: tk.Event) -> None:
        self.teclas_pulsadas.discard((evento.keysym or "").lower())

    def _bucle_manual(self) -> None:
        """Desplazamiento continuo mientras se mantiene una tecla.

        Comparte el bucle de eventos con el vuelo automatico: no hay hilos.
        """
        self._id_bucle_manual = None
        if not self.teclas_pulsadas:
            self.reloj_manual.pausar()
            return
        dx = dy = 0.0
        for tecla in self.teclas_pulsadas:
            dx += (tecla in {"d", "right"}) - (tecla in {"a", "left"})
            dy += (tecla in {"s", "down"}) - (tecla in {"w", "up"})
        if dx or dy:
            self._desplazar_manual(dx * PASO_TECLADO_PX, dy * PASO_TECLADO_PX)
        self._id_bucle_manual = self.root.after(tema.MS_REPETICION_TECLA, self._bucle_manual)

    def _desplazar_manual(self, dx: float, dy: float) -> None:
        x, y = self.mapa.a_pantalla(self.manual_lat, self.manual_lon, repetir=True)
        grados = self.mapa.a_grados(self._acotar_al_mapa(x + dx, y + dy))
        if grados is not None:
            self._fijar_posicion_manual(grados[0], grados[1])

    def iniciar_arrastre(self, evento: tk.Event) -> None:
        """Captura el punto de agarre: sin esto el avion 'salta' al cursor."""
        x, y = self.mapa.a_pantalla(self.manual_lat, self.manual_lon, repetir=True)
        self.arrastrando = True
        self._offset_arrastre = (x - evento.x, y - evento.y)
        self.acciones += 1
        self.reloj_manual.iniciar()
        self.lienzo.configure(cursor="fleur")

    def arrastrar(self, evento: tk.Event) -> None:
        if not self.arrastrando:
            return
        objetivo = (evento.x + self._offset_arrastre[0], evento.y + self._offset_arrastre[1])
        grados = self.mapa.a_grados(self._acotar_al_mapa(*objetivo))
        if grados is not None:
            self._fijar_posicion_manual(grados[0], grados[1])

    def terminar_arrastre(self, _evento: tk.Event) -> None:
        if self.arrastrando:
            self.arrastrando = False
            self.lienzo.configure(cursor="crosshair")

    def _fijar_posicion_manual(self, lat: float, lon: float) -> None:
        lat = max(-MAX_LATITUD_MOVIL, min(MAX_LATITUD_MOVIL, lat))
        if self.manual_ultima_pos is not None:
            rumbo = geo.rumbo_inicial(self.manual_ultima_pos[0], self.manual_ultima_pos[1],
                                      lat, lon)
            diferencia = abs((rumbo - self.rumbo_manual + 180.0) % 360.0 - 180.0)
            if diferencia > 25.0:
                self.correcciones += 1
            self.rumbo_manual = rumbo
            self.distancia_manual_km += geo.haversine(
                self.manual_ultima_pos[0], self.manual_ultima_pos[1], lat, lon)
        self.manual_lat, self.manual_lon = lat, lon
        self.manual_ultima_pos = (lat, lon)
        x, y = self.mapa.a_pantalla(lat, lon, repetir=True)
        self._ubicar_avion(self.avion_manual, self.area_manual, x, y, self.rumbo_manual)
        self._programar_refresco()

    def _acotar_al_mapa(self, x: float, y: float) -> tuple[float, float]:
        """Restriccion: el avion no abandona el area geografica visible."""
        x0, y0, ancho, alto = self.mapa.rect_mapa
        return (max(x0, min(x0 + ancho, x)), max(y0, min(y0 + alto, y)))

    # ==================================================================
    # PRESENTACION: paneles y consola
    # ==================================================================
    def _medicion_manual(self) -> Medicion:
        return Medicion(modo="MANUAL", distancia_km=self.distancia_manual_km,
                        tiempo_s=self.reloj_manual.transcurrido, tramos=1,
                        acciones=self.acciones, correcciones=self.correcciones)

    def _medicion_auto_actual(self) -> Medicion:
        return Medicion(modo="AUTO",
                        distancia_km=geo.longitud_ruta([(a.lat, a.lon) for a in self.ruta]),
                        tiempo_s=self.reloj_auto.transcurrido,
                        tramos=max(0, len(self.ruta) - 1))

    def _actualizar_paneles(self) -> None:
        # --- panel de vuelo automatico --------------------------------
        distancia_total = geo.longitud_ruta([(a.lat, a.lon) for a in self.ruta])
        vel_kmh = self._velocidad_avion_kmh()
        pos_auto = f"{self.auto_lat:+.2f}°, {self.auto_lon:+.2f}°"
        if self.vuelo_en_curso and self.segmento < len(self.ruta) - 1:
            origen, destino = self.ruta[self.segmento], self.ruta[self.segmento + 1]
            tramo_txt = f"tramo       {origen.iata} → {destino.iata}\n"
            dist_rest = self._distancia_restante()
            linea_dist = (f"distancia   {geo.formatear_distancia(distancia_total)}"
                          f"  (rest. {geo.formatear_distancia(dist_rest)})\n")
            linea_tiempo = (f"tiempo est. {self._tiempo_estimado(distancia_total)}"
                            f"  (rest. {self._tiempo_estimado(dist_rest)})\n")
        else:
            tramos = max(0, len(self.ruta) - 1)
            tramo_txt = f"tramos      {tramos}\n"
            linea_dist = f"distancia   {geo.formatear_distancia(distancia_total)}\n"
            linea_tiempo = f"tiempo est. {self._tiempo_estimado(distancia_total)}\n"
        self.panel_auto["texto"].configure(text=(
            tramo_txt
            + linea_dist
            + linea_tiempo
            + f"velocidad   {vel_kmh:,.0f} km/h\n"
            + f"posicion    {pos_auto}"))

        # --- panel de control manual ----------------------------------
        hechas = self.registro.por_modo("MANUAL")
        manual = hechas[-1] if hechas else self._medicion_manual()
        grados = self.mapa.a_grados(self.mapa.a_pantalla(self.manual_lat, self.manual_lon, repetir=True))
        posicion = f"{grados[0]:+.2f}°, {grados[1]:+.2f}°" if grados else "fuera del mapa"
        self.panel_manual["texto"].configure(text=(
            f"distancia   {geo.formatear_distancia(manual.distancia_km)}\n"
            f"acciones    {self.acciones} teclas + arrastres\n"
            f"giros       {self.correcciones} correcciones de rumbo\n"
            f"posicion    {posicion}"))

    def _programar_refresco(self) -> None:
        if self._id_refresco is None:
            self._id_refresco = self.root.after(tema.MS_PASO_TELEMETRIA, self._refrescar)

    def _refrescar(self) -> None:
        self._id_refresco = None
        self._actualizar_paneles()
        if self.vuelo_en_curso or self.teclas_pulsadas or self.arrastrando:
            self._programar_refresco()

    def _activar_controles(self, volando: bool) -> None:
        self.boton_iniciar.configure(state="disabled" if volando else "normal")
        self.boton_pausar.configure(state="normal" if volando else "disabled",
                                    text="Pausar")
        hay_ruta = bool(self.ruta and len(self.ruta) >= 2)
        self.boton_reiniciar_vuelo.configure(
            state="normal" if (volando or hay_ruta) else "disabled")

    def _consola(self, mensaje: str, error: bool = False) -> None:
        self.consola.configure(text=("AVISO:  " if error else ">  ") + mensaje,
                               fg=tema.ALERTA if error else tema.TEXTO_TENUE)

    def _avisos_carga(self) -> None:
        limites = self.mapa.proyeccion.limites
        self.consola.configure(text=(
            f"{len(self.fuente.aeropuertos):,} aeropuertos  ·  "
            f"{len(self.fuente.paises)} paises  ·  "
            f"proyeccion {self.mapa.proyeccion.nombre}  ·  "
            f"distancias por haversine  ·  "
            f"mapa: {limites.lon_izq:.0f}° a {limites.lon_der:.0f}° de longitud"))
        for aviso in self.fuente.avisos:
            self._consola(aviso, error=True)

    # ==================================================================
    # PRESENTACION: ajustes del lienzo
    # ==================================================================
    def _al_redimensionar(self, evento: tk.Event) -> None:
        if abs(evento.width - self.ancho_lienzo) < 2 and abs(evento.height - self.alto_lienzo) < 2:
            return
        self.ancho_lienzo = max(640, evento.width)
        self.alto_lienzo = max(360, evento.height)
        self.mapa.encajar(self.ancho_lienzo, self.alto_lienzo, margen=8)
        self._dibujar_todo()
        self._actualizar_paneles()
