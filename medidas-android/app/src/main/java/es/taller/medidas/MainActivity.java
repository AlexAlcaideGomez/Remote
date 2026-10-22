package es.taller.medidas;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.core.content.FileProvider;
import androidx.webkit.WebViewAssetLoader;

import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * La app es la misma página web de medidas, abierta dentro de un WebView.
 * Aquí solo está lo que la página no puede hacer sola en Android: abrir la cámara
 * o la galería, guardar la copia de seguridad en Descargas, enviarla y el botón "atrás".
 */
public class MainActivity extends Activity {

    // Dirección interna desde la que se sirve la página (no sale a internet).
    private static final String INICIO = "https://appassets.androidplatform.net/assets/index.html";
    private static final int PEDIR_ARCHIVO = 1;
    private static final int PEDIR_CAMARA = 2;

    private WebView web;
    private ValueCallback<Uri[]> esperandoArchivos;
    private Uri fotoDeCamara;

    @Override
    protected void onCreate(Bundle estado) {
        super.onCreate(estado);
        web = new WebView(this);
        setContentView(web);

        WebSettings ajustes = web.getSettings();
        ajustes.setJavaScriptEnabled(true);
        ajustes.setDomStorageEnabled(true);
        ajustes.setAllowFileAccess(false);

        WebViewAssetLoader cargador = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView vista, WebResourceRequest peticion) {
                return cargador.shouldInterceptRequest(peticion.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView vista, WebResourceRequest peticion) {
                Uri destino = peticion.getUrl();
                if ("appassets.androidplatform.net".equals(destino.getHost())) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, destino));
                } catch (ActivityNotFoundException ignorada) {
                    // No hay nada para abrir ese enlace.
                }
                return true;
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView vista, ValueCallback<Uri[]> respuesta, FileChooserParams opciones) {
                if (esperandoArchivos != null) esperandoArchivos.onReceiveValue(null);
                esperandoArchivos = respuesta;
                boolean abierto = opciones.isCaptureEnabled() ? abrirCamara() : abrirSelector(opciones);
                if (!abierto) {
                    esperandoArchivos = null;
                    return false;
                }
                return true;
            }
        });

        web.addJavascriptInterface(new Puente(), "AppMedidas");

        if (estado == null || web.restoreState(estado) == null) web.loadUrl(INICIO);
    }

    private boolean abrirCamara() {
        try {
            File carpeta = new File(getCacheDir(), "fotos");
            if (!carpeta.exists() && !carpeta.mkdirs()) return false;
            File foto = File.createTempFile("foto-", ".jpg", carpeta);
            fotoDeCamara = FileProvider.getUriForFile(this, getPackageName() + ".archivos", foto);
            Intent intento = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            intento.putExtra(MediaStore.EXTRA_OUTPUT, fotoDeCamara);
            intento.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivityForResult(intento, PEDIR_CAMARA);
            return true;
        } catch (IOException | ActivityNotFoundException e) {
            return false;
        }
    }

    private boolean abrirSelector(WebChromeClient.FileChooserParams opciones) {
        boolean soloImagenes = true;
        for (String tipo : opciones.getAcceptTypes()) {
            if (!tipo.isEmpty() && !tipo.startsWith("image/")) soloImagenes = false;
        }
        Intent intento = new Intent(Intent.ACTION_GET_CONTENT);
        intento.addCategory(Intent.CATEGORY_OPENABLE);
        // Los .zip no siempre llevan el mismo tipo; para la copia de seguridad se deja elegir cualquier archivo.
        intento.setType(soloImagenes ? "image/*" : "*/*");
        if (opciones.getMode() == WebChromeClient.FileChooserParams.MODE_OPEN_MULTIPLE) {
            intento.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        }
        try {
            startActivityForResult(intento, PEDIR_ARCHIVO);
            return true;
        } catch (ActivityNotFoundException e) {
            return false;
        }
    }

    @Override
    protected void onActivityResult(int peticion, int resultado, Intent datos) {
        super.onActivityResult(peticion, resultado, datos);
        if (esperandoArchivos == null) return;
        Uri[] elegidos = null;
        if (resultado == RESULT_OK) {
            if (peticion == PEDIR_CAMARA) {
                elegidos = new Uri[]{fotoDeCamara};
            } else if (datos != null) {
                ClipData varios = datos.getClipData();
                if (varios != null) {
                    elegidos = new Uri[varios.getItemCount()];
                    for (int i = 0; i < varios.getItemCount(); i++) elegidos[i] = varios.getItemAt(i).getUri();
                } else if (datos.getData() != null) {
                    elegidos = new Uri[]{datos.getData()};
                }
            }
        }
        esperandoArchivos.onReceiveValue(elegidos);
        esperandoArchivos = null;
    }

    @Override
    protected void onSaveInstanceState(Bundle estado) {
        super.onSaveInstanceState(estado);
        web.saveState(estado);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        web.evaluateJavascript("window.atras ? window.atras() : false", gestionado -> {
            if (!"true".equals(gestionado)) super.onBackPressed();
        });
    }

    /** Lo que la página puede pedirle a Android (window.AppMedidas). */
    private class Puente {
        private final Map<String, Uri> archivos = new HashMap<>();
        private final Map<String, OutputStream> abiertos = new HashMap<>();

        /** Crea el archivo en Descargas/Medidas y devuelve un identificador ("" si falla). */
        @JavascriptInterface
        public synchronized String empezarArchivo(String nombre) {
            try {
                ContentValues valores = new ContentValues();
                valores.put(MediaStore.Downloads.DISPLAY_NAME, nombre);
                valores.put(MediaStore.Downloads.MIME_TYPE, "application/zip");
                valores.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Medidas");
                valores.put(MediaStore.Downloads.IS_PENDING, 1);
                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, valores);
                if (uri == null) return "";
                OutputStream salida = getContentResolver().openOutputStream(uri);
                if (salida == null) return "";
                String id = UUID.randomUUID().toString();
                archivos.put(id, uri);
                abiertos.put(id, salida);
                return id;
            } catch (Exception e) {
                return "";
            }
        }

        /** Añade un trozo (en base64) al archivo. */
        @JavascriptInterface
        public synchronized boolean escribir(String id, String base64) {
            OutputStream salida = abiertos.get(id);
            if (salida == null) return false;
            try {
                salida.write(Base64.decode(base64, Base64.DEFAULT));
                return true;
            } catch (Exception e) {
                return false;
            }
        }

        /** Cierra el archivo y lo deja visible en Descargas. Devuelve su dirección ("" si falla). */
        @JavascriptInterface
        public synchronized String terminar(String id) {
            OutputStream salida = abiertos.remove(id);
            Uri uri = archivos.remove(id);
            if (salida == null || uri == null) return "";
            try {
                salida.close();
                ContentValues valores = new ContentValues();
                valores.put(MediaStore.Downloads.IS_PENDING, 0);
                getContentResolver().update(uri, valores, null, null);
                return uri.toString();
            } catch (Exception e) {
                getContentResolver().delete(uri, null, null);
                return "";
            }
        }

        /** Descarta un archivo a medias. */
        @JavascriptInterface
        public synchronized void cancelar(String id) {
            OutputStream salida = abiertos.remove(id);
            Uri uri = archivos.remove(id);
            try {
                if (salida != null) salida.close();
            } catch (IOException ignorada) {
                // Se borra igualmente.
            }
            if (uri != null) getContentResolver().delete(uri, null, null);
        }

        /** Abre el menú de "Enviar" de Android con la copia (correo, Drive, Bluetooth...). */
        @JavascriptInterface
        public boolean compartir(String direccion) {
            try {
                Intent enviar = new Intent(Intent.ACTION_SEND);
                enviar.setType("application/zip");
                enviar.putExtra(Intent.EXTRA_STREAM, Uri.parse(direccion));
                enviar.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                startActivity(Intent.createChooser(enviar, "Enviar la copia de seguridad"));
                return true;
            } catch (Exception e) {
                return false;
            }
        }
    }
}
