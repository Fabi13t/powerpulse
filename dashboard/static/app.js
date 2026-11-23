// PowerPulse - Dashboard: lee la API de Flask y dibuja las vistas
const $ = id => document.getElementById(id);
const COLORES = { 'Crítica': '#ef4444', 'Alta': '#f97316', 'Media': '#f59e0b', 'Info': '#2563eb' };
let vistaActual = 'inicio';

// ----------------------------------------------------------- navegación
document.querySelectorAll('.nav').forEach(b => b.onclick = () => mostrar(b.dataset.vista));
document.querySelectorAll('[data-ir]').forEach(a => a.onclick = e => { e.preventDefault(); mostrar(a.dataset.ir); });

function mostrar(vista) {
  vistaActual = vista;
  document.querySelectorAll('.nav').forEach(b => b.classList.toggle('activo', b.dataset.vista === vista));
  document.querySelectorAll('.vista').forEach(s => s.classList.toggle('activa', s.id === 'vista-' + vista));
  actualizar();
}

// ----------------------------------------------------------- utilidades
const fmt = (v, suf = '', dec = 0) => (v === null || v === undefined) ? '–' : Number(v).toFixed(dec) + suf;
const fechaCorta = f => f ? f.slice(8, 10) + '/' + f.slice(5, 7) : '';

function lienzo(id) {
  const c = $(id), r = window.devicePixelRatio || 1;
  // Se guarda el tamaño original una sola vez: así el lienzo no crece en cada actualización
  if (!c.dataset.alto) { c.dataset.alto = c.getAttribute('height'); c.dataset.ancho = c.getAttribute('width') || ''; }
  const h = Number(c.dataset.alto), w = Number(c.dataset.ancho) || c.clientWidth;
  c.style.height = h + 'px'; if (c.dataset.ancho) c.style.width = w + 'px';
  c.width = w * r; c.height = h * r;
  const ctx = c.getContext('2d'); ctx.scale(r, r); ctx.clearRect(0, 0, w, h);
  ctx.font = '11px Segoe UI, sans-serif';
  return { ctx, w, h: Number(h) };
}

function lineas(id, etiquetas, valores, color, min = 0, max = 100) {
  const { ctx, w, h } = lienzo(id);
  const izq = 34, abajo = 22, alto = h - abajo - 8, ancho = w - izq - 8;
  ctx.strokeStyle = '#eef0f4'; ctx.fillStyle = '#9ca3af';
  for (let i = 0; i <= 4; i++) {
    const y = 8 + alto * i / 4, v = max - (max - min) * i / 4;
    ctx.beginPath(); ctx.moveTo(izq, y); ctx.lineTo(w - 8, y); ctx.stroke();
    ctx.fillText(Math.round(v) + '%', 0, y + 4);
  }
  if (!valores.length) { ctx.fillText('Sin datos todavía', izq + 10, h / 2); return; }
  const X = i => izq + (valores.length === 1 ? ancho / 2 : ancho * i / (valores.length - 1));
  const Y = v => 8 + alto * (1 - (v - min) / (max - min));
  ctx.beginPath(); valores.forEach((v, i) => i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)));
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
  ctx.lineTo(X(valores.length - 1), 8 + alto); ctx.lineTo(X(0), 8 + alto); ctx.closePath();
  ctx.fillStyle = color + '22'; ctx.fill();
  if (valores.length <= 31) {  // pocos puntos (p. ej. salud por día): se marcan con círculos para que se vean
    ctx.fillStyle = color;
    valores.forEach((v, i) => { ctx.beginPath(); ctx.arc(X(i), Y(v), 4, 0, 2 * Math.PI); ctx.fill(); });
    if (valores.length === 1) ctx.fillText(Math.round(valores[0] * 10) / 10 + '%', X(0) + 8, Y(valores[0]) - 6);
  }
  ctx.fillStyle = '#9ca3af'; const paso = Math.ceil(etiquetas.length / 6);
  etiquetas.forEach((e, i) => { if (i % paso === 0) ctx.fillText(e, Math.min(X(i) - 14, w - 34), h - 4); });
}

// Historial del día con eje de TIEMPO real: si hubo un corte (> 5 min sin registros) la línea se interrumpe
function lineaTiempo(id, puntos, color) {
  const { ctx, w, h } = lienzo(id);
  const izq = 34, abajo = 22, alto = h - abajo - 8, ancho = w - izq - 8;
  ctx.strokeStyle = '#eef0f4'; ctx.fillStyle = '#9ca3af';
  for (let i = 0; i <= 4; i++) {
    const y = 8 + alto * i / 4;
    ctx.beginPath(); ctx.moveTo(izq, y); ctx.lineTo(w - 8, y); ctx.stroke();
    ctx.fillText((100 - 25 * i) + '%', 0, y + 4);
  }
  const datos = puntos.filter(p => p.bateria != null).map(p => {
    const [hh, mm, ss] = p.momento.slice(11).split(':').map(Number);
    return { t: hh * 60 + mm + (ss || 0) / 60, v: p.bateria };  // minutos desde las 00:00
  });
  if (!datos.length) { ctx.fillText('Sin datos todavía', izq + 10, h / 2); return; }
  const t0 = datos[0].t, t1 = Math.max(datos[datos.length - 1].t, t0 + 10);
  const X = t => izq + ancho * (t - t0) / (t1 - t0), Y = v => 8 + alto * (1 - v / 100);
  // tramos continuos: se separan donde hay más de 5 minutos sin registros
  const tramos = [[datos[0]]];
  for (let i = 1; i < datos.length; i++) {
    if (datos[i].t - datos[i - 1].t > 5) tramos.push([]);
    tramos[tramos.length - 1].push(datos[i]);
  }
  tramos.forEach(tr => {
    ctx.beginPath(); tr.forEach((p, i) => i ? ctx.lineTo(X(p.t), Y(p.v)) : ctx.moveTo(X(p.t), Y(p.v)));
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    ctx.lineTo(X(tr[tr.length - 1].t), 8 + alto); ctx.lineTo(X(tr[0].t), 8 + alto); ctx.closePath();
    ctx.fillStyle = color + '22'; ctx.fill();
    if (tr.length === 1) { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(X(tr[0].t), Y(tr[0].v), 3, 0, 2 * Math.PI); ctx.fill(); }
  });
  if (datos.length <= 31) {  // pocos registros: se marcan con puntos
    ctx.fillStyle = color;
    datos.forEach(p => { ctx.beginPath(); ctx.arc(X(p.t), Y(p.v), 4, 0, 2 * Math.PI); ctx.fill(); });
  }
  // zonas sin datos (cortes) en gris con su leyenda
  ctx.font = '10px Segoe UI, sans-serif';
  for (let i = 1; i < tramos.length; i++) {
    const a = X(tramos[i - 1][tramos[i - 1].length - 1].t), b = X(tramos[i][0].t);
    ctx.fillStyle = 'rgba(148,163,184,0.15)'; ctx.fillRect(a, 8, b - a, alto);
    if (b - a > 50) { ctx.fillStyle = '#64748b'; ctx.fillText('Sin datos', (a + b) / 2 - 20, 8 + alto / 2); }
  }
  // etiquetas de hora repartidas en el eje
  ctx.font = '11px Segoe UI, sans-serif'; ctx.fillStyle = '#9ca3af';
  const hhmm = t => String(Math.floor(t / 60)).padStart(2, '0') + ':' + String(Math.floor(t % 60)).padStart(2, '0');
  for (let i = 0; i <= 5; i++) {
    const t = t0 + (t1 - t0) * i / 5;
    ctx.fillText(hhmm(t), Math.min(Math.max(X(t) - 14, izq - 14), w - 34), h - 4);
  }
}

function barras(id, etiquetas, valores) {
  const { ctx, w, h } = lienzo(id);
  const max = Math.max(1, ...valores), ancho = (w - 10) / valores.length;
  valores.forEach((v, i) => {
    const alto = (h - 40) * v / max, x = 5 + i * ancho + ancho * 0.25;
    ctx.fillStyle = '#2563eb'; ctx.fillRect(x, h - 20 - alto, ancho * 0.5, alto);
    ctx.fillStyle = '#6b7280'; ctx.fillText(etiquetas[i], x - 2, h - 5);
    if (v) ctx.fillText(v, x + ancho * 0.15, h - 24 - alto);
  });
}

function dona(id, partes, centro, sub) {
  const c = $(id), ctx = c.getContext('2d'), r = c.width / 2;
  ctx.clearRect(0, 0, c.width, c.height);
  const total = partes.reduce((s, p) => s + p.valor, 0);
  let ang = -Math.PI / 2;
  if (!total) partes = [{ valor: 1, color: '#e5e7eb' }];
  partes.forEach(p => {
    const a = (p.valor / (total || 1)) * Math.PI * 2;
    ctx.beginPath(); ctx.arc(r, r, r - 8, ang, ang + a); ctx.strokeStyle = p.color; ctx.lineWidth = 12; ctx.stroke();
    ang += a;
  });
  ctx.fillStyle = '#111827'; ctx.textAlign = 'center'; ctx.font = 'bold 18px Segoe UI';
  ctx.fillText(centro, r, r + 4); ctx.font = '11px Segoe UI'; ctx.fillStyle = '#6b7280';
  if (sub) ctx.fillText(sub, r, r + 20); ctx.textAlign = 'left';
}

function tarjetaAlerta(a) {
  return `<div class="alerta ${a.nivel}"><b style="font-size:13px;margin:0">${a.tipo}</b>
          <small>${fechaCorta(a.fecha)} ${a.hora.slice(0, 5)} · ${a.descripcion}</small></div>`;
}

// ----------------------------------------------------------- vistas
async function verInicio() {
  const d = await (await fetch('/api/resumen')).json(), u = d.ultimo;
  $('fechaHora').textContent = new Date().toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' });
  $('estadoSistema').textContent = d.activo ? '● Sistema activo'
    : u ? `● Sin datos desde las ${u.hora.slice(0, 5)}` : '● Sin datos hoy';
  $('estadoSistema').className = 'chip ' + (d.activo ? 'verde' : 'rojo');
  $('estadoLateral').className = 'punto' + (d.activo ? '' : ' inactivo');
  if (u) {
    $('kBateria').textContent = fmt(u.porcentaje_bateria, '%');
    $('bBateria').style.width = (u.porcentaje_bateria || 0) + '%';
    $('kBateriaSub').textContent = u.cargando ? 'Cargando' : 'En uso (batería)';
    $('kCarga').textContent = u.cargando ? 'Con cargador' : 'Sin cargador';
    $('kCargaSub').textContent = u.cargando ? 'Usando el cargador' : 'Usando batería';
    $('kCpu').textContent = fmt(u.uso_cpu, '%');
    $('bCpu').style.width = (u.uso_cpu || 0) + '%';
    $('kCpuSub').textContent = u.uso_cpu >= 70 ? 'Carga alta' : u.uso_cpu >= 30 ? 'Carga moderada' : 'Carga baja';
    if (u.cargando) {  // cargando: se muestra cuánto sube la batería por minuto
      const v = d.velocidad_carga;
      $('kTasa').innerHTML = v == null ? '–' : '+' + v.toFixed(2) + '<span class="tenue"> %/min</span>';
      $('kTasaSub').textContent = v == null ? 'Cargando' : 'Cargando (velocidad de carga)';
    } else {
      $('kTasa').innerHTML = fmt(u.tasa_descarga_min, '', 2) + '<span class="tenue"> %/min</span>';
      $('kTasaSub').textContent = u.tasa_descarga_min > 1 ? 'Descarga rápida' : 'Estable';
    }
  }
  lineaTiempo('gHistorial', d.historial, '#2563eb');
  $('alertasRecientes').innerHTML = d.alertas_recientes.length
    ? d.alertas_recientes.map(tarjetaAlerta).join('') : '<p class="vacio">Sin alertas en los últimos 7 días.</p>';
}

async function verBateria() {
  const d = await (await fetch('/api/bateria')).json(), u = d.ultimo || {};
  dona('gNivel', [{ valor: u.porcentaje_bateria || 0, color: '#10b981' }, { valor: 100 - (u.porcentaje_bateria || 0), color: '#e5e7eb' }],
       fmt(u.porcentaje_bateria, '%'));
  $('nivelSub').textContent = u.cargando ? 'Cargando' : 'En uso (batería)';
  $('kSalud').textContent = fmt(u.salud_pct, '%', 1);
  const s = u.salud_pct, chip = $('kSaludChip');
  chip.textContent = s == null ? 'Sin dato' : s >= 80 ? '✔ Buena' : s >= 60 ? 'Desgaste moderado' : 'Reemplazo sugerido';
  chip.className = 'chip ' + (s == null ? '' : s >= 80 ? 'verde' : s >= 60 ? 'amarillo' : 'rojo');
  $('kDiseno').textContent = fmt(u.capacidad_diseno_wh, ' Wh', 2);
  $('kActual').textContent = 'Actual: ' + fmt(u.capacidad_actual_wh, ' Wh', 2);
  $('kCiclos').textContent = fmt(u.ciclos_carga);
  const seg = u.tiempo_restante_seg;
  const horas = s => `${Math.floor(s / 3600)} h ${Math.round(s % 3600 / 60)} min`;
  if (u.cargando) {  // Windows no da el tiempo al cargar: se estima con la velocidad de carga
    const v = d.velocidad_carga, falta = 100 - (u.porcentaje_bateria || 0);
    $('kRestanteTit').textContent = 'Tiempo para carga completa';
    $('kRestante').textContent = falta <= 0 ? 'Carga completa' : v > 0 ? '≈ ' + horas(falta / v * 60) : 'Calculando…';
  } else {
    $('kRestanteTit').textContent = 'Tiempo estimado restante';
    $('kRestante').textContent = seg > 0 ? horas(seg) : '–';
  }
  $('kVoltaje').textContent = u.voltaje_mv ? (u.voltaje_mv / 1000).toFixed(2) + ' V' : '–';
  const saludes = d.salud_por_dia.map(p => p.salud);
  const minimo = saludes.length ? Math.max(0, Math.floor(Math.min(...saludes) / 10) * 10 - 10) : 0;
  lineas('gSalud', d.salud_por_dia.map(p => fechaCorta(p.fecha)), saludes, '#10b981', minimo, 100);
  const c = d.consumo, nd = 'No reportado', est = c.estimado ? ' (est.)' : '';
  $('cProm').textContent = c.promedio == null ? nd : c.promedio + ' W' + est;
  $('cMax').textContent = c.maximo == null ? nd : c.maximo + ' W' + est;
  $('cMin').textContent = c.minimo == null ? nd : c.minimo + ' W' + est;
}

async function verSistema() {
  const d = await (await fetch('/api/sistema')).json();
  $('plan').textContent = d.plan || '–';
  const ahorro = /econom|ahorro|saver/i.test(d.plan || '');
  $('planChip').textContent = ahorro ? 'Modo ahorro activo' : 'Normal';
  $('planChip').className = 'chip ' + (ahorro ? 'amarillo' : 'verde');
  $('politica').textContent = `Cuando la batería baja del ${d.umbral} % sin cargador, PowerPulse activa automáticamente el plan de ahorro de Windows (powercfg) y lo restaura al conectar el cargador.`;
  $('recomendaciones').innerHTML = d.recomendaciones.map(r =>
    `<div class="reco"><div>${r[0]}<span class="chip azul">${r[2]}</span></div><p>${r[1]}</p></div>`).join('');
}

async function verAlertas() {
  const d = await (await fetch('/api/alertas?dias=7')).json();
  $('tablaAlertas').innerHTML = d.alertas.length ? d.alertas.map(a =>
    `<tr><td>${fechaCorta(a.fecha)} – ${a.hora.slice(0, 5)}</td>
         <td><span style="color:${COLORES[a.nivel]}">●</span> ${a.tipo}</td><td>${a.descripcion}</td>
         <td><span class="chip" style="background:${COLORES[a.nivel]}22;color:${COLORES[a.nivel]}">${a.nivel}</span></td></tr>`).join('')
    : '<tr><td colspan="4" class="vacio">Sin eventos registrados.</td></tr>';
  const partes = ['Crítica', 'Alta', 'Media', 'Info'].map(n => ({ nombre: n, valor: d.resumen[n] || 0, color: COLORES[n] }));
  dona('gResumen', partes, d.alertas.length, 'Total');
  $('leyenda').innerHTML = '<b class="chico">Resumen de alertas</b>' + partes.map(p =>
    `<div><span><span style="color:${p.color}">●</span> ${p.nombre}</span><b style="font-size:13px;margin:0">${p.valor}</b></div>`).join('');
  barras('gDias', d.por_dia.map(p => p.fecha.slice(8, 10)), d.por_dia.map(p => p.total));
}

// ----------------------------------------------------------- refresco
async function actualizar() {
  try {
    await { inicio: verInicio, bateria: verBateria, sistema: verSistema, alertas: verAlertas }[vistaActual]();
    $('avisoServidor').hidden = true;
  } catch (e) {  // Flask no responde: se avisa en pantalla y se mantienen los últimos datos
    $('avisoServidor').hidden = false;
    console.error('No se pudo actualizar:', e);
  }
}
actualizar();
setInterval(actualizar, 5000);   // se actualiza cada 5 segundos
window.onresize = actualizar;
