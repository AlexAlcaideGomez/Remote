# Medidas — app Android

La app de medidas instalada en el móvil, sin navegador, sin internet y sin cuentas.
Haces foto al papel de las medidas, dices para quién es y queda guardado y ordenado
**solo en ese móvil**.

## Instalarla

1. En el móvil Android, abre
   **https://github.com/AlexAlcaideGomez/Remote/releases/latest**
   y toca **Medidas.apk** para descargarlo.
2. Abre el archivo descargado (en la notificación o en *Descargas*).
3. La primera vez, Android te pedirá permiso para "instalar apps de origen desconocido"
   desde el navegador o el gestor de archivos: actívalo y vuelve atrás.
4. Pulsa **Instalar**. Aparecerá el icono **Medidas**.

Si Play Protect avisa de que la app es "desconocida", es normal: no está en la Play Store.
Pulsa *Más detalles → Instalar de todas formas*.

**Para actualizar**, descarga el APK nuevo desde el mismo enlace e instálalo encima.
Lo guardado se conserva.

> ⚠️ **No desinstales la app sin haber hecho antes una copia de seguridad.**
> Desinstalarla, o borrar sus datos desde Ajustes, borra todas las medidas.

## Copia de seguridad

En la pantalla principal, abajo del todo:

- **💾 Hacer copia** guarda un `.zip` con todas las fotos en *Descargas › Medidas*.
- **📤 Enviar la copia** abre el menú de Android para mandarla por correo, subirla a
  Drive, etc. Así queda fuera del móvil.
- **📂 Recuperar una copia** vuelve a cargar un `.zip`, por ejemplo en un móvil nuevo.

La app avisa si pasa una semana sin copia.

## Para quien la mantenga

- `pagina/medidas.html` es la app en sí. Es la misma página que se publica como versión web
  en claude.ai: allí se usa tal cual y aquí se envuelve en un documento completo al compilar.
  La página detecta la app por `window.AppMedidas`.
- `app/src/main/java/.../MainActivity.java` es un WebView que sirve la página desde los
  assets (`https://appassets.androidplatform.net/`, con IndexedDB). Además abre la cámara
  y la galería, guarda y envía la copia (`AppMedidas`) y gestiona el botón atrás
  (`window.atras`).
- GitHub Actions (`.github/workflows/android-medidas.yml`) fabrica el APK en cada cambio y
  lo publica en *Releases*.
- `firma/medidas.jks` es la clave de firma. **Tiene que ser siempre la misma**: con otra,
  Android no deja actualizar y obliga a desinstalar, y eso borra los datos. Está en el
  repositorio para que GitHub pueda firmar, así que conviene que el repositorio sea privado.
