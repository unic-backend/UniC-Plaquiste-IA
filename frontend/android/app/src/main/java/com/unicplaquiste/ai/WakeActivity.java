package com.unicplaquiste.ai;

import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.view.WindowManager;

import com.getcapacitor.BridgeActivity;

/**
 * Écran ouvert par « Hey UniC » : s'affiche par-dessus l'écran verrouillé et ouvre directement UniC vocal.
 * Il ne donne accès à rien d'autre : le téléphone reste verrouillé derrière.
 */
public class WakeActivity extends BridgeActivity {
    /** Vrai tant que cet écran est ouvert : la page sait qu'elle est en mode « téléphone verrouillé / mains libres ». */
    static volatile boolean active;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(UnicPhonePlugin.class);
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        active = true;
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
    }

    /** Fin de la conversation : on ferme l'écran et on remet l'écoute du mot d'appel. */
    void finishAndResume() {
        runOnUiThread(() -> {
            finishAndRemoveTask();
            if (UnicWakeService.enabled(this)) {
                Intent i = new Intent(this, UnicWakeService.class).setAction(UnicWakeService.ACTION_RESUME);
                try {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(i);
                    else startService(i);
                } catch (Exception ignored) { /* repris au prochain démarrage */ }
            }
        });
    }

    @Override
    public void onDestroy() {
        active = false;
        super.onDestroy();
    }
}
