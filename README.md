# Asistente de llamadas para la carpintería metálica

Contesta las llamadas cuando tú no puedes, habla con el cliente, apunta lo que necesita
y te lo deja resumido en una página web que miras desde el móvil cuando te venga bien.
Sigues usando **tu mismo teléfono y tu mismo número**.

```
Cliente llama a tu móvil
        │
        ├─ Lo coges tú ──────────────► hablas normal
        │
        └─ No lo coges / lo rechazas ─► se desvía al número del asistente
                                          │
                                          ▼
                     El asistente contesta, pregunta lo necesario y se despide
                                          │
                                          ▼
                 Página "Recados" en tu móvil (+ aviso por Telegram si quieres)
                 ┌──────────────────────────────────────────────┐
                 │ 🔴 Puerta de garaje no cierra     hoy 12:48  │
                 │ Marta López · 611 22 23 33                   │
                 │ La corredera del garaje no responde...       │
                 │ 👉 Llamar cuanto antes para ir hoy           │
                 │ [📞 Llamar] [WhatsApp] [✅ Hecho]            │
                 └──────────────────────────────────────────────┘
```

## Qué hace

- Contesta en español, de usted, presentándose como el asistente automático del negocio.
- Pregunta solo lo que hace falta: quién es, qué necesita (presupuesto, encargo en marcha,
  avería, proveedor, factura…), detalles del trabajo (material, medidas, dirección, plazo),
  si es urgente y cuándo le viene bien que le llames.
- **No da precios, plazos ni citas**: dice siempre que tú le llamarás para concretarlo.
- Al colgar, resume la llamada en una ficha: titular, nombre, motivo, urgencia, datos
  concretos y qué deberías hacer. Los urgentes salen arriba y en rojo.
- Desde la ficha: botón para **llamar**, para abrir **WhatsApp** con ese número, y para
  marcarla como **hecha**. También puedes leer la conversación entera.
- Si la persona cuelga a mitad, o no dice nada, también queda apuntada con su número.
- Opcional: te manda un aviso por **Telegram** con cada recado (o solo con los urgentes).

## Qué necesitas

| Qué | Para qué | Dónde |
|---|---|---|
| Cuenta de **Claude API** | La inteligencia que habla y resume | https://platform.claude.com |
| Cuenta de **Twilio** con un número español | El número al que se desvían tus llamadas | https://www.twilio.com |
| Un **servidor** con dirección https | Donde funciona este programa | Un VPS pequeño, Railway, Render, Fly.io… |

Para un número español, Twilio pide documentación (DNI o CIF y una dirección en España);
tarda unos días en aprobarse. Ambos servicios cobran por uso: unos pocos euros al mes por el
número y unos céntimos por minuto de llamada y por cada resumen. Mira los precios actuales en
sus webs. Pregunta también a tu compañía de móvil si el **desvío de llamadas** a un fijo te
cuesta algo con tu tarifa (en las tarifas con llamadas ilimitadas suele estar incluido).

## Puesta en marcha

### 1. Configurar

```bash
cp .env.example .env
```

Abre `.env` y rellena el nombre del negocio, tu nombre, la clave de Claude, el token de
Twilio, la dirección pública y una contraseña para el panel.

Luego edita **`negocio.md`** con lo que haces, tu zona y tu horario. El asistente solo dirá
lo que ponga ahí; lo demás lo apunta para que lo contestes tú.

### 2. Arrancar en el servidor

Con Docker:

```bash
docker compose up -d --build
```

Sin Docker (Python 3.11 o superior):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Las llamadas se guardan en `datos/llamadas.db`. Delante tiene que haber https
(por ejemplo con Caddy o el que te dé el servicio donde lo alojes).

### 3. Conectar el número de Twilio

En la consola de Twilio → *Phone Numbers* → tu número → *Voice Configuration*:

- **A call comes in** → Webhook → `https://TU-DIRECCION/voz/entrante` → `HTTP POST`
- **Call status changes** → `https://TU-DIRECCION/voz/estado` → `HTTP POST`

Llama al número de Twilio y prueba. El recado aparecerá en `https://TU-DIRECCION/`
(te pedirá el usuario y la contraseña del panel). Guárdala en la pantalla de inicio del móvil
para abrirla como una app.

### 4. Desviar tu móvil al asistente

Marca estos códigos en tu móvil como si fuera una llamada (cambia `+34XXXXXXXXX` por el
número de Twilio). Funcionan con casi todas las compañías; si alguno no va, pregunta en la
tuya cómo activar el desvío.

| Código | Qué hace |
|---|---|
| `**004*+34XXXXXXXXX#` | **Recomendado.** Desvía cuando no contestas, cuando rechazas la llamada o si no tienes cobertura. Tú decides en cada llamada si la coges. |
| `##004#` | Quita ese desvío. |
| `**21*+34XXXXXXXXX#` | Desvía **todas** las llamadas (para cuando estás soldando o en una obra y no quieres que suene). |
| `##21#` | Quita el desvío de todas (si tenías el `**004*` puesto, ese sigue funcionando). |

Con el desvío recomendado, lo normal es: si ves que es alguien con quien quieres hablar,
contestas; si no, cuelgas (o lo dejas sonar) y lo atiende el asistente.

También se puede activar en *Ajustes → Teléfono → Desvío de llamadas* (iPhone) o en
*Teléfono → Ajustes → Llamadas → Desvío de llamadas* (Android).

### 5. (Opcional) Avisos por Telegram

1. En Telegram, habla con **@BotFather**, escribe `/newbot` y sigue los pasos. Te dará un
   token: ponlo en `TELEGRAM_BOT_TOKEN`.
2. Escribe cualquier cosa a tu bot nuevo y abre
   `https://api.telegram.org/botTU_TOKEN/getUpdates`. Busca `"chat":{"id":123456789`
   y pon ese número en `TELEGRAM_CHAT_ID`.
3. Si solo quieres avisos de lo urgente, pon `AVISAR_SOLO_URGENTES=si`.

## Probar sin teléfono

Puedes hablar con el asistente escribiendo, para ajustar `negocio.md` antes de desviar
llamadas reales (necesita la clave de Claude en `.env`):

```bash
python simular_llamada.py
```

La llamada de prueba aparece después en el panel.

## Ajustes

Todo va en `.env` (ver `.env.example`). Además de lo básico:

| Variable | Por defecto | Para qué |
|---|---|---|
| `SALUDO` | "Hola, ha llamado a … Le atiende el asistente automático de …" | La frase al descolgar |
| `VOZ` | `Polly.Lucia-Neural` | Voz de Twilio (español de España) |
| `MODELO_CLAUDE` | `claude-opus-5-5` | Modelo de Claude |
| `ESFUERZO_CONVERSACION` | `low` | Cuánto piensa en cada respuesta (más bajo = contesta más rápido) |
| `ESFUERZO_RESUMEN` | `medium` | Cuánto piensa al resumir |
| `MAX_TURNOS` | `14` | Si la llamada se alarga más, se despide |
| `ZONA_HORARIA` | `Europe/Madrid` | Para las horas del panel |

## Privacidad

- El asistente dice desde el primer momento que es un asistente automático.
- No se graba el audio: solo se guarda el texto de la conversación y el resumen, en tu
  servidor. Para generar las respuestas y el resumen, el texto se envía a Claude (Anthropic)
  y el audio pasa por Twilio.
- El panel está protegido con usuario y contraseña, y el servidor rechaza peticiones que no
  vengan firmadas por Twilio.
- Como guardas nombres y teléfonos de clientes, revisa con tu gestoría lo que te pida la
  protección de datos (RGPD), por ejemplo mencionarlo en el saludo.

## Para quien lo mantenga

```
app/main.py        Webhooks de Twilio (/voz/*) y panel web
app/asistente.py   Llamadas a Claude: respuesta en cada turno y resumen final (salida JSON estructurada)
app/db.py          SQLite
app/avisos.py      Telegram
app/templates/     HTML del panel
negocio.md         Lo que el asistente sabe del negocio
tests/             pip install -r requirements-dev.txt && pytest
```

Cada turno de la llamada usa `<Gather input="speech">` de Twilio para pasar la voz a texto,
pide a Claude la siguiente frase (`{"texto", "colgar"}`) y la dice con `<Say>`. Al terminar
(despedida, silencio, fallo o aviso de fin de llamada de Twilio) se genera el resumen una
sola vez y se manda el aviso. Si Claude falla en mitad de la llamada, el asistente se
disculpa, cuelga y el recado queda guardado con el número y lo que se dijo.
