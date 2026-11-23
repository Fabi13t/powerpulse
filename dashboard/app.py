"""PowerPulse - Dashboard web (Sprint 4: RF-013 y RF-014)
Requisitos: pip install flask
Ejecutar:   python dashboard/app.py   ->  http://127.0.0.1:5000
"""
import csv
import glob
import io
import os
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, request, send_from_directory

CARPETA_LOGS = os.path.join(os.environ.get('LOCALAPPDATA', '.'), 'PowerPulse', 'logs')
CARPETA_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
UMBRAL_AHORRO = 20
TASA_MAXIMA = 3  # %/min; por encima se descarta para estimar el consumo
NUMERICOS = ['porcentaje_bateria', 'cargando', 'uso_cpu', 'tasa_descarga_min',
             'tiempo_restante_seg', 'voltaje_mv', 'consumo_w', 'capacidad_diseno_wh',
             'capacidad_actual_wh', 'ciclos_carga', 'salud_pct']

app = Flask(__name__, static_folder=CARPETA_WEB, static_url_path='/static')


# ------------------------------------------------------------- lectura de CSV
def numero(texto):
  """Convierte el texto del CSV en número; vacío -> None."""
  try:
    return float(texto) if texto not in ('', None) else None
  except ValueError:
    return None


def leer_csv(patron, dias):
  """Lee los CSV diarios (powerpulse_* o alertas_*) de los últimos `dias` días."""
  desde = (datetime.now() - timedelta(days=dias - 1)).strftime('%Y-%m-%d')
  filas = []
  for ruta in sorted(glob.glob(os.path.join(CARPETA_LOGS, patron))):
    fecha = os.path.basename(ruta).split('_')[-1][:10]
    if fecha < desde:
      continue
    for codificacion in ('utf-8-sig', 'cp1252'):  # CSV nuevos (UTF-8) o antiguos (Windows)
      try:
        with open(ruta, newline='', encoding=codificacion) as f:
          filas.extend(csv.DictReader(f))
        break
      except UnicodeDecodeError:
        continue  # se prueba con la otra codificación
      except PermissionError:
        break     # archivo en uso: se omite sin detener el dashboard
  return filas


def telemetria(dias=1):
  filas = leer_csv('powerpulse_*.csv', dias)
  for fila in filas:
    for campo in NUMERICOS:
      fila[campo] = numero(fila.get(campo))
    fila['momento'] = f"{fila.get('fecha', '')} {fila.get('hora', '')}"
  filas.sort(key=lambda fila: fila['momento'])
  return filas


def alertas(dias=7):
  filas = leer_csv('alertas_*.csv', dias)
  filas.sort(key=lambda fila: (fila.get('fecha', ''), fila.get('hora', '')), reverse=True)
  return filas


def reducir(filas, maximo=300):
  """Toma como máximo `maximo` puntos para que las gráficas sean ligeras."""
  paso = max(1, len(filas) // maximo)
  return filas[::paso]


def velocidad_carga(filas, minutos=10):
  """Con el cargador conectado: cuántos % por minuto sube la batería (últimos `minutos`)."""
  if not filas or not filas[-1]['cargando']:
    return None
  limite = (datetime.strptime(filas[-1]['momento'], '%Y-%m-%d %H:%M:%S')
            - timedelta(minutes=minutos)).strftime('%Y-%m-%d %H:%M:%S')
  tramo = [f for f in filas if f['momento'] >= limite and f['cargando']
           and f['porcentaje_bateria'] is not None]
  if len(tramo) < 2:
    return None
  inicio = datetime.strptime(tramo[0]['momento'], '%Y-%m-%d %H:%M:%S')
  fin = datetime.strptime(tramo[-1]['momento'], '%Y-%m-%d %H:%M:%S')
  duracion_min = (fin - inicio).total_seconds() / 60
  if duracion_min <= 0:
    return None
  return round((tramo[-1]['porcentaje_bateria'] - tramo[0]['porcentaje_bateria']) / duracion_min, 2)


def consumo_estimado(fila):
  """Si la batería no reporta el consumo (ACPI = -1), se estima en vatios:
  W = (tasa %/min / 100) x capacidad actual (Wh) x 60 min/h. Solo descargando."""
  tasa, cap = fila['tasa_descarga_min'], fila['capacidad_actual_wh']
  # Más de 3 %/min (> ~90 W en tu batería) no es real: son lecturas erróneas, p. ej. del cálculo antiguo cada 2 s
  if fila['cargando'] or not tasa or tasa <= 0 or tasa > TASA_MAXIMA or not cap or cap <= 0:
    return None
  return tasa / 100 * cap * 60


# ------------------------------------------------------------------ API JSON
@app.route('/')
def inicio():
  return send_from_directory(CARPETA_WEB, 'index.html')


@app.route('/api/resumen')
def api_resumen():
  filas = telemetria(1)
  ultimo = filas[-1] if filas else None
  activo = False
  if ultimo:
    try:
      momento = datetime.strptime(ultimo['momento'], '%Y-%m-%d %H:%M:%S')
      activo = datetime.now() - momento < timedelta(minutes=3)
    except ValueError:
      activo = False  # fila con fecha u hora en otro formato
  return jsonify({
      'ultimo': ultimo,
      'activo': activo,
      'velocidad_carga': velocidad_carga(filas),
      'historial': [{'momento': f['momento'], 'bateria': f['porcentaje_bateria']}
                    for f in reducir(filas)],
      'alertas_recientes': alertas(7)[:3],
  })


@app.route('/api/bateria')
def api_bateria():
  filas = telemetria(30)  # 30 días = mismo periodo de retención de los CSV
  ultimo = filas[-1] if filas else None
  por_dia = {}
  for f in filas:
    if f['salud_pct'] is not None:
      por_dia[f['fecha']] = f['salud_pct']  # último valor del día
  consumos = [f['consumo_w'] for f in filas if f['consumo_w'] is not None]
  estimado = False
  if not consumos:  # la batería no reporta el consumo: se estima con la tasa de descarga
    consumos = [c for c in map(consumo_estimado, filas) if c is not None]
    estimado = bool(consumos)
  return jsonify({
      'ultimo': ultimo,
      'velocidad_carga': velocidad_carga(filas),
      'salud_por_dia': [{'fecha': d, 'salud': s} for d, s in sorted(por_dia.items())],
      'consumo': {
          'promedio': round(sum(consumos) / len(consumos), 2) if consumos else None,
          'maximo': round(max(consumos), 2) if consumos else None,
          'minimo': round(min(consumos), 2) if consumos else None,
          'estimado': estimado,
      },
  })


@app.route('/api/sistema')
def api_sistema():
  filas = telemetria(1)
  ultimo = filas[-1] if filas else None
  recomendaciones = []
  if ultimo:
    bat, carga = ultimo['porcentaje_bateria'], ultimo['cargando']
    cpu, salud = ultimo['uso_cpu'], ultimo['salud_pct']
    if bat is not None and bat <= UMBRAL_AHORRO and not carga:
      recomendaciones.append(['Batería baja', 'Conecta el cargador; el modo ahorro ya se activó automáticamente.', 'Automático'])
    if cpu is not None and cpu >= 70:
      recomendaciones.append(['Reduce el uso de CPU', f'La CPU está al {cpu:.0f} %. Cierra las aplicaciones que no uses.', 'Según CPU'])
    if salud is not None and salud < 80:
      recomendaciones.append(['Batería desgastada', f'La salud es {salud:.1f} %. Evita mantenerla siempre al 100 % y el calor excesivo.', 'Según salud'])
    if carga and bat is not None and bat >= 100:
      recomendaciones.append(['Gestiona la carga', 'La batería está al 100 % con el cargador conectado. Desconéctalo de vez en cuando para prolongar su vida útil.', 'Consejo'])
  recomendaciones.append(['Optimiza el brillo', 'Reducir el brillo de la pantalla prolonga la duración de la batería.', 'Consejo manual'])
  return jsonify({
      'plan': ultimo['esquema_energia'] if ultimo else '',
      'umbral': UMBRAL_AHORRO,
      'recomendaciones': recomendaciones,
  })


@app.route('/api/alertas')
def api_alertas():
  dias = int(request.args.get('dias', 7))
  lista = alertas(dias)
  resumen = {'Crítica': 0, 'Alta': 0, 'Media': 0, 'Info': 0}
  for a in lista:
    resumen[a.get('nivel', 'Info')] = resumen.get(a.get('nivel', 'Info'), 0) + 1
  hoy = datetime.now().date()
  por_dia = []
  for i in range(6, -1, -1):
    dia = (hoy - timedelta(days=i)).strftime('%Y-%m-%d')
    por_dia.append({'fecha': dia, 'total': sum(1 for a in lista if a.get('fecha') == dia)})
  return jsonify({'alertas': lista, 'resumen': resumen, 'por_dia': por_dia})


@app.route('/api/alertas/exportar')
def api_exportar():
  salida = io.StringIO()
  writer = csv.writer(salida)
  writer.writerow(['id_evento', 'fecha', 'hora', 'tipo', 'descripcion', 'nivel'])
  for a in alertas(int(request.args.get('dias', 7))):
    writer.writerow([a.get(c, '') for c in ['id_evento', 'fecha', 'hora', 'tipo', 'descripcion', 'nivel']])
  return Response('﻿' + salida.getvalue(), mimetype='text/csv',
                  headers={'Content-Disposition': 'attachment; filename=alertas_powerpulse.csv'})


if __name__ == '__main__':
  print('=== PowerPulse: Dashboard activo en http://127.0.0.1:5000 ===')
  app.run(host='127.0.0.1', port=5000, debug=False)
