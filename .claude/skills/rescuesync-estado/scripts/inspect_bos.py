"""Resume el estado del modelo Bonita dentro de un .bos sin abrir Studio.

Uso: python inspect_bos.py [ruta al .bos]   (default: entrega-2/RescueSync.bos)
Solo lectura. La raiz interna del zip cambia (entrega4/, entrega41/...), asi que
se busca por sufijo en vez de hardcodear el nombre.
"""
import re
import sys
import zipfile
import xml.dom.minidom as minidom

path = sys.argv[1] if len(sys.argv) > 1 else "entrega-2/RescueSync.bos"
z = zipfile.ZipFile(path)
names = z.namelist()
proc = next(n for n in names if n.endswith(".proc"))
raw = z.read(proc).decode("utf8", "replace")
pretty = minidom.parseString(z.read(proc)).toprettyxml(indent=" ")

print("archivo:", path)
print("contenido app/:", [n.split("/app/")[1] for n in names if "/app/" in n and not n.endswith("/")])

start = re.findall(r'xmi:type="(process:[A-Za-z]*Start[A-Za-z]*)"[^>]*name="([^"]*)"', raw)
print("start event:", start)

datas = re.findall(r'<data [^>]*name="([^"]*)"', raw)
print(f"variables ({len(datas)}):", datas)
bound = re.findall(r'<data [^>]*name="([^"]*)"[^>]*>\s*<defaultValue[^>]*type="TYPE_CONTRACT_INPUT"', raw)
print("  atadas a input de contrato:", bound)

print("inputs del contrato del pool:", re.findall(r'<inputs [^>]*name="([^"]*)"', raw))

timer = re.findall(r'BoundaryTimerEvent[^>]*name="([^"]*)".*?<condition [^>]*content="([^"]*)"', raw, re.S)
print("timer:", timer)

print("actores del proceso:", re.findall(r'<actors [^>]*name="([^"]*)"', raw))
print("lanes:", re.findall(r'xmi:type="process:Lane"[^>]*name="([^"]*)"', raw))

targets = re.findall(r'<targetForm [^>]*content="([^"]*)"', raw)
print(f"form mappings: {len(targets)} total, {sum(1 for t in targets if t)} con destino (resto vacios)")

for org in [n for n in names if "/organizations/" in n and n.endswith(".xml")]:
    o = z.read(org).decode("utf8", "replace")
    print("organizacion", org.split("/")[-1], "| usuarios:", o.count("<user "),
          "| grupos:", re.findall(r'<group name="([^"]*)"', o))
