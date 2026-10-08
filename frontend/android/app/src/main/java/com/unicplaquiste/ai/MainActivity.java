package com.unicplaquiste.ai;

import android.content.res.Configuration;
import android.webkit.WebView;

import androidx.activity.OnBackPressedCallback;

import com.getcapacitor.BridgeActivity;

/**
 * Thème « Auto » : suit le mode jour/nuit du téléphone, même quand il change pendant que l'appli est ouverte.
 * L'activité ne redémarre pas sur un changement de mode (configChanges="uiMode") : on prévient la page nous-mêmes.
 */
public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(android.os.Bundle savedInstanceState) {
        registerPlugin(UnicPhonePlugin.class);   // appels, SMS et contacts pour UniC vocal
        super.onCreate(savedInstanceState);
        installBackHandler();
    }

    /**
     * Retour du téléphone (bouton ou geste) : la page décide. Elle remonte d'un écran, ferme un menu ou un panneau ;
     * seulement depuis l'accueil, l'appli passe en arrière-plan. Sans ça, Android fermait l'appli à chaque retour.
     */
    private void installBackHandler() {
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                final WebView web = getBridge() == null ? null : getBridge().getWebView();
                if (web == null) {
                    moveTaskToBack(true);
                    return;
                }
                web.evaluateJavascript(
                    "(function(){try{return window.__unicBack?window.__unicBack():false}catch(e){return false}})()",
                    value -> {
                        if (!"true".equals(value)) moveTaskToBack(true);
                    });
            }
        });
    }

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
