package com.unicplaquiste.ai;

import android.app.Application;
import android.content.SharedPreferences;

import java.io.PrintWriter;
import java.io.StringWriter;

/** Garde la trace du dernier plantage (affichée dans Voix) : sans elle, on ne peut pas savoir pourquoi l'appli s'est arrêtée. */
public class UnicApp extends Application {
    static final String PREFS = "unic.crash";

    @Override
    public void onCreate() {
        super.onCreate();
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
            try {
                StringWriter sw = new StringWriter();
                e.printStackTrace(new PrintWriter(sw));
                String text = sw.toString();
                if (text.length() > 3500) text = text.substring(0, 3500);
                getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                    .putString("text", "Fil : " + t.getName() + "\n" + text)
                    .putLong("time", System.currentTimeMillis()).commit();
            } catch (Throwable ignored) { /* on ne masque jamais le vrai plantage */ }
            if (previous != null) previous.uncaughtException(t, e);
        });
    }

    static SharedPreferences prefs(android.content.Context c) {
        return c.getSharedPreferences(PREFS, MODE_PRIVATE);
    }
}
