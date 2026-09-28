"""
muestra_basica_profesor.py - Codigo base entregado por el docente.

Se conserva SIN MODIFICAR como linea base de la practica: sirve para
documentar el punto de partida y, sobre todo, los defectos que se corrigieron
en la version 2 (simulador_de_posicionamiento_interactivo.py + paquete ihc):

  1. `threading.Thread` pinta sobre el lienzo y sobre los Label desde un hilo
     secundario. Tk no es seguro entre hilos: produce TclError intermitentes y
     bloqueos de la interfaz. Aqui se sustituye por `root.after()`.
  2. La distancia del vuelo automatico se acumulaba como
     `dist_total_auto += dist/100`, es decir, sumando distancias parciales al
     ORIGEN y dividiendo entre 100: la cifra no correspondia al tramo recorrido.
  3. `self.distancia()` era la distancia en pixeles del lienzo multiplicada por
     0.621. No era una distancia geografica: dependia del tamano de la ventana,
     de modo que el mismo vuelo media distinto en cada computadora.
  4. El arrastre (`drag`) asignaba `event.x, event.y` como nueva posicion del
     avion, sin conservar el punto de agarre: el avion saltaba al pulsar.
  5. `imagen.png` (1800x913) se redimensionaba a 1000x507, deformando el mapa.
  6. Las coordenadas de los paises eran pixeles inventados, sin relacion con la
     geografia real ni con la imagen de fondo.
  7. No existian pausa, detencion ni reinicio de la medicion, por lo que no se
     podia repetir la prueba ni comparar dos ejecuciones.
  8. Automatico y manual se distinguian solo por el color (accesibilidad).
  9. `root.mainloop()` sin `if __name__ == "__main__"`, sin manejo de errores y
     sin redimensionado de ventana.

Este archivo no se ejecuta en la entrega: es material de analisis.
"""

import tkinter as tk
import math
import time
import threading
import os
from PIL import Image, ImageTk

# 🎨 COLORES
COLOR_FONDO = "#020617"
COLOR_GRID = "#1e293b"
COLOR_RUTA = "#00f5ff"
COLOR_PUNTO = "#ffcc00"
COLOR_TEXTO = "#ffffff"
COLOR_AUTO = "#ff2d55"
COLOR_MANUAL = "#22c55e"

class SimuladorMapa:

    def __init__(self, root):
        self.root = root
        self.root.title("✈ Simulador Aéreo (Auto vs Manual)")

        ancho = 1000
        alto = min(600, root.winfo_screenheight() - 220)

        base_dir = os.path.dirname(os.path.abspath(__file__))
        ruta_imagen = os.path.join(base_dir, "imagen.png")

        if os.path.exists(ruta_imagen):
            img = Image.open(ruta_imagen).resize((ancho, alto))
        else:
            img = Image.new("RGB", (ancho, alto), COLOR_FONDO)

        self.bg = ImageTk.PhotoImage(img)

        self.canvas = tk.Canvas(root, width=ancho, height=alto, bg=COLOR_FONDO)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.bg)

        self.dibujar_cuadricula()

        # 🌍 Países
        self.paises = {
            "Ecuador": (200, 300),
            "Colombia": (220, 220),
            "Perú": (200, 380),
            "Brasil": (400, 350),
            "USA": (300, 100),
            "España": (650, 180),
            "Japón": (900, 220)
        }

        self.dibujar_paises()

        # ✈ Aviones
        x, y = self.paises["Ecuador"]

        self.avion_auto = self.crear_avion(x, y, COLOR_AUTO)
        self.avion_manual = self.crear_avion(x+30, y+30, COLOR_MANUAL)

        # 📊 Variables AUTO
        self.dist_total_auto = 0
        self.tiempo_inicio = None

        # 📊 Variables MANUAL
        self.dist_total_manual = 0
        self.last_manual_pos = (x+30, y+30)

        # 🧾 Paneles
        frame = tk.Frame(root, bg=COLOR_FONDO)
        frame.pack()

        self.label_auto = tk.Label(frame, fg="white", bg=COLOR_FONDO,
                                   font=("Consolas", 10, "bold"), justify="left")
        self.label_auto.grid(row=0, column=0, padx=20)

        self.label_manual = tk.Label(frame, fg="white", bg=COLOR_FONDO,
                                     font=("Consolas", 10, "bold"), justify="left")
        self.label_manual.grid(row=0, column=1, padx=20)

        tk.Button(root, text="Iniciar Vuelo Automático", command=self.iniciar_vuelo).pack()

        # 🎮 Controles
        root.bind("<w>", self.mover_manual)
        root.bind("<s>", self.mover_manual)
        root.bind("<a>", self.mover_manual)
        root.bind("<d>", self.mover_manual)

        self.canvas.tag_bind(self.avion_manual, "<ButtonPress-1>", self.start_drag)
        self.canvas.tag_bind(self.avion_manual, "<B1-Motion>", self.drag)
        self.canvas.tag_bind(self.avion_manual, "<ButtonRelease-1>", self.stop_drag)

        self.dragging = False

    def crear_avion(self, x, y, color):
        return self.canvas.create_polygon(
            x, y-10,
            x-8, y+10,
            x, y+5,
            x+8, y+10,
            fill=color, outline="white", width=2
        )

    def dibujar_cuadricula(self):
        h = int(self.canvas["height"])
        for i in range(0, 1000, 50):
            self.canvas.create_line(i, 0, i, h, fill=COLOR_GRID)
        for j in range(0, h, 50):
            self.canvas.create_line(0, j, 1000, j, fill=COLOR_GRID)

    def dibujar_paises(self):
        for n, (x, y) in self.paises.items():
            self.canvas.create_oval(x-6, y-6, x+6, y+6,
                                    fill=COLOR_PUNTO, outline="white")
            self.canvas.create_text(x, y-12, text=n,
                                    fill="white", font=("Arial", 10, "bold"))

    def distancia(self, x1, y1, x2, y2):
        return math.sqrt((x2-x1)**2 + (y2-y1)**2) * 0.621

    # ✈ AUTOMÁTICO
    def iniciar_vuelo(self):
        self.tiempo_inicio = time.time()
        threading.Thread(target=self.viajar).start()

    def viajar(self):
        ruta = list(self.paises.keys())

        for i in range(len(ruta)-1):
            o = ruta[i]
            d = ruta[i+1]

            x1, y1 = self.paises[o]
            x2, y2 = self.paises[d]

            self.canvas.create_line(x1, y1, x2, y2,
                                    fill=COLOR_RUTA, width=4)

            for t in range(100):
                nx = x1 + (x2-x1)*t/100
                ny = y1 + (y2-y1)*t/100

                self.canvas.coords(self.avion_auto,
                                   nx, ny-10,
                                   nx-8, ny+10,
                                   nx, ny+5,
                                   nx+8, ny+10)

                dist = self.distancia(x1, y1, nx, ny)
                self.dist_total_auto += dist/100
                tiempo = time.time() - self.tiempo_inicio

                self.label_auto.config(
                    text=f"""
✈ AUTOMÁTICO
{ o } → { d }

📏 {dist:.2f} mi
🌍 Total: {self.dist_total_auto:.2f}
⏱ {tiempo:.2f}s
"""
                )

                time.sleep(0.03)

    # 🎮 MANUAL
    def mover_manual(self, event):
        dx, dy = 0, 0
        paso = 10

        if event.keysym == "w": dy = -paso
        if event.keysym == "s": dy = paso
        if event.keysym == "a": dx = -paso
        if event.keysym == "d": dx = paso

        self.canvas.move(self.avion_manual, dx, dy)
        self.actualizar_manual()

    def start_drag(self, event):
        self.dragging = True

    def drag(self, event):
        if not self.dragging:
            return

        x, y = event.x, event.y

        self.canvas.coords(self.avion_manual,
                           x, y-10,
                           x-8, y+10,
                           x, y+5,
                           x+8, y+10)

        self.actualizar_manual()

    def stop_drag(self, event):
        self.dragging = False

    def actualizar_manual(self):
        coords = self.canvas.coords(self.avion_manual)
        x, y = coords[0], coords[1]

        lx, ly = self.last_manual_pos

        dist = self.distancia(lx, ly, x, y)
        self.dist_total_manual += dist

        self.last_manual_pos = (x, y)

        self.label_manual.config(
            text=f"""
🎮 MANUAL

📏 Movimiento: {dist:.2f} mi
🌍 Total: {self.dist_total_manual:.2f}
📍 Pos: ({int(x)}, {int(y)})
"""
        )

# 🚀 RUN
root = tk.Tk()
app = SimuladorMapa(root)
root.mainloop()
