'use strict';

// App de medidas: foto del papel + para quién es. Funciona sin cobertura:
// lo que se guarda va a una cola en el móvil y se sube cuando hay conexión.

const $ = (selector, raiz = document) => raiz.querySelector(selector);
const vista = $('#vista');

let yo = null;          // usuario que ha entrado
let trabajos = [];      // lista del servidor (o la última guardada en el móvil)
let filtro = { texto: '', terminados: false };
let borrador = null;    // toma de medidas a medio hacer: { trabajoId, nuevo, fotos: [{ id, blob, url }] }

// --------------------------------------------------------------------------- Utilidades

function esc(texto) {
  return String(texto ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  return [...b].map(x => x.toString(16).padStart(2, '0')).join('');
}

function normalizar(texto) {
  return String(texto || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

function fecha(iso) {
  const d = new Date(iso);
  const hoy = new Date();
  const ayer = new Date(); ayer.setDate(hoy.getDate() - 1);
  const hora = d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === hoy.toDateString()) return `hoy ${hora}`;
  if (d.toDateString() === ayer.toDateString()) return `ayer ${hora}`;
  return d.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' });
}

let temporizadorAviso;
function avisar(texto) {
  const aviso = $('#aviso');
  aviso.textContent = texto;
  aviso.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, 3500);
}

// --------------------------------------------------------------------------- Almacén en el móvil

const BD = (() => {
  let abierta;
  function abrir() {
    abierta ??= new Promise((ok, mal) => {
      const peticion = indexedDB.open('medidas', 1);
      peticion.onupgradeneeded = () => {
        peticion.result.createObjectStore('cola', { keyPath: 'id' });
        peticion.result.createObjectStore('cache');
      };
      peticion.onsuccess = () => ok(peticion.result);
      peticion.onerror = () => mal(peticion.error);
    });
    return abierta;
  }
  async function operar(almacen, modo, fn) {
    const bd = await abrir();
    return new Promise((ok, mal) => {
      const tx = bd.transaction(almacen, modo);
      const peticion = fn(tx.objectStore(almacen));
      tx.oncomplete = () => ok(peticion?.result);
      tx.onerror = () => mal(tx.error);
      tx.onabort = () => mal(tx.error);
    });
  }
  return {
    cola: () => operar('cola', 'readonly', s => s.getAll()),
    ponerEnCola: item => operar('cola', 'readwrite', s => s.put(item)),
    quitarDeCola: id => operar('cola', 'readwrite', s => s.delete(id)),
    leer: clave => operar('cache', 'readonly', s => s.get(clave)),
    guardar: (clave, valor) => operar('cache', 'readwrite', s => s.put(valor, clave)),
    vaciarCache: () => operar('cache', 'readwrite', s => s.clear()),
  };
})();

// --------------------------------------------------------------------------- Servidor

class ErrorApi extends Error {
  constructor(estado, mensaje) { super(mensaje); this.estado = estado; }
}

async function api(metodo, ruta, cuerpo) {
  const opciones = { method: metodo, credentials: 'same-origin', headers: {} };
  if (cuerpo instanceof FormData) {
    opciones.body = cuerpo;
  } else if (cuerpo !== undefined) {
    opciones.headers['Content-Type'] = 'application/json';
    opciones.body = JSON.stringify(cuerpo);
  }
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch {
    throw new ErrorApi(0, 'Sin conexión');
  }
  if (!respuesta.ok) {
    let mensaje = `Error ${respuesta.status}`;
    try {
      const datos = await respuesta.json();
      if (typeof datos.detail === 'string') mensaje = datos.detail;
    } catch { /* sin cuerpo */ }
    if (respuesta.status === 401 && ruta !== '/api/entrar') sesionCaducada();
    throw new ErrorApi(respuesta.status, mensaje);
  }
  return respuesta.json();
}

function sesionCaducada() {
  if (!yo) return;
  yo = null;
  BD.guardar('yo', null);
  pintarCabecera();
  pintar();
}

async function cargarTrabajos() {
  try {
    trabajos = await api('GET', '/api/trabajos');
    await BD.guardar('trabajos', trabajos);
  } catch { /* sin conexión: se queda la última lista guardada */ }
  repintarSiHaceFalta();
}

// Lista del servidor + lo que todavía está en la cola del móvil.
async function trabajosConPendientes() {
  const cola = await BD.cola();
  const mapa = new Map(trabajos.map(t => [t.id, { ...t, pendientes: [] }]));
  for (const op of cola.sort((a, b) => a.creado - b.creado)) {
    let t = mapa.get(op.trabajoId);
    if (!t) {
      if (!op.trabajo) continue;
      t = { ...op.trabajo, autor: yo?.nombre, autor_id: yo?.id, terminado: false, fotos: [], pendientes: [] };
      mapa.set(t.id, t);
    } else if (op.trabajo) {
      t.titulo = op.trabajo.titulo;
      t.notas = op.trabajo.notas;
    }
    t.pendientes.push(...op.fotos);
    t.sinSubir = true;
  }
  return [...mapa.values()].sort((a, b) => b.creado_en.localeCompare(a.creado_en));
}

// --------------------------------------------------------------------------- Sincronización

let sincronizando = false;
const REINTENTABLE = new Set([0, 401, 408, 429]);

async function sincronizar() {
  if (sincronizando || !yo) return;
  sincronizando = true;
  try {
    const cola = (await BD.cola()).sort((a, b) => a.creado - b.creado);
    for (const op of cola) {
      if (op.trabajo) {
        await api('PUT', `/api/trabajos/${op.trabajoId}`, op.trabajo);
        op.trabajo = null;
        await BD.ponerEnCola(op);
      }
      while (op.fotos.length) {
        const foto = op.fotos[0];
        const datos = new FormData();
        datos.append('foto', foto.blob, `${foto.id}.jpg`);
        try {
          await api('PUT', `/api/trabajos/${op.trabajoId}/fotos/${foto.id}`, datos);
        } catch (e) {
          if (REINTENTABLE.has(e.estado) || e.estado >= 500) throw e;
          avisar(`No se pudo subir una foto: ${e.message}`);
        }
        op.fotos.shift();
        await BD.ponerEnCola(op);
      }
      await BD.quitarDeCola(op.id);
    }
    await cargarTrabajos();
  } catch {
    // Sin conexión o servidor caído: se reintenta más tarde.
  } finally {
    sincronizando = false;
    actualizarEstadoSync();
  }
}

async function actualizarEstadoSync() {
  const elemento = $('#estado-sync');
  if (!yo) { elemento.hidden = true; return; }
  const cola = await BD.cola();
  const fotos = cola.reduce((n, op) => n + op.fotos.length, 0);
  const sinSubir = cola.length ? (fotos ? `${fotos} foto${fotos === 1 ? '' : 's'}` : `${cola.length} toma${cola.length === 1 ? '' : 's'}`) : '';
  if (!navigator.onLine) elemento.textContent = sinSubir ? `📴 ${sinSubir} sin subir` : '📴 Sin conexión';
  else elemento.textContent = sinSubir ? `⏳ Subiendo ${sinSubir}…` : '';
  elemento.hidden = !elemento.textContent;
}

window.addEventListener('online', sincronizar);
window.addEventListener('offline', actualizarEstadoSync);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && yo) { cargarTrabajos(); sincronizar(); }
});
setInterval(() => { if (yo) sincronizar(); }, 60000);

// --------------------------------------------------------------------------- Fotos

// Reduce la foto antes de guardarla: se lee igual de bien y se sube mucho antes con datos móviles.
async function prepararFoto(archivo) {
  try {
    const imagen = await createImageBitmap(archivo, { imageOrientation: 'from-image' });
    const escala = Math.min(1, 2400 / Math.max(imagen.width, imagen.height));
    const lienzo = document.createElement('canvas');
    lienzo.width = Math.round(imagen.width * escala);
    lienzo.height = Math.round(imagen.height * escala);
    lienzo.getContext('2d').drawImage(imagen, 0, 0, lienzo.width, lienzo.height);
    const blob = await new Promise(ok => lienzo.toBlob(ok, 'image/jpeg', 0.85));
    return blob || archivo;
  } catch {
    return archivo;
  }
}

function abrirVisor(url, alBorrar) {
  const visor = $('#visor');
  const marco = $('#visor-marco');
  $('#visor-img').src = url;
  marco.classList.remove('ampliada');
  const borrar = $('#visor-borrar');
  borrar.hidden = !alBorrar;
  borrar.onclick = async () => {
    if (!confirm('¿Borrar esta foto?')) return;
    try {
      await alBorrar();
      cerrarVisor();
    } catch (e) {
      avisar(e.estado === 0 ? 'Necesitas conexión para borrar' : e.message);
    }
  };
  visor.hidden = false;
}

function cerrarVisor() {
  $('#visor').hidden = true;
  $('#visor-img').removeAttribute('src');
}

$('#visor-cerrar').addEventListener('click', cerrarVisor);
$('#visor-img').addEventListener('click', () => $('#visor-marco').classList.toggle('ampliada'));

// --------------------------------------------------------------------------- Cabecera y menú

function pintarCabecera() {
  $('#boton-menu').hidden = !yo;
  $('#menu-usuarios').hidden = !yo?.es_admin;
  $('#menu-quien').textContent = yo ? `${yo.nombre} · ${yo.negocio || ''}` : '';
  actualizarEstadoSync();
}

function cerrarMenu() { $('#menu').hidden = true; }

$('#boton-menu').addEventListener('click', () => { $('#menu').hidden = !$('#menu').hidden; });
document.addEventListener('click', e => {
  if (!e.target.closest('#menu, #boton-menu')) cerrarMenu();
});

$('#menu-salir').addEventListener('click', async () => {
  const cola = await BD.cola();
  if (cola.length && !confirm('Hay medidas sin subir todavía. Se subirán cuando alguien vuelva a entrar en este móvil. ¿Salir igualmente?')) return;
  try {
    await api('POST', '/api/salir');
  } catch {
    avisar('Necesitas conexión para salir');
    return;
  }
  yo = null;
  trabajos = [];
  await BD.vaciarCache();
  if ('caches' in window) await caches.delete('medidas-fotos');
  pintarCabecera();
  location.hash = '#/';
  pintar();
});

// --------------------------------------------------------------------------- Pantallas

function ruta() { return location.hash.slice(1) || '/'; }

window.addEventListener('hashchange', pintar);

function pintar() {
  cerrarMenu();
  cerrarVisor();
  window.scrollTo(0, 0);
  if (!yo) return pintarEntrar();
  const r = ruta();
  if (r === '/') return pintarLista();
  if (r === '/nueva') return pintarNueva(null);
  if (r.startsWith('/t/')) return pintarTrabajo(decodeURIComponent(r.slice(3)));
  if (r.startsWith('/fotos/')) return pintarNueva(decodeURIComponent(r.slice(7)));
  if (r === '/usuarios' && yo.es_admin) return pintarUsuarios();
  if (r === '/contrasena') return pintarContrasena();
  location.hash = '#/';
}

function repintarSiHaceFalta() {
  const r = ruta();
  if (!yo) return;
  if (r === '/') pintarResultados();
  else if (r.startsWith('/t/') && !$('#editar-titulo')) pintarTrabajo(decodeURIComponent(r.slice(3)));
}

// ----- Entrar

function pintarEntrar() {
  vista.innerHTML = `
    <form class="entrar" id="form-entrar">
      <h1>Entrar</h1>
      <label for="usuario">Usuario</label>
      <input id="usuario" autocomplete="username" autocapitalize="none" required>
      <label for="contrasena">Contraseña</label>
      <input id="contrasena" type="password" autocomplete="current-password" required>
      <div class="botones"><button class="boton principal ancho">Entrar</button></div>
    </form>`;
  $('#form-entrar').addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api('POST', '/api/entrar', { usuario: $('#usuario').value, contrasena: $('#contrasena').value });
      yo = await api('GET', '/api/yo');
      await BD.guardar('yo', yo);
    } catch (err) {
      avisar(err.estado === 0 ? 'Sin conexión. Para entrar la primera vez hace falta cobertura.' : err.message);
      return;
    }
    pintarCabecera();
    pintar();
    cargarTrabajos();
    sincronizar();
  });
}

// ----- Lista

function pintarLista() {
  vista.innerHTML = `
    <div class="buscador"><input id="buscar" type="search" placeholder="Buscar cliente, calle, trabajo…" value="${esc(filtro.texto)}"></div>
    <div class="pestanas">
      <button type="button" data-terminados="0" aria-pressed="${!filtro.terminados}">Pendientes</button>
      <button type="button" data-terminados="1" aria-pressed="${filtro.terminados}">Terminados</button>
    </div>
    <div id="resultados"></div>
    <a href="#/nueva" class="boton principal flotante">📷 Nueva toma de medidas</a>`;
  $('#buscar').addEventListener('input', e => { filtro.texto = e.target.value; pintarResultados(); });
  for (const boton of vista.querySelectorAll('.pestanas button')) {
    boton.addEventListener('click', () => {
      filtro.terminados = boton.dataset.terminados === '1';
      pintarLista();
    });
  }
  pintarResultados();
}

async function pintarResultados() {
  const contenedor = $('#resultados');
  if (!contenedor) return;
  const palabras = normalizar(filtro.texto).split(/\s+/).filter(Boolean);
  const lista = (await trabajosConPendientes()).filter(t => {
    if (palabras.length === 0 && t.terminado !== filtro.terminados) return false;
    const texto = normalizar(`${t.titulo} ${t.notas} ${t.autor} ${fecha(t.creado_en)}`);
    return palabras.every(p => texto.includes(p));
  });
  if (!lista.length) {
    contenedor.innerHTML = `<p class="vacio">${palabras.length ? 'No hay nada con esa búsqueda.' :
      filtro.terminados ? 'No hay trabajos terminados.' : 'No hay medidas pendientes.<br>Pulsa el botón de abajo para añadir la primera.'}</p>`;
    return;
  }
  contenedor.innerHTML = lista.map(t => {
    const primera = t.fotos[0] ? `/fotos/${t.fotos[0]}_min.jpg` : null;
    const total = t.fotos.length + t.pendientes.length;
    const miniatura = primera ? `<img src="${primera}" alt="" loading="lazy">`
      : t.pendientes[0] ? `<img data-pendiente="${esc(t.pendientes[0].id)}" alt="">`
      : '<span class="sin-foto">📝</span>';
    return `
      <a class="trabajo" href="#/t/${encodeURIComponent(t.id)}">
        ${miniatura}
        <div class="texto">
          <p class="titulo">${esc(t.titulo)}</p>
          <p class="meta">${esc(fecha(t.creado_en))} · ${esc(t.autor || '')} · ${total} foto${total === 1 ? '' : 's'}</p>
          ${t.sinSubir ? '<span class="etiqueta pendiente">⏳ Sin subir</span>' : ''}
          ${palabras.length && t.terminado ? '<span class="etiqueta">Terminado</span>' : ''}
        </div>
      </a>`;
  }).join('');
  // Miniaturas de fotos que aún están solo en el móvil.
  const pendientes = new Map(lista.flatMap(t => t.pendientes).map(f => [f.id, f.blob]));
  for (const img of contenedor.querySelectorAll('img[data-pendiente]')) {
    img.src = URL.createObjectURL(pendientes.get(img.dataset.pendiente));
  }
}

// ----- Nueva toma de medidas (o añadir fotos a una que ya existe)

async function pintarNueva(trabajoId) {
  const existente = trabajoId ? (await trabajosConPendientes()).find(t => t.id === trabajoId) : null;
  if (trabajoId && !existente) { location.hash = '#/'; return; }
  // Si sales a mitad y vuelves, se recupera lo que llevabas.
  const sirve = borrador && (trabajoId ? !borrador.nuevo && borrador.trabajoId === trabajoId : borrador.nuevo);
  if (!sirve) borrador = { trabajoId: trabajoId || uuid(), nuevo: !trabajoId, fotos: [] };

  vista.innerHTML = `
    <p><a href="${existente ? `#/t/${encodeURIComponent(existente.id)}` : '#/'}" class="boton">← Volver</a></p>
    <h1>${existente ? 'Añadir fotos' : 'Nueva toma de medidas'}</h1>
    ${existente ? `<p class="suave">${esc(existente.titulo)}</p>` : ''}
    <div class="botones">
      <button type="button" class="boton principal" id="hacer-foto">📷 Hacer foto</button>
      <button type="button" class="boton" id="de-galeria">🖼️ De la galería</button>
    </div>
    <input type="file" accept="image/*" capture="environment" id="entrada-camara" style="display:none">
    <input type="file" accept="image/*" multiple id="entrada-galeria" style="display:none">
    <div class="fotos" id="fotos-nuevas"></div>
    ${existente ? '' : `
      <label for="titulo">Cliente / obra</label>
      <input id="titulo" placeholder="Ej.: Juan Pérez, C/ Mayor 3, puerta garaje" autocomplete="off" value="${esc(borrador.titulo || '')}">
      <p class="ayuda">Pulsa el 🎤 del teclado para dictarlo en vez de escribir.</p>
      <label for="notas">Notas <span class="suave">(opcional)</span></label>
      <textarea id="notas">${esc(borrador.notas || '')}</textarea>`}
    <button type="button" class="boton principal flotante" id="guardar">💾 Guardar</button>`;

  const pintarFotos = () => {
    $('#fotos-nuevas').innerHTML = borrador.fotos.map(f => `
      <div class="foto"><img src="${f.url}" alt="">
        <button type="button" class="quitar" data-id="${f.id}" aria-label="Quitar foto">✕</button></div>`).join('');
    for (const boton of vista.querySelectorAll('.quitar')) {
      boton.addEventListener('click', () => {
        borrador.fotos = borrador.fotos.filter(f => f.id !== boton.dataset.id);
        pintarFotos();
      });
    }
  };
  const anadir = async archivos => {
    const boton = $('#guardar');
    boton.disabled = true;
    boton.textContent = 'Preparando fotos…';
    for (const archivo of archivos) {
      const blob = await prepararFoto(archivo);
      borrador.fotos.push({ id: uuid(), blob, url: URL.createObjectURL(blob) });
      pintarFotos();
    }
    boton.disabled = false;
    boton.textContent = '💾 Guardar';
  };
  for (const [boton, entrada] of [['#hacer-foto', '#entrada-camara'], ['#de-galeria', '#entrada-galeria']]) {
    $(boton).addEventListener('click', () => $(entrada).click());
    $(entrada).addEventListener('change', e => { anadir([...e.target.files]); e.target.value = ''; });
  }
  if (!existente) {
    $('#titulo').addEventListener('input', e => { borrador.titulo = e.target.value; });
    $('#notas').addEventListener('input', e => { borrador.notas = e.target.value; });
  }
  pintarFotos();

  $('#guardar').addEventListener('click', async () => {
    const titulo = existente ? null : $('#titulo').value.trim();
    const notas = existente ? '' : $('#notas').value.trim();
    if (!existente && !titulo) { avisar('Pon para quién es (cliente u obra)'); $('#titulo').focus(); return; }
    if (existente && !borrador.fotos.length) { avisar('Añade al menos una foto'); return; }
    if (!existente && !borrador.fotos.length && !notas && !confirm('No has puesto ninguna foto. ¿Guardar igualmente?')) return;
    await BD.ponerEnCola({
      id: uuid(),
      creado: Date.now(),
      trabajoId: borrador.trabajoId,
      trabajo: existente ? null : { titulo, notas, creado_en: new Date().toISOString() },
      fotos: borrador.fotos.map(f => ({ id: f.id, blob: f.blob })),
    });
    const destino = existente ? `#/t/${encodeURIComponent(existente.id)}` : '#/';
    borrador = null;
    avisar('Guardado ✔');
    location.hash = destino;
    actualizarEstadoSync();
    sincronizar();
  });
}

// ----- Ver un trabajo

async function pintarTrabajo(id) {
  const t = (await trabajosConPendientes()).find(x => x.id === id);
  if (!t) {
    vista.innerHTML = '<p><a href="#/" class="boton">← Volver</a></p><p class="vacio">Este trabajo no existe o se ha borrado.</p>';
    return;
  }
  const enServidor = trabajos.some(x => x.id === id);
  const puedeBorrar = yo.es_admin || t.autor_id === yo.id;
  vista.innerHTML = `
    <p><a href="#/" class="boton">← Volver</a></p>
    <div id="cabecera-trabajo">
      <h1>${esc(t.titulo)}</h1>
      <p class="suave">${esc(fecha(t.creado_en))} · ${esc(t.autor || '')}
        ${t.terminado ? ' · <span class="etiqueta">Terminado</span>' : ''}
        ${t.sinSubir ? ' · <span class="etiqueta pendiente">⏳ Sin subir</span>' : ''}</p>
      ${t.notas ? `<div class="notas">${esc(t.notas)}</div>` : ''}
    </div>
    <div class="fotos">
      ${t.fotos.map(f => `<button type="button" class="foto" data-foto="${esc(f)}"><img src="/fotos/${esc(f)}_min.jpg" alt="Foto" loading="lazy"></button>`).join('')}
      ${t.pendientes.map(f => `<button type="button" class="foto" data-pendiente="${esc(f.id)}"><img alt="Foto sin subir"></button>`).join('')}
    </div>
    ${t.fotos.length + t.pendientes.length ? '' : '<p class="suave">Sin fotos.</p>'}
    <div class="botones">
      <a class="boton principal" href="#/fotos/${encodeURIComponent(t.id)}">➕ Añadir fotos</a>
      ${enServidor ? `
        <button type="button" class="boton" id="editar">✏️ Editar texto</button>
        <button type="button" class="boton" id="terminado">${t.terminado ? '↩️ Volver a pendiente' : '✅ Marcar terminado'}</button>
        ${puedeBorrar ? '<button type="button" class="boton peligro" id="borrar">🗑️ Borrar</button>' : ''}` : ''}
    </div>`;

  const pendientes = new Map(t.pendientes.map(f => [f.id, f.blob]));
  for (const boton of vista.querySelectorAll('.foto')) {
    if (boton.dataset.foto) {
      const fotoId = boton.dataset.foto;
      boton.addEventListener('click', () => abrirVisor(`/fotos/${fotoId}.jpg`, puedeBorrar ? async () => {
        await api('DELETE', `/api/trabajos/${t.id}/fotos/${fotoId}`);
        await cargarTrabajos();
      } : null));
    } else {
      const url = URL.createObjectURL(pendientes.get(boton.dataset.pendiente));
      $('img', boton).src = url;
      boton.addEventListener('click', () => abrirVisor(url, null));
    }
  }
  if (!enServidor) return;

  const conConexion = async (accion, despues) => {
    try {
      await accion();
      await cargarTrabajos();
      despues?.();
    } catch (e) {
      avisar(e.estado === 0 ? 'Necesitas conexión para esto' : e.message);
    }
  };
  $('#terminado').addEventListener('click', () => conConexion(
    () => api('POST', `/api/trabajos/${t.id}/terminado`, { terminado: !t.terminado }),
  ));
  $('#borrar')?.addEventListener('click', () => {
    if (!confirm('¿Borrar este trabajo con todas sus fotos?')) return;
    conConexion(() => api('DELETE', `/api/trabajos/${t.id}`), () => { location.hash = '#/'; });
  });
  $('#editar').addEventListener('click', () => {
    $('#cabecera-trabajo').innerHTML = `
      <label for="editar-titulo">Cliente / obra</label>
      <input id="editar-titulo" value="${esc(t.titulo)}">
      <label for="editar-notas">Notas</label>
      <textarea id="editar-notas">${esc(t.notas)}</textarea>
      <div class="botones">
        <button type="button" class="boton" id="cancelar-edicion">Cancelar</button>
        <button type="button" class="boton principal" id="guardar-edicion">Guardar</button>
      </div>`;
    $('#cancelar-edicion').addEventListener('click', () => pintarTrabajo(id));
    $('#guardar-edicion').addEventListener('click', () => {
      const titulo = $('#editar-titulo').value.trim();
      if (!titulo) { avisar('El cliente / obra no puede quedar vacío'); return; }
      conConexion(
        () => api('PUT', `/api/trabajos/${t.id}`, { titulo, notas: $('#editar-notas').value.trim(), creado_en: t.creado_en }),
        () => pintarTrabajo(id),
      );
    });
  });
}

// ----- Usuarios (solo administrador)

async function pintarUsuarios() {
  vista.innerHTML = '<p><a href="#/" class="boton">← Volver</a></p><h1>Usuarios</h1><div id="lista-usuarios" class="suave">Cargando…</div>';
  let usuarios;
  try {
    usuarios = await api('GET', '/api/usuarios');
  } catch (e) {
    $('#lista-usuarios').textContent = e.estado === 0 ? 'Necesitas conexión para ver los usuarios.' : e.message;
    return;
  }
  $('#lista-usuarios').outerHTML = `
    <div>${usuarios.map(u => `
      <div class="usuario">
        <div><b>${esc(u.nombre)}</b> <span class="suave">(${esc(u.usuario)})</span>
          ${u.es_admin ? '<span class="etiqueta">admin</span>' : ''}</div>
        <div class="botones" style="margin:0">
          <button type="button" class="boton" data-clave="${u.id}">🔑 Contraseña</button>
          ${u.id === yo.id ? '' : `<button type="button" class="boton peligro" data-baja="${u.id}">Dar de baja</button>`}
        </div>
      </div>`).join('')}</div>
    <h2>Añadir a alguien</h2>
    <form id="form-usuario">
      <label for="nu-nombre">Nombre</label>
      <input id="nu-nombre" required placeholder="Ej.: Pepe">
      <label for="nu-usuario">Usuario para entrar</label>
      <input id="nu-usuario" required autocapitalize="none" pattern="[A-Za-z0-9._\\-]{2,40}" placeholder="Ej.: pepe">
      <label for="nu-clave">Contraseña</label>
      <input id="nu-clave" required minlength="6">
      <label class="casilla"><input type="checkbox" id="nu-admin"> Puede gestionar usuarios</label>
      <div class="botones"><button class="boton principal ancho">Añadir</button></div>
    </form>`;

  for (const boton of vista.querySelectorAll('[data-clave]')) {
    boton.addEventListener('click', async () => {
      const clave = prompt('Nueva contraseña (mínimo 6 caracteres):');
      if (!clave) return;
      try {
        await api('POST', `/api/usuarios/${boton.dataset.clave}/contrasena`, { contrasena: clave });
        avisar('Contraseña cambiada');
      } catch (e) { avisar(e.message); }
    });
  }
  for (const boton of vista.querySelectorAll('[data-baja]')) {
    boton.addEventListener('click', async () => {
      if (!confirm('¿Dar de baja a este usuario? Sus medidas se quedan guardadas.')) return;
      try {
        await api('DELETE', `/api/usuarios/${boton.dataset.baja}`);
        pintarUsuarios();
      } catch (e) { avisar(e.message); }
    });
  }
  $('#form-usuario').addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api('POST', '/api/usuarios', {
        nombre: $('#nu-nombre').value.trim(),
        usuario: $('#nu-usuario').value.trim().toLowerCase(),
        contrasena: $('#nu-clave').value,
        es_admin: $('#nu-admin').checked,
      });
      avisar('Usuario añadido');
      pintarUsuarios();
    } catch (err) { avisar(err.message); }
  });
}

// ----- Cambiar mi contraseña

function pintarContrasena() {
  vista.innerHTML = `
    <p><a href="#/" class="boton">← Volver</a></p>
    <h1>Cambiar mi contraseña</h1>
    <form id="form-clave">
      <label for="clave1">Nueva contraseña</label>
      <input id="clave1" type="password" autocomplete="new-password" required minlength="6">
      <label for="clave2">Repítela</label>
      <input id="clave2" type="password" autocomplete="new-password" required minlength="6">
      <div class="botones"><button class="boton principal ancho">Cambiar</button></div>
    </form>`;
  $('#form-clave').addEventListener('submit', async e => {
    e.preventDefault();
    if ($('#clave1').value !== $('#clave2').value) { avisar('Las dos contraseñas no coinciden'); return; }
    try {
      await api('POST', `/api/usuarios/${yo.id}/contrasena`, { contrasena: $('#clave1').value });
      avisar('Contraseña cambiada');
      location.hash = '#/';
    } catch (err) { avisar(err.estado === 0 ? 'Necesitas conexión para esto' : err.message); }
  });
}

// --------------------------------------------------------------------------- Arranque

async function iniciar() {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
  trabajos = (await BD.leer('trabajos')) || [];
  try {
    yo = await api('GET', '/api/yo');
    await BD.guardar('yo', yo);
  } catch (e) {
    yo = e.estado === 0 ? (await BD.leer('yo')) || null : null;  // sin cobertura: seguimos con la sesión guardada
  }
  pintarCabecera();
  pintar();
  if (yo) { cargarTrabajos(); sincronizar(); }
}

iniciar();
