"""
capturar_evidencia.py - Genera las capturas tecnicas del manual.

El entorno tiene una pantalla virtual sin compositor: `import`, `xwd` y
`ImageGrab` devuelven negro, porque el root no refleja lo que Tk pinta. La
salida fiable es `canvas.postscript`, que el propio Tk genera en PostScript y
que ademas incluye la imagen del mapa. Despues ghostscript lo rasteriza a PNG.

Lo que se captura es el lienzo del mapa (mapa, rutas, aviones, etiquetas), que
es justamente la evidencia tecnica que pide el manual. Los paneles de texto se
documentan aparte, con su contenido textual.

Uso:
    python herramientas/capturar_evidencia.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from ihc.app import SimuladorMapa  # noqa: E402
from ihc.proyeccion import TransformacionVista  # noqa: E402

SALIDA = RAIZ / "capturas"
TMP = Path("/tmp/opencode/_evidencia")


def eventsimple(**campos):
    """tk.Event no admite keyword en este interprete; los manejadores de la
    app solo leen atributos, asi que basta un objeto con esos campos."""
    class _Evento:
        def __init__(self, **kw):
            self.__dict__.update(campos)
            self.__dict__.update(kw)
    return _Evento(**campos)


def pump(root: tk.Misc, veces: int = 3, pausa: float = 0.05) -> None:
    for _ in range(veces):
        root.update_idletasks()
        root.update()
        time.sleep(pausa)


def capturar(lienzo: tk.Canvas, root: tk.Misc, nombre: str, escala: int = 96) -> Path:
    """PostScript del lienzo -> PNG con ghostscript."""
    TMP.mkdir(parents=True, exist_ok=True)
    SALIDA.mkdir(exist_ok=True)
    eps = TMP / f"{nombre}.eps"
    png = SALIDA / f"{nombre}.png"

    print(f"  -> {nombre}")
    lienzo.postscript(file=str(eps), colormode="color", x=0, y=0,
                      width=lienzo.winfo_width(), height=lienzo.winfo_height())
    # Si ghostscript se queda colgado, no se pierde la sesion entera.
    try:
        subprocess.run(
            ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=png16m",
             f"-r{escala}", "-dEPSCrop", f"-sOutputFile={png}", str(eps)],
            check=True, capture_output=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        print(f"     {nombre}: ghostscript supero 60 s, se omite")
        return png
    print(f"  {png.name:34} {png.stat().st_size / 1024:6.1f} KB")
    return png


def main() -> int:
    if not shutil.which("gs"):
        print("Se necesita ghostscript (gs) para rasterizar el PostScript.", file=sys.stderr)
        return 1

    root = tk.Tk()
    root.title("Simulador de Posicionamiento de Aeronaves")
    root.geometry("1360x760+0+0")
    app = SimuladorMapa(root)
    pump(root, veces=6)
    lienzo = app.lienzo
    print(f"Lienzo: {lienzo.winfo_width()} x {lienzo.winfo_height()} px")
    print(f"Aeropuertos cargados: {len(app.fuente.aeropuertos)}  |  "
          f"Paises: {len(app.fuente.paises)}")

    print("\nCapturas:")
    capturar(lienzo, root, "01_mapa_inicial")

    # Ruta manual UIO -> MAD, con el avion manual fuera del origen.
    app.entrada_origen.delete(0, "end")
    app.entrada_origen.insert(0, "UIO")
    app.entrada_destino.delete(0, "end")
    app.entrada_destino.insert(0, "MAD")
    app.planificar_vuelo()
    pump(root)
    capturar(lienzo, root, "02_ruta_uio_mad")

    # Ruta multi-tramo de demostracion (gran circulo largo).
    app.entrada_destino.delete(0, "end")
    app.entrada_destino.insert(0, "SYD")
    app.planificar_vuelo()
    pump(root)
    print(f"  Ruta Quito-Sydney: {[a.iata for a in app.ruta]}")
    capturar(lienzo, root, "03_ruta_gran_circulo_uio_syd")

    # Avion en vuelo, a mitad del tramo.
    app.entrada_destino.delete(0, "end")
    app.entrada_destino.insert(0, "MAD")
    app.planificar_vuelo()
    app.iniciar_vuelo()
    for _ in range(120):
        pump(root, veces=1, pausa=0.02)
    capturar(lienzo, root, "04_vuelo_en_curso")
    print(f"  Vuelo en curso: tramo {app.segmento + 1}/{len(app.ruta) - 1}, "
          f"progreso {app.progreso:.0%}")
    app.detener_vuelo()
    pump(root)

    # Movimiento con teclado: W A S D desplaza el avion y suma acciones.
    antes_acc, antes_km = app.acciones, app.distancia_manual_km
    antes_pos = (app.manual_lat, app.manual_lon)
    for _ in range(40):
        app._al_teclar(eventsimple(keysym="d", x=0, y=0, state=0))
        pump(root, veces=1, pausa=0.01)
        app._al_soltar_tecla(eventsimple(keysym="d", x=0, y=0, state=0))
    print(f"  Teclado: {app.acciones - antes_acc} acciones, "
          f"({antes_pos[0]:+.2f},{antes_pos[1]:+.2f}) -> "
          f"({app.manual_lat:+.2f},{app.manual_lon:+.2f}), "
          f"{app.distancia_manual_km - antes_km:,.0f} km, "
          f"rumbo {app.rumbo_manual:.0f} grados, correcciones {app.correcciones}")
    capturar(lienzo, root, "05_control_teclado")

    # Arrastre con el puntero: tag_bind <B1-Motion>, el comando exigido por la guia.
    for _ in range(30):
        app._al_teclar(eventsimple(keysym="a", x=0, y=0, state=0))
        pump(root, veces=1, pausa=0.01)
        app._al_soltar_tecla(eventsimple(keysym="a", x=0, y=0, state=0))
    x, y = app.mapa.a_pantalla(app.manual_lat, app.manual_lon)
    app.iniciar_arrastre(eventsimple(x=x - 60, y=y - 45))
    for k in range(1, 41):
        app.arrastrar(eventsimple(x=x - 60 + k * 4, y=y - 45 + k * 2))
    app.terminar_arrastre(eventsimple(x=x + 100, y=y + 35))
    pump(root)
    print(f"  Tras el arrastre: avion en "
          f"({app.manual_lat:+.3f}, {app.manual_lon:+.3f}), "
          f"{app.acciones} acciones, {app.distancia_manual_km:,.0f} km")
    capturar(lienzo, root, "06_control_manual")

    # Encuadre automatico: la ruta sola determina la escala y el desplazamiento.
    app.entrada_origen.delete(0, "end")
    app.entrada_origen.insert(0, "UIO")
    app.entrada_destino.delete(0, "end")
    app.entrada_destino.insert(0, "MAD")
    app.planificar_vuelo()
    pump(root)
    for etiqueta, aeropuerto in (("origen", app.ruta[0]), ("destino", app.ruta[-1])):
        x, y = app.mapa.a_pantalla(aeropuerto.lat, aeropuerto.lon, repetir=True)
        print(f"  {etiqueta} {aeropuerto.iata} en pantalla ({x:.0f}, {y:.0f}) "
              f"dentro: {0 <= x <= lienzo.winfo_width() and 0 <= y <= lienzo.winfo_height()}")
    print(f"  Encuadre automatico: {app.mapa.vista.escala:.2f}x | "
          f"aeropuertos dibujados {len(app._aeropuertos_visibles())}")
    capturar(lienzo, root, "07_encuadre_automatico")

    # Buscador: localizar un aeropuerto y centrar la vista en el.
    app.entrada_busqueda.delete(0, "end")
    app.entrada_busqueda.insert(0, "Japon")
    app._buscar()
    pump(root)
    print(f"  Buscador «Japon»: {len(app.resultados)} resultados -> "
          + ", ".join(a.iata for a in app.resultados[:5]))
    app.seleccionar_aeropuerto(app.resultados[0])
    pump(root)
    elegido = app.seleccionado
    print(f"  Localizado {elegido.iata} {elegido.ciudad} en "
          f"{elegido.lat:+.3f}, {elegido.lon:+.3f} | items {len(lienzo.find_all())}")
    capturar(lienzo, root, "10_buscador_localizado")
    app._ocultar_resultados()
    pump(root)

    # Vista global de la ruta. Antes esta captura era una comparativa entre el
    # encuadre automatico y el zoom manual, pero el zoom manual ya no existe y
    # ademas las medidas se inventaban: solo se capturaba el lienzo, asi que
    # los paneles no aparecian en la imagen. Esta evidencia si se ve, y sirve
    # para explicar por que la trayectoria se ve curva en una proyeccion
    # cilindrica: el arco de gran circulo se dibuja como tal, no como la recta
    # que uniria los dos puntos en la imagen.
    app.entrada_origen.delete(0, "end")
    app.entrada_origen.insert(0, "UIO")
    app.entrada_destino.delete(0, "end")
    app.entrada_destino.insert(0, "MAD")
    app.planificar_vuelo()
    pump(root)
    app.mapa.vista = TransformacionVista()
    app._dibujar_todo()
    pump(root)
    print(f"  Vista global: escala {app.mapa.vista.escala:.2f}x | "
          f"items {len(lienzo.find_all())} | "
          f"aeropuertos dibujados {len(lienzo.find_withtag('aeropuerto')) // 6} | "
          f"paises {len(lienzo.find_withtag('paises'))}")
    capturar(lienzo, root, "08_vista_global_de_la_ruta")

    # Ventana maximizada: comprobar que el mapa escala sin deformarse.
    app.reencuadrar_ruta(anunciar=False)
    root.geometry("1500x880+0+0")
    pump(root, veces=8, pausa=0.08)
    print(f"  Redimensionado: lienzo {lienzo.winfo_width()} x {lienzo.winfo_height()} px, "
          f"px/grado {lienzo.winfo_width() / app.mapa.proyeccion.limites.ancho:.3f}, "
          f"escala {app.mapa.vista.escala:.2f}x, "
          f"items {len(lienzo.find_all())}")
    capturar(lienzo, root, "09_redimensionado")

    root.destroy()
    print(f"\nListo: {len(list(SALIDA.glob('*.png')))} capturas en {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
