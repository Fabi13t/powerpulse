import csv
import glob
import json
import os
import re
import socket
import subprocess
import time
from datetime import datetime
from plyer import notification

RETENCION_DIAS = 30
VENTANA_TASA_SEG = 60       # la tasa se calcula con lecturas separadas al menos 60 s
UMBRAL_AHORRO = 20          # % de bateria para activar la politica de ahorro
COLUMNAS = [
    'id_registro', 'fecha', 'hora', 'porcentaje_bateria', 'cargando',
    'uso_cpu', 'tasa_descarga_min', 'tiempo_restante_seg', 'voltaje_mv',
    'consumo_w', 'capacidad_diseno_wh', 'capacidad_actual_wh',
    'ciclos_carga', 'salud_pct', 'esquema_energia',
]

ruta_appdata = os.getenv('LOCALAPPDATA')
carpeta_logs = os.path.join(ruta_appdata, 'PowerPulse', 'logs')
os.makedirs(carpeta_logs, exist_ok=True)


# ---------------------------------------------------------------- archivos CSV
def purgar_archivos_viejos():
  limite_segundos = RETENCION_DIAS * 86400
  ahora = time.time()
  archivos = glob.glob(os.path.join(carpeta_logs, 'powerpulse_*.csv'))

  for archivo in archivos:
    if (ahora - os.path.getmtime(archivo)) > limite_segundos:
      try:
        os.remove(archivo)
        print(f'[PowerPulse] Archivo purgado (>{RETENCION_DIAS} dias): {archivo}')
      except Exception as e:
        print(f'Error al eliminar {archivo}: {e}')


def contar_registros(archivo):
  if not os.path.exists(archivo):
    return 0
  with open(archivo, newline='', encoding='utf-8') as f:
    return max(sum(1 for _ in f) - 1, 0)


# ------------------------------------------- politica de energia (Control ACPI)
def ejecutar_powercfg(*args):
  """Ejecuta powercfg y devuelve (codigo, salida). None si no se puede."""
  try:
    r = subprocess.run(
        ['powercfg', *args], capture_output=True, timeout=10,
        encoding='oem' if os.name == 'nt' else 'utf-8', errors='replace',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    return r.returncode, r.stdout
  except (OSError, subprocess.SubprocessError):
    return None, ''


def esquema_activo():
  """Devuelve (guid, nombre) del plan de energia activo de Windows."""
  _, salida = ejecutar_powercfg('/getactivescheme')
  m = re.search(r'([0-9a-fA-F-]{36})\s*\((.+?)\)', salida)
  return (m.group(1), m.group(2)) if m else (None, '')


def activar_ahorro():
  """Pasa Windows a 'Ahorro de energia'. Devuelve el metodo usado o None."""
  codigo, _ = ejecutar_powercfg('/setactive', 'SCHEME_MAX')
  if codigo == 0:
    return 'plan'
  # Equipos con un solo plan: se activa el Ahorro de bateria de Windows
  codigo, _ = ejecutar_powercfg('/setdcvalueindex', 'SCHEME_CURRENT',
                                'SUB_ENERGYSAVER', 'ESBATTTHRESHOLD', '100')
  if codigo == 0:
    ejecutar_powercfg('/setactive', 'SCHEME_CURRENT')
    return 'ahorro_bateria'
  return None


def restaurar_esquema(metodo, guid_anterior):
  if metodo == 'plan' and guid_anterior:
    ejecutar_powercfg('/setactive', guid_anterior)
  elif metodo == 'ahorro_bateria':
    ejecutar_powercfg('/setdcvalueindex', 'SCHEME_CURRENT',
                      'SUB_ENERGYSAVER', 'ESBATTTHRESHOLD', '20')
    ejecutar_powercfg('/setactive', 'SCHEME_CURRENT')


def valor(dato, divisor=1, decimales=2):
  """Convierte -1 (no disponible) en celda vacia."""
  if dato is None or dato < 0:
    return ''
  return round(dato / divisor, decimales) if divisor != 1 else dato


# -------------------------------------------------------------- programa
purgar_archivos_viejos()

udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.bind(('127.0.0.1', 5005))

print('=== PowerPulse: Gestor Python Activo ===')

ultimo_registro_tiempo = 0
ultima_alerta_tiempo = 0
ultimo_cargando = None
referencia_tasa = None
tasa_descarga = 0.0
archivo_actual = None
id_registro = 0

metodo_ahorro = None
guid_anterior = None
_, nombre_esquema = esquema_activo()
ultima_consulta_esquema = time.time()

while True:
  data, addr = udp_sock.recvfrom(1024)

  try:
    datos = json.loads(data.decode('utf-8'))
    porcentaje = int(datos['bateria'])
    cargando = int(datos['cargando'])
    cpu = int(datos['uso_cpu'])
  except (ValueError, KeyError, TypeError, UnicodeDecodeError):
    print('[PowerPulse] Mensaje invalido descartado')
    continue

  tiempo_restante = datos.get('tiempo_restante_seg', -1)
  voltaje = datos.get('voltaje_mv', -1)
  consumo_mw = datos.get('consumo_mw', -1)
  cap_diseno = datos.get('cap_diseno_mwh', -1)
  cap_actual = datos.get('cap_actual_mwh', -1)
  ciclos = datos.get('ciclos', -1)

  # RF-012: salud = capacidad actual / capacidad de diseno
  salud = ''
  if cap_diseno and cap_diseno > 0 and cap_actual and cap_actual > 0:
    salud = round(cap_actual * 100 / cap_diseno, 2)

  tiempo_actual = time.time()

  # Tasa de descarga en %/min, medida en una ventana de 60 s
  if cargando:
    referencia_tasa = None
    tasa_descarga = 0.0
  elif referencia_tasa is None:
    referencia_tasa = (tiempo_actual, porcentaje)
  elif tiempo_actual - referencia_tasa[0] >= VENTANA_TASA_SEG:
    minutos = (tiempo_actual - referencia_tasa[0]) / 60.0
    tasa_descarga = round((referencia_tasa[1] - porcentaje) / minutos, 2)
    referencia_tasa = (tiempo_actual, porcentaje)

  # Politica automatica de ahorro de energia (Control ACPI)
  if not cargando and porcentaje <= UMBRAL_AHORRO and metodo_ahorro is None:
    guid_anterior, _ = esquema_activo()
    metodo_ahorro = activar_ahorro()
    if metodo_ahorro:
      print(f'[PowerPulse] Politica de ahorro ACTIVADA ({metodo_ahorro})')
      notification.notify(
          title='PowerPulse: Modo ahorro activado',
          message=f'Batería en {porcentaje}%. Se activó el ahorro de energía.',
          timeout=5,
      )
    else:
      print('[PowerPulse] No se pudo cambiar el plan de energia')
      metodo_ahorro = 'fallido'  # evita reintentar cada 2 s
    ultima_consulta_esquema = 0
  elif cargando and metodo_ahorro is not None:
    restaurar_esquema(metodo_ahorro, guid_anterior)
    print('[PowerPulse] Cargador conectado: plan de energia restaurado')
    metodo_ahorro = None
    ultima_consulta_esquema = 0

  if tiempo_actual - ultima_consulta_esquema >= 60:
    _, nombre_esquema = esquema_activo()
    ultima_consulta_esquema = tiempo_actual

  # Registro adaptativo segun el nivel de bateria
  if porcentaje <= 10:
    intervalo_log = 2
  elif porcentaje <= 20:
    intervalo_log = 15
  else:
    intervalo_log = 60

  debe_guardar = (
      tiempo_actual - ultimo_registro_tiempo >= intervalo_log
  ) or cargando != ultimo_cargando  # tambien al conectar/desconectar el cargador
  ultimo_cargando = cargando

  if debe_guardar:
    ahora = datetime.now()
    fecha_hoy = ahora.strftime('%Y-%m-%d')
    hora_actual = ahora.strftime('%H:%M:%S')

    archivo_csv = os.path.join(carpeta_logs, f'powerpulse_{fecha_hoy}.csv')
    if archivo_csv != archivo_actual:  # nuevo dia o primer arranque
      archivo_actual = archivo_csv
      id_registro = contar_registros(archivo_csv)
    existe = os.path.exists(archivo_csv)
    id_registro += 1

    consumo_w = abs(consumo_mw) / 1000 if consumo_mw not in (None, -1) else -1

    with open(archivo_csv, mode='a', newline='', encoding='utf-8') as f:
      writer = csv.writer(f)
      if not existe:
        writer.writerow(COLUMNAS)
      writer.writerow([
          id_registro, fecha_hoy, hora_actual, porcentaje, cargando, cpu,
          tasa_descarga, valor(tiempo_restante), valor(voltaje),
          valor(consumo_w) if consumo_w >= 0 else '',
          valor(cap_diseno, 1000), valor(cap_actual, 1000), valor(ciclos),
          salud, nombre_esquema,
      ])

    print(
        f'[{hora_actual}] Bat: {porcentaje}% | Cargando: {cargando} | CPU: {cpu}%'
        f' | Tasa: {tasa_descarga}%/min | Salud: {salud}% | Plan: {nombre_esquema}'
        ' -> Guardado'
    )
    ultimo_registro_tiempo = tiempo_actual

  # RF-010 y RF-011: alertas en dos niveles
  if not cargando:
    if 10 < porcentaje <= 20 and (tiempo_actual - ultima_alerta_tiempo >= 60):
      notification.notify(
          title='PowerPulse: Batería Baja',
          message=(
              f'Queda {porcentaje}%. CPU: {cpu}%. Tasa: {tasa_descarga}%/min.'
          ),
          timeout=5,
      )
      ultima_alerta_tiempo = tiempo_actual
    elif porcentaje <= 10 and (tiempo_actual - ultima_alerta_tiempo >= 10):
      notification.notify(
          title='PowerPulse: ¡BATERÍA CRÍTICA!',
          message=f'¡Peligro! Queda {porcentaje}%. CPU: {cpu}%.',
          timeout=5,
      )
      ultima_alerta_tiempo = tiempo_actual
