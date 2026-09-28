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

from . import geo, tema
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
# La imagen esta generada con la MISMA proyeccion que el mapa vectorial
# (`herramientas/generar_fondo.py`), asi que su costa y la linea que dibuja
# Natural Earth caen en el mismo sitio por construccion: no hay nada que
# calibrar. Va debajo de los paises. Para ver el mismo fondo sin los colores,
# apuntar esta constante a "referencias/mapa_1800x913.png".
FONDO_MAPA = RAIZ / "referencias" / "fondo_1800x913.png"
# Cuantos reescalados se guardan a la vez. Pillow necesita entre 15 y 150 ms
# por cada uno, segun el tamano, y eso no puede ir en cada fotograma. Solo hace
# falta al cambiar el encuadre: al arrastrar el tamano no cambia y sale de la
# cache. Dos bastan para no repetir trabajo entre reencuadrar la ruta y
# seleccionar un aeropuerto, que son los dos encuadres que se usan.
FONDOS_EN_CACHE = 2
# A partir de este acercamiento la imagen de 1800 px de ancho se veria tan
# ampliada que no compensaria: se sigue con el mar plano y las costas de vector.
MAXIMO_AMPLIACION_FONDO = 2.0


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

        self.boton_iniciar = self._boton(barra, "Iniciar vuelo automático", self.iniciar_vuelo)
        self.boton_pausar = self._boton(barra, "Pausar", self.alternar_pausa, deshabilitado=True)
        self.boton_detener = self._boton(barra, "Detener", self.detener_vuelo, deshabilitado=True)
        self.boton_limpiar = self._boton(barra, "Reiniciar medición", self.reiniciar_medicion)

        self._separador(barra)
        tk.Label(barra, text="Origen", bg=tema.FONDO_PANEL, fg=tema.TEXTO_TENUE,
                 font=tema.FUENTE_PEQUENA).pack(side="left")
        self.entrada_origen = self._entrada(barra, tema.ORIGEN_POR_DEFECTO, 7)
        tk.Label(barra, text="Destino", bg=tema.FONDO_PANEL, fg=tema.TEXTO_TENUE,
                 font=tema.FUENTE_PEQUENA).pack(side="left", padx=(10, 0))
        self.entrada_destino = self._entrada(barra, "MAD", 7)
        self._boton(barra, "Planificar vuelo", self.planificar_vuelo, tipo="secundario")

        self._separador(barra)
        self._boton(barra, "Ayuda", self.mostrar_ayuda, tipo="secundario")

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
        self._boton(fila_busqueda, "Ir", self._elegir_resultado, tipo="secundario")
        self.boton_origen = self._boton(fila_busqueda, "Usar como origen",
                                        lambda: self._usar_seleccion("origen"),
                                        tipo="secundario", deshabilitado=True)
        self.boton_destino = self._boton(fila_busqueda, "Usar como destino",
                                         lambda: self._usar_seleccion("destino"),
                                         tipo="secundario", deshabilitado=True)

        self._separador(fila_busqueda)
        tk.Label(fila_busqueda, text="Vista", bg=tema.FONDO_PANEL, fg=tema.TEXTO_TENUE,
                 font=tema.FUENTE_PEQUENA).pack(side="left", padx=(0, 4))
        self.boton_reencuadrar = tk.Button(
            fila_busqueda, text="Encuadrar ruta", bg=tema.FONDO_ALT, fg=tema.TEXTO,
            activebackground=tema.BORDE, activeforeground=tema.TEXTO,
            font=tema.FUENTE_PEQUENA, relief="flat", cursor="hand2",
            command=self.reencuadrar_ruta)
        self.boton_reencuadrar.pack(side="left")

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
        self.panel_comparativa = self._panel(paneles, "COMPARATIVA DE EFICIENCIA", tema.EXITO)

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
               deshabilitado: bool = False, activo: bool = False) -> tk.Button:
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
        boton.pack(side="left", padx=3)
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
        self._dibujar_paises()
        self._dibujar_ruta()
        self._dibujar_aeropuertos()
        self._dibujar_aviones()
        self._enlazar_eventos_avion()

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
            return False
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
        """Dibuja unicamente el origen y el destino de la ruta.

        Antes se dibujaban hasta 1.171 aeropuertos grandes y el buscador anadia
        sus resultados. Cada etiqueta con halo cuesta cinco elementos del
        lienzo, asi que la decision se tomo por fluidez: con el encuadre
        automatico la vista ya se ajusta a los dos puntos de la ruta y el resto
        solo anadia elementos sin aportar informacion.
        """
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
        x, y = self.mapa.a_pantalla(punto.lat, punto.lon)
        self.avion_auto, self.area_auto = self._crear_avion(x, y, tema.AUTO, tema.AUTO, 90)
        self._texto(x, y + 16, "AUTO", tema.AUTO, tema.FUENTE_ETIQUETA, "avion")

        mx, my = self.mapa.a_pantalla(self.manual_lat, self.manual_lon)
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

    def planificar_vuelo(self) -> None:
        """Construye la ruta origen -> destino con los valores de los dos campos."""
        origen = self.fuente.buscar(self.entrada_origen.get(), 1)
        destino = self.fuente.buscar(self.entrada_destino.get(), 1)
        if not origen or not destino:
            self._consola("Aeropuerto no reconocido. Use el codigo IATA (UIO, MAD, JFK).",
                          error=True)
            return
        if origen[0].iata == destino[0].iata:
            self._consola("El origen y el destino deben ser distintos.", error=True)
            return
        self.detener_vuelo()
        self.ruta = [origen[0], destino[0]]
        self.segmento = 0
        self.progreso = 0.0
        lat, lon = geo.punto_sobre_arco(origen[0].lat, origen[0].lon, 90.0, 900.0)
        self.manual_lat, self.manual_lon = lat, lon
        self.manual_ultima_pos = (lat, lon)
        self.distancia_manual_km = 0.0
        self.acciones = 0
        self.correcciones = 0
        self.rumbo_manual = 90.0
        # El encuadre automatico ocurre al planificar: el usuario define dos
        # puntos y la vista se ajusta sola, sin rueda ni arrastre.
        escala = self.mapa.encuadrar_puntos([(a.lat, a.lon) for a in self.ruta],
                                             ESCALA_MAXIMA_AUTOMATICA)
        self._dibujar_todo()
        self._actualizar_paneles()
        distancia = geo.haversine(origen[0].lat, origen[0].lon, destino[0].lat, destino[0].lon)
        self._consola(f"Ruta planificada {origen[0].iata} → {destino[0].iata} · "
                      f"{geo.formatear_distancia(distancia)} de gran circulo · "
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
            "  Solo se dibujan el origen y el destino.\n\n"
            "OTRAS TECLAS\n"
            "  Esc  detener el vuelo        R  encuadrar la ruta\n\n"
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
        else:
            self.lista_resultados.pack_forget()
        self._dibujar_todo()
        if self.resultados:
            self._consola(f"{len(self.resultados)} coincidencias para «{texto}». "
                          f"Elija una y pulse Ir.")
        else:
            self._consola(f"Sin coincidencias para «{texto}». Pruebe el nombre de la "
                          f"ciudad, el pais o el codigo IATA.", error=True)

    def _ocultar_resultados(self) -> None:
        self.resultados = []
        self.lista_resultados.delete(0, "end")
        self.lista_resultados.pack_forget()
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
        activo = "normal" if aeropuerto else "disabled"
        self.boton_origen.configure(state=activo)
        self.boton_destino.configure(state=activo)
        # Si el aeropuerto encontrado forma parte de la ruta, se reencuadra
        # para que origen y destino queden visibles a la vez.
        if any(a.iata == aeropuerto.iata for a in self.ruta):
            self.mapa.encuadrar_puntos([(a.lat, a.lon) for a in self.ruta],
                                       ESCALA_MAXIMA_AUTOMATICA)
        self._dibujar_todo()
        self._consola(f"Aeropuerto localizado: {aeropuerto.etiqueta} · {aeropuerto.pais} "
                      f"· {aeropuerto.lat:+.3f}, {aeropuerto.lon:+.3f}")

    def _usar_seleccion(self, campo: str) -> None:
        if self.seleccionado is None:
            self._consola("Busque primero un aeropuerto.", error=True)
            return
        entrada = self.entrada_origen if campo == "origen" else self.entrada_destino
        entrada.delete(0, "end")
        entrada.insert(0, self.seleccionado.iata)
        self._consola(f"{campo.capitalize()} fijado en {self.seleccionado.iata} "
                      f"({self.seleccionado.ciudad}).")

    # ==================================================================
    # DOMINIO: vuelo automatico
    # ==================================================================
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
        duracion = max(1.5, tramo_km / 320.0)
        self.progreso += tema.MS_PASO_VUELO / 1000.0 / duracion

        while self.progreso >= 1.0 and self.segmento < len(self.ruta) - 2:
            self.progreso -= 1.0
            self.segmento += 1
            origen, destino = self.ruta[self.segmento], self.ruta[self.segmento + 1]

        punto = geo.interpolar((origen.lat, origen.lon), (destino.lat, destino.lon),
                               min(1.0, self.progreso))
        rumbo = geo.rumbo_inicial(punto.lat, punto.lon, destino.lat, destino.lon)
        x, y = self.mapa.a_pantalla(punto.lat, punto.lon)
        self._ubicar_avion(self.avion_auto, self.area_auto, x, y, rumbo)

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
        if tecla in TECLAS_MOVIMIENTO:
            if tecla not in self.teclas_pulsadas:
                self.acciones += 1
            self.teclas_pulsadas.add(tecla)
            if self._id_bucle_manual is None:
                self.reloj_manual.iniciar()
                self._bucle_manual()
            return "break"
        if tecla == "r":
            self.reencuadrar_ruta()
            return "break"
        return None

    def reencuadrar_ruta(self, anunciar: bool = True) -> None:
        """Encuadra la ruta: el zoom se calcula solo con origen y destino.

        Es el sustituto del zoom con la rueda. En lugar de que el usuario
        controle un factor, la vista se ajusta al rectangulo que contiene la
        trayectoria, de modo que los dos puntos de la ruta quedan siempre
        visibles sin tener que desplazar el mapa a mano. Con una sola parada se
        ve el mundo entero; con una ruta corta se acerca hasta el limite de
        `ESCALA_MAXIMA_AUTOMATICA`.
        """
        puntos = [(a.lat, a.lon) for a in (self.ruta[0], self.ruta[-1])] if self.ruta else []
        if not puntos:
            self.mapa.vista = TransformacionVista()
            self._dibujar_todo()
            if anunciar:
                self._consola("Sin ruta: vista general (1.00x).")
            return
        escala = self.mapa.encuadrar_puntos(puntos, ESCALA_MAXIMA_AUTOMATICA)
        self._dibujar_todo()
        if anunciar:
            orientes = " y ".join(a.iata for a in (self.ruta[0], self.ruta[-1]))
            self._consola(f"Ruta {orientes} encuadrada automaticamente "
                          f"(acercamiento {escala:.2f}x).")

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
        x, y = self.mapa.a_pantalla(self.manual_lat, self.manual_lon)
        grados = self.mapa.a_grados(self._acotar_al_mapa(x + dx, y + dy))
        if grados is not None:
            self._fijar_posicion_manual(grados[0], grados[1])

    def iniciar_arrastre(self, evento: tk.Event) -> None:
        """Captura el punto de agarre: sin esto el avion 'salta' al cursor."""
        x, y = self.mapa.a_pantalla(self.manual_lat, self.manual_lon)
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
        x, y = self.mapa.a_pantalla(lat, lon)
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
        completadas = self.registro.por_modo("AUTO")
        auto = completadas[-1] if completadas else self._medicion_auto_actual()
        tramo_actual = ""
        if self.vuelo_en_curso and self.segmento < len(self.ruta) - 1:
            origen, destino = self.ruta[self.segmento], self.ruta[self.segmento + 1]
            tramo_actual = f"tramo       {origen.iata} → {destino.iata}\n"
        else:
            tramo_actual = f"tramos      {auto.tramos}\n"
        self.panel_auto["texto"].configure(text=(
            tramo_actual
            + f"distancia   {geo.formatear_distancia(auto.distancia_km)}\n"
            + f"tiempo      {auto.duracion()}\n"
            + f"velocidad   {auto.velocidad_kmh:,.0f} km/h"))

        hechas = self.registro.por_modo("MANUAL")
        manual = hechas[-1] if hechas else self._medicion_manual()
        grados = self.mapa.a_grados(self.mapa.a_pantalla(self.manual_lat, self.manual_lon))
        posicion = f"{grados[0]:+.2f}°, {grados[1]:+.2f}°" if grados else "fuera del mapa"
        self.panel_manual["texto"].configure(text=(
            f"distancia   {geo.formatear_distancia(manual.distancia_km)}\n"
            f"tiempo      {manual.duracion()}\n"
            f"acciones    {self.acciones} teclas + arrastres\n"
            f"giros       {self.correcciones} correcciones de rumbo\n"
            f"posicion    {posicion}"))

        comparativa = self.registro.comparativa()
        if comparativa:
            self.panel_comparativa["texto"].configure(text=(
                f"auto        {comparativa['auto_s_por_1000km']:.2f} s por 1000 km\n"
                f"manual      {comparativa['manual_s_por_1000km']:.2f} s por 1000 km\n"
                f"manual es {comparativa['manual_es_x_mas_lento']:.1f} veces mas lento\n"
                f"ventaja automatica: {comparativa['ventaja_automatica_pct']:.0f} %"))
        else:
            self.panel_comparativa["texto"].configure(text=(
                "Se requiere una ejecucion de cada modo\n"
                "para comparar la eficiencia (s / 1000 km)."))

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
        self.boton_detener.configure(state="normal" if volando else "disabled")

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
