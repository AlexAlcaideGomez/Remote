"""Prueba el asistente escribiendo en vez de llamar.

    python simular_llamada.py

Tú haces de cliente. Al terminar, la llamada aparece resumida en el panel.
"""

import uuid

from app import db
from app.asistente import responder
from app.config import ajustes
from app.main import procesar_fin_de_llamada

NUMERO_PRUEBA = "+34600000000"


def main() -> None:
    db.iniciar()
    call_sid = f"SIM-{uuid.uuid4().hex[:12]}"
    db.crear_llamada(call_sid, NUMERO_PRUEBA)
    db.anadir_turno(call_sid, "asistente", ajustes.texto_saludo)
    print(f"\nAsistente: {ajustes.texto_saludo}")
    print("(Escribe lo que diría el cliente. Línea vacía o Ctrl+C para colgar.)\n")
    try:
        while True:
            dicho = input("Cliente: ").strip()
            if not dicho:
                break
            turnos = db.anadir_turno(call_sid, "cliente", dicho)
            respuesta = responder(turnos, NUMERO_PRUEBA)
            db.anadir_turno(call_sid, "asistente", respuesta.texto)
            print(f"Asistente: {respuesta.texto}\n")
            if respuesta.colgar:
                print("(El asistente cuelga.)")
                break
    except (KeyboardInterrupt, EOFError):
        print("\n(Cuelgas.)")

    print("Resumiendo...")
    procesar_fin_de_llamada(call_sid)
    resumen = db.obtener(call_sid)["resumen"]
    print("\n--- Así aparecerá en el panel ---")
    for clave, valor in resumen.items():
        print(f"{clave}: {valor}")


if __name__ == "__main__":
    main()
