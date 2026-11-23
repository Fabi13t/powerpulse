import csv
import glob
import json
import os
import re
import socket
import subprocess
import time
from datetime import datetime, timedelta
from plyer import notification

RETENCION_DIAS = 30
VENTANA_TASA_SEG = 60       # la tasa se calcula con lecturas separadas al menos 60 s
UMBRAL_AHORRO = 20          # % de bateria para activar la politica de ahorro
UMBRAL_CPU = 90             # % de CPU sostenido 30 s para registrar 'CPU alta'
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
  archivos = (glob.glob(os.path.join(carpeta_logs, 'powerpulse_*.csv'))
              + glob.glob(os.path.join(carpeta_logs, 'alertas_*.csv')))

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
  try:
    with open(archivo, newline='', encoding='utf-8', errors='replace') as f:
      return max(sum(1 for _ in f) - 1, 0)  # sin contar la cabecera
  except PermissionError:
    return 0  # archivo bloqueado (p. ej. abierto en Excel)


def ultimo_registro_guardado():
  """Fecha y hora del ultimo registro del CSV mas reciente (para saber cuanto estuvo detenido)."""
  archivos = sorted(glob.glob(os.path.join(carpeta_logs, 'powerpulse_*.csv')))
  if not archivos:
    return None
  try:
    with open(archivos[-1], newline='', encoding='utf-8', errors='replace') as f:
      filas = list(csv.reader(f))
    return datetime.strptime(f'{filas[-1][1]} {filas[-1][2]}', '%Y-%m-%d %H:%M:%S')
  except (OSError, IndexError, ValueError):
    return None


# -------------------------------------------------- historial de alertas (RF-014)
COLUMNAS_ALERTA = ['id_evento', 'fecha', 'hora', 'tipo', 'descripcion', 'nivel']


def registrar_alerta(tipo, descripcion, nivel):
  """Guarda un evento en alertas_AAAA-MM-DD.csv (tabla EVENTO_ALERTA)."""
  ahora = datetime.now()
  archivo = os.path.join(carpeta_logs, f'alertas_{ahora:%Y-%m-%d}.csv')
  existe = os.path.exists(archivo)
  id_evento = contar_registros(archivo) + 1
  try:
    with open(archivo, mode='a', newline='', encoding='utf-8') as f:
      writer = csv.writer(f)
      if not existe:
        writer.writerow(COLUMNAS_ALERTA)
      writer.writerow([id_evento, f'{ahora:%Y-%m-%d}', f'{ahora:%H:%M:%S}',
                       tipo, descripcion, nivel])
  except PermissionError:
    print('[PowerPulse] Archivo de alertas en uso; el evento no se pudo guardar.')


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
udp_sock.settimeout(1)  # revisa cada segundo si el recolector sigue enviando datos
LIMITE_SIN_DATOS = 10   # s sin mensajes = corte de conexion con el recolector

print('=== PowerPulse: Gestor Python Activo ===')

# Evento de inicio: indica desde cuando no se guardaban datos (equipo apagado o sistema detenido)
anterior = ultimo_registro_guardado()
if anterior and datetime.now() - anterior > timedelta(minutes=5):
  registrar_alerta('Sistema', f'Monitoreo iniciado (sin datos desde {anterior:%d/%m %H:%M})', 'Info')
else:
  registrar_alerta('Sistema', 'Monitoreo iniciado', 'Info')

ultimo_registro_tiempo = 0
ultima_alerta_tiempo = 0
ultimo_cargando = None
referencia_tasa = None  # (tiempo, porcentaje)
tasa_descarga = 0.0
archivo_actual = None
pendientes = []        # registros que no se pudieron escribir (CSV bloqueado)
id_registro = 0

carga_completa_avisada = False
cpu_alta_desde = None   # momento en que la CPU paso del umbral
ultima_alerta_cpu = 0

ultimo_mensaje = None   # momento del ultimo mensaje recibido
corte_registrado = False

metodo_ahorro = None    # None = politica inactiva
guid_anterior = None
_, nombre_esquema = esquema_activo()
ultima_consulta_esquema = time.time()

while True:
  # Deteccion de corte: el recolector deja de enviar (se cerro, fallo o el equipo se suspendio)
  try:
    data, addr = udp_sock.recvfrom(1024)
  except socket.timeout:
    if (ultimo_mensaje is not None and not corte_registrado
        and time.time() - ultimo_mensaje >= LIMITE_SIN_DATOS):
      print('[PowerPulse] Sin datos del recolector: conexion interrumpida')
      registrar_alerta('Conexión', 'Corte de conexión: el recolector dejó de enviar datos', 'Alta')
      corte_registrado = True
    continue

  pausa = time.time() - ultimo_mensaje if ultimo_mensaje is not None else 0
  if corte_registrado or pausa >= LIMITE_SIN_DATOS:  # vuelven los datos (o el equipo desperto)
    if not corte_registrado:  # p. ej. suspension: no hubo tiempo de detectar el corte
      registrar_alerta('Conexión', 'Corte de conexión: el recolector dejó de enviar datos', 'Alta')
    duracion = f'{pausa:.0f} s' if pausa < 60 else f'{pausa / 60:.0f} min'
    registrar_alerta('Conexión', f'Conexión restablecida tras {duracion} sin datos', 'Info')
    print('[PowerPulse] Conexion con el recolector restablecida')
    corte_registrado = False
  ultimo_mensaje = time.time()

  # RF-009: validar el JSON; si es invalido se descarta sin detener el servicio
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
      registrar_alerta('Cambio de esquema',
                       f'Modo ahorro activado (batería {porcentaje}%)', 'Info')
    else:
      print('[PowerPulse] No se pudo cambiar el plan de energia')
      metodo_ahorro = 'fallido'  # evita reintentar cada 2 s
      registrar_alerta('Error de política',
                       'No se pudo cambiar el plan de energía', 'Alta')
    ultima_consulta_esquema = 0
  elif cargando and metodo_ahorro is not None:
    restaurar_esquema(metodo_ahorro, guid_anterior)
    print('[PowerPulse] Cargador conectado: plan de energia restaurado')
    if metodo_ahorro != 'fallido':
      registrar_alerta('Cambio de esquema', 'Plan de energía restaurado', 'Info')
    metodo_ahorro = None
    ultima_consulta_esquema = 0

  if tiempo_actual - ultima_consulta_esquema >= 60:
    _, nombre_esquema = esquema_activo()
    ultima_consulta_esquema = tiempo_actual

  # RF-014: eventos del sistema para el historial (solo se registran, sin notificacion)
  if ultimo_cargando is not None and cargando != ultimo_cargando:
    if cargando:
      registrar_alerta('Cargador', f'Cargador conectado (batería {porcentaje}%)', 'Info')
    else:
      registrar_alerta('Cargador', f'Cargador desconectado (batería {porcentaje}%)', 'Info')

  if cargando and porcentaje >= 100 and not carga_completa_avisada:
    registrar_alerta('Carga completa', 'Batería al 100 %: puede desconectar el cargador', 'Info')
    carga_completa_avisada = True
  elif porcentaje < 95:
    carga_completa_avisada = False

  if cpu >= UMBRAL_CPU:
    if cpu_alta_desde is None:
      cpu_alta_desde = tiempo_actual
    elif (tiempo_actual - cpu_alta_desde >= 30
          and tiempo_actual - ultima_alerta_cpu >= 300):
      registrar_alerta('CPU alta', f'Uso de CPU al {cpu}% durante más de 30 s', 'Media')
      ultima_alerta_cpu = tiempo_actual
  else:
    cpu_alta_desde = None

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
    id_registro += 1

    consumo_w = abs(consumo_mw) / 1000 if consumo_mw not in (None, -1) else -1

    # BUG-001: si el CSV esta abierto en Excel, el registro queda en memoria (pendientes)
    # y se escribe en cuanto el archivo se libere, asi no se pierden datos
    pendientes.append((archivo_csv, [
        id_registro, fecha_hoy, hora_actual, porcentaje, cargando, cpu,
        tasa_descarga, valor(tiempo_restante), valor(voltaje),
        valor(consumo_w) if consumo_w >= 0 else '',
        valor(cap_diseno, 1000), valor(cap_actual, 1000), valor(ciclos),
        salud, nombre_esquema,
    ]))
    while pendientes:
      destino, fila = pendientes[0]
      try:
        existe = os.path.exists(destino)
        with open(destino, mode='a', newline='', encoding='utf-8') as f:
          writer = csv.writer(f)
          if not existe:
            writer.writerow(COLUMNAS)
          writer.writerow(fila)
        pendientes.pop(0)
      except PermissionError:
        print(f'[PowerPulse] CSV en uso (¿abierto en Excel?). {len(pendientes)} registro(s)'
              ' en espera; se guardaran al cerrar el archivo.')
        break

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
      registrar_alerta('Batería baja', f'Nivel de batería {porcentaje}%', 'Media')
      ultima_alerta_tiempo = tiempo_actual
    elif porcentaje <= 10 and (tiempo_actual - ultima_alerta_tiempo >= 10):
      notification.notify(
          title='PowerPulse: ¡BATERÍA CRÍTICA!',
          message=f'¡Peligro! Queda {porcentaje}%. CPU: {cpu}%.',
          timeout=5,
      )
      registrar_alerta('Batería crítica', f'Nivel de batería {porcentaje}%', 'Crítica')
      ultima_alerta_tiempo = tiempo_actual
