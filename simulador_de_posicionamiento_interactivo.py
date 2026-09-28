"""
Simulador de Posicionamiento Interactivo
=========================================

Practica 2 de la asignatura Interaccion Humano-Computador (UNEMI).
Comparacion entre trayectorias automaticas y control manual sobre un mapa
mundial con la posicion geografica real de los aeropuertos.

Ejecucion:
    python simulador_de_posicionamiento_interactivo.py

Este archivo es solo el punto de entrada: la logica esta en el paquete `ihc`
(geodesia, proyeccion, datos, telemetria, tema e interfaz), de modo que cada
pieza se pueda probar por separado.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from ihc.app import SimuladorMapa  # noqa: E402  (requiere el ajuste de sys.path)


def main() -> int:
    """Crea la ventana y entra al bucle de eventos. Devuelve el codigo de salida."""
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"No se pudo abrir la ventana grafica: {error}", file=sys.stderr)
        print("En Linux sin servidor grafico use un entorno con X (o ssh -X).",
              file=sys.stderr)
        return 1

    try:
        SimuladorMapa(root)
    except Exception as error:  # evita el traceback en la consola de la demo
        from tkinter import messagebox
        messagebox.showerror("Error al iniciar el simulador", str(error))
        return 1

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
