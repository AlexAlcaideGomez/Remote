// Permite abrir la app sin cobertura y ver las fotos ya vistas.
// Los datos (lista de trabajos y cola de subida) los guarda la propia app en el móvil.

const VERSION = 'medidas-v1';
const FOTOS = 'medidas-fotos';
const APP = ['/', '/app.js', '/estilos.css', '/manifest.webmanifest', '/icono-180.png', '/icono-192.png', '/icono-512.png'];

self.addEventListener('install', evento => {
  evento.waitUntil(caches.open(VERSION).then(cache => cache.addAll(APP)));
  self.skipWaiting();
});

self.addEventListener('activate', evento => {
  evento.waitUntil(
    caches.keys().then(claves => Promise.all(
      claves.filter(c => c !== VERSION && c !== FOTOS).map(c => caches.delete(c)),
    )),
  );
  self.clients.claim();
});

self.addEventListener('fetch', evento => {
  const url = new URL(evento.request.url);
  if (evento.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;

  if (url.pathname.startsWith('/fotos/')) {
    // Una foto nunca cambia: si ya está guardada, no hace falta conexión.
    evento.respondWith(caches.open(FOTOS).then(async cache => {
      const guardada = await cache.match(evento.request);
      if (guardada) return guardada;
      const respuesta = await fetch(evento.request);
      if (respuesta.ok) cache.put(evento.request, respuesta.clone());
      return respuesta;
    }));
    return;
  }

  // La app: primero la versión nueva; sin conexión, la guardada.
  evento.respondWith(
    fetch(evento.request)
      .then(respuesta => {
        if (respuesta.ok) caches.open(VERSION).then(cache => cache.put(evento.request, respuesta.clone()));
        return respuesta;
      })
      .catch(async () => (await caches.match(evento.request, { ignoreSearch: true }))
        || (evento.request.mode === 'navigate' ? caches.match('/') : Response.error())),
  );
});
