"""Hook SessionStart: le da a Claude la rama, el último commit y cómo está la rama respecto de `origin/dev`."""
import subprocess


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


rama = git("rev-parse", "--abbrev-ref", "HEAD") or "?"
ultimo = git("log", "-1", "--format=%h %s (%cr)") or "?"
cuentas = git("rev-list", "--left-right", "--count", "origin/dev...HEAD").split()
relacion = f"{cuentas[1]} adelante y {cuentas[0]} atrás de origin/dev" if len(cuentas) == 2 else "sin datos de origin/dev"
cambios = len([l for l in git("status", "--porcelain").splitlines() if l.strip()])
print(f"RescueSync · rama {rama} ({relacion}) · último commit: {ultimo} · archivos con cambios: {cambios}. "
      "Para orientarte, usá el skill rescuesync-estado.")
