package com.unicplaquiste.ai;

import android.content.res.Configuration;
import android.webkit.WebView;

import com.getcapacitor.BridgeActivity;

/**
 * Thème « Auto » : suit le mode jour/nuit du téléphone, même quand il change pendant que l'appli est ouverte.
 * L'activité ne redémarre pas sur un changement de mode (configChanges="uiMode") : on prévient la page nous-mêmes.
 */
public class MainActivity extends BridgeActivity {

    private boolean isNight() {
        int mode = getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
        return mode == Configuration.UI_MODE_NIGHT_YES;
    }

    private void pushNightMode() {
        if (getBridge() == null) return;
        final WebView web = getBridge().getWebView();
        if (web == null) return;
        final String js = "window.__unicSetNight && window.__unicSetNight(" + isNight() + ")";
        web.post(() -> web.evaluateJavascript(js, null));
        web.postDelayed(() -> web.evaluateJavascript(js, null), 1500);   // page encore en chargement au démarrage
    }

    @Override
    public void onResume() {
        super.onResume();
        pushNightMode();
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        pushNightMode();
    }
}
