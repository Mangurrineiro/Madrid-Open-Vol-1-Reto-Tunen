"""
Ejecuta todos los pasos de evidencia en orden y deja el log en samples/_log_ejecucion.txt.

    python exploracion/evidencia/run_all.py            # todo (~6-8 min, SoilGrids espera 60 s entre llamadas)
    python exploracion/evidencia/run_all.py 2 3        # solo algunos pasos (0 debe haberse ejecutado antes)

Variables de entorno útiles:
    SG_PAUSE=60          pausa entre consultas REST a SoilGrids (s)
    SG_ALL_POINTS=1      consultar SoilGrids también en P2 y P4
    LBEG_DISCOVER=0      saltar el barrido de todas las capas LBEG (~350 llamadas)
    N_PROBE=0            nº de campos a sondear contra LBEG en el paso 0 (0 = todos)
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import RAW, SAMPLES  # noqa: E402

STEPS = {
    "0": "paso0_puntos.py",
    "1": "paso1_soilgrids.py",
    "2": "paso2_lbeg_bk50.py",
    "3": "paso3_bodenschaetzung.py",
    "4": "paso4_buek200.py",
    "5": "paso5_resumen.py",
}


def main() -> None:
    selected = sys.argv[1:] or list(STEPS)
    SAMPLES.mkdir(exist_ok=True)
    if not sys.argv[1:]:
        # Ejecución completa: log de llamadas nuevo. Los ficheros de evidencia se
        # sobrescriben paso a paso (si una fuente cae, se conserva lo último bueno
        # de los pasos que no se lleguen a reescribir).
        for name in ("_llamadas.csv", "_log_ejecucion.txt"):
            (SAMPLES / name).unlink(missing_ok=True)
    RAW.mkdir(exist_ok=True)
    log = (SAMPLES / "_log_ejecucion.txt").open("a", encoding="utf-8")
    failed = []
    for key in selected:
        script = STEPS[key]
        t0 = time.time()
        banner = f"\n{'#' * 100}\n# {script}\n{'#' * 100}"
        print(banner)
        log.write(banner + "\n")
        proc = subprocess.Popen([sys.executable, "-u", str(HERE / script)], cwd=HERE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            print(line, end="")
            log.write(line)
        proc.wait()
        msg = f"-> {script}: código {proc.returncode} en {time.time() - t0:.0f} s"
        print(msg)
        log.write(msg + "\n")
        if proc.returncode:
            failed.append(script)
    log.close()
    print("\nFALLOS: " + ", ".join(failed) if failed else "\nTodos los pasos OK.")
    print(f"Resultados en {SAMPLES}")


if __name__ == "__main__":
    main()
