# Medidas

App para el móvil que guarda las medidas que tomas en las obras, ordenadas por cliente.
Sigues apuntando en papel como siempre; al terminar, le haces una foto y dices para quién es.
Así el papel ya puede perderse, que las medidas quedan guardadas.

## Cómo se usa

1. Pulsa **📷 Nueva toma de medidas**.
2. **Haz foto** al papel (o a varios). También puedes elegirlas de la galería.
3. En **Cliente / obra** escribe o dicta con el 🎤 del teclado para quién es:
   *"Juan Pérez, calle Mayor 3, puerta garaje"*. Las notas son opcionales.
4. **Guardar**. La fecha, la hora y quién lo ha hecho se ponen solos.

Después:

- En la lista salen los trabajos **pendientes**, con los más recientes arriba.
- El **buscador** encuentra por cliente, calle, trabajo, quién lo hizo o fecha
  (da igual que escribas con o sin tildes).
- Al abrir un trabajo ves las fotos. Tócalas para verlas en grande, y otra vez para ampliar.
- Si vuelves a la obra, **➕ Añadir fotos** las añade al mismo trabajo.
- **✅ Marcar terminado** lo pasa a la pestaña *Terminados*, sin borrarlo.

### Sin cobertura

Funciona igual. Lo que guardes se queda en el móvil con la marca **⏳ Sin subir**, y se sube
solo en cuanto vuelve la señal. No hace falta hacer nada.

(Lo que necesita conexión: entrar la primera vez, editar el texto, marcar terminado, borrar
y gestionar usuarios.)

### Varias personas

Cada uno entra con su usuario. Todos ven todos los trabajos del taller y pueden añadir fotos,
y en cada trabajo pone quién tomó las medidas. Solo quien lo creó, o el administrador, puede
borrarlo.

El administrador da de alta y de baja a los demás desde **☰ → Usuarios**. Al dar de baja a
alguien, no puede entrar más, pero sus medidas se quedan guardadas.

### Ponerla como una app en el móvil

Abre la dirección en el navegador y:

- **Android (Chrome):** menú ⋮ → *Añadir a pantalla de inicio* / *Instalar aplicación*.
- **iPhone (Safari):** botón compartir → *Añadir a pantalla de inicio*.

Queda un icono como el de cualquier app y se abre a pantalla completa.

## Puesta en marcha (para quien la instale)

Necesita un servidor con dirección **https**. Puede ser el mismo que el asistente de
llamadas. Hace falta https porque el móvil solo deja usar la cámara y el modo sin conexión
en páginas seguras.

```bash
cp .env.example .env      # nombre del negocio y el usuario administrador
docker compose up -d --build
```

O sin Docker (Python 3.11 o superior):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

El administrador se crea la primera vez que arranca, con los datos de `.env`. Luego conviene
cambiarle la contraseña desde **☰ → Cambiar mi contraseña**.

Todo se guarda en la carpeta `datos/`: la base de datos `medidas.db` y las fotos.
**Haz copia de seguridad de esa carpeta.** Por ejemplo, una copia diaria a otro sitio.

Para probar en un ordenador sin https, pon `COOKIE_SEGURA=no` en `.env` y entra por
`http://localhost:8000`.

## Para quien la mantenga

```
app/main.py      API (FastAPI): sesión, trabajos, fotos y usuarios; sirve la app
app/db.py        SQLite
static/app.js    La app del móvil (sin frameworks ni compilación)
static/sw.js     Service worker: abrir la app y ver fotos ya vistas sin conexión
tests/           pip install -r requirements-dev.txt && pytest
```

- Los identificadores de trabajos y fotos los genera el móvil. Así se puede guardar sin
  conexión y reintentar la subida sin duplicar nada: los `PUT` son idempotentes.
- La cola de subida vive en IndexedDB y se vacía al recuperar la conexión, al volver a abrir
  la app y cada minuto.
- El móvil reduce las fotos a 2400 px antes de guardarlas. El servidor las vuelve a validar
  con Pillow, las endereza, les quita los metadatos (EXIF, GPS) y genera una miniatura de
  400 px.
- Borrar trabajos y fotos solo los marca como borrados: los archivos se quedan en el disco.
