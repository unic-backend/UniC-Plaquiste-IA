package com.unicplaquiste.ai;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.content.res.AssetManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;

import androidx.core.app.NotificationCompat;

import org.vosk.Model;
import org.vosk.Recognizer;
import org.vosk.android.RecognitionListener;
import org.vosk.android.SpeechService;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * « Hey UniC » : écoute SEULEMENT le mot d'appel, sur le téléphone, sans rien enregistrer ni envoyer.
 * Le moteur (Vosk) ne connaît que quelques phrases (« hé unique »…) ; tout le reste est ignoré tout de suite.
 * Au mot d'appel : le micro est libéré et l'écran UniC vocal s'ouvre (par-dessus l'écran verrouillé si besoin).
 */
public class UnicWakeService extends Service implements RecognitionListener {

    static final String ACTION_STOP = "com.unicplaquiste.ai.WAKE_STOP";
    static final String ACTION_RESUME = "com.unicplaquiste.ai.WAKE_RESUME";
    static final String PREFS = "unic.wake";
    static final String KEY_ENABLED = "enabled";
    private static final String CHANNEL = "unic_wake";
    private static final String CHANNEL_CALL = "unic_wake_call";
    private static final int NOTIF_ID = 4101;
    private static final int NOTIF_CALL_ID = 4102;
    private static final String MODEL_ASSET = "model-fr";
    private static final double MIN_CONF = 0.6;
    private static final long COOLDOWN_MS = 2500;

    /** État lisible par la page : off | loading | listening | busy | missing | error. */
    static volatile String state = "off";

    private Model model;
    private SpeechService speech;
    private PowerManager.WakeLock cpu;
    private final Handler main = new Handler(Looper.getMainLooper());
    private volatile boolean stopped;
    private long lastWake;

    static boolean modelBundled(Context c) {
        try {
            String[] l = c.getAssets().list(MODEL_ASSET);
            return l != null && l.length > 0;
        } catch (Exception e) {
            return false;
        }
    }

    static boolean enabled(Context c) {
        return c.getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean(KEY_ENABLED, false);
    }

    static void setEnabled(Context c, boolean on) {
        c.getSharedPreferences(PREFS, MODE_PRIVATE).edit().putBoolean(KEY_ENABLED, on).apply();
    }

    static boolean start(Context c) {
        try {
            Intent i = new Intent(c, UnicWakeService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) c.startForegroundService(i);
            else c.startService(i);
            return true;
        } catch (Exception e) {   // Android refuse un démarrage en arrière-plan
            return false;
        }
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, UnicWakeService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        if (pm != null) {
            cpu = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "unic:wake");
            cpu.setReferenceCounted(false);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_STOP.equals(action)) {
            setEnabled(this, false);
            stopSelf();
            return START_NOT_STICKY;
        }
        try {
            goForeground("Dis « Hey UniC » pour me parler");
        } catch (Throwable e) {   // Android refuse le micro en arrière-plan : on s'arrête proprement au lieu de planter l'appli
            state = "error";
            stopSelf();
            return START_NOT_STICKY;
        }
        if (ACTION_RESUME.equals(action)) {
            state = "loading";
            main.postDelayed(this::listen, 600);
        } else if (speech == null) {
            state = "loading";
            new Thread(this::prepareAndListen, "unic-wake-init").start();
        }
        return START_NOT_STICKY;   // jamais relancé tout seul en arrière-plan (Android interdit alors le micro et ferait planter l'appli)
    }

    private void goForeground(String text) {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Hey UniC (écoute)", NotificationManager.IMPORTANCE_LOW));
        }
        Intent stop = new Intent(this, UnicWakeService.class).setAction(ACTION_STOP);
        PendingIntent stopPi = PendingIntent.getService(this, 1, stop, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification n = new NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("UniC écoute le mot d'appel")
            .setContentText(text)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .addAction(0, "Arrêter", stopPi)
            .build();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else {
            startForeground(NOTIF_ID, n);
        }
    }

    // ---------- moteur ----------

    private void prepareAndListen() {
        try {
            if (!modelBundled(this)) {
                state = "missing";
                stopSelf();
                return;
            }
            File dir = new File(getFilesDir(), MODEL_ASSET);
            File ok = new File(dir, ".ok");
            if (!ok.exists()) {
                deleteTree(dir);
                copyAssets(getAssets(), MODEL_ASSET, dir);
                if (!ok.createNewFile()) throw new IllegalStateException("marker");
            }
            model = new Model(dir.getAbsolutePath());
            main.post(this::listen);
        } catch (Throwable e) {
            state = "error";
            stopSelf();
        }
    }

    private void listen() {
        if (stopped || model == null || "busy".equals(state)) return;   // UniC est ouvert : le micro est à lui
        try {
            if (speech != null) { speech.shutdown(); speech = null; }
            Recognizer rec = new Recognizer(model, 16000f, WakeMatcher.grammarJson());
            speech = new SpeechService(rec, 16000f);
            speech.startListening(this);
            state = "listening";
            if (cpu != null && !cpu.isHeld()) cpu.acquire();
        } catch (Throwable e) {
            state = "error";
            stopSelf();
        }
    }

    private void releaseMic() {
        if (speech != null) {
            try { speech.shutdown(); } catch (Throwable ignored) { /* déjà arrêté */ }
            speech = null;
        }
        if (cpu != null && cpu.isHeld()) cpu.release();
    }

    @Override
    public void onPartialResult(String hypothesis) {
        if ("busy".equals(state)) return;
        if (WakeMatcher.matches(hypothesis, true, MIN_CONF)) onWake();
    }

    @Override
    public void onResult(String hypothesis) {
        if ("busy".equals(state)) return;
        if (WakeMatcher.matches(hypothesis, false, MIN_CONF)) onWake();
    }

    @Override
    public void onFinalResult(String hypothesis) { /* rien : seul le mot d'appel compte */ }

    @Override
    public void onError(Exception e) {
        if ("busy".equals(state) || stopped) return;   // arrêt voulu (UniC ouvert) : pas de réessai, le micro n'est pas à nous
        state = "error";
        main.postDelayed(this::listen, 3000);   // micro pris par un appel, etc. : on réessaie
    }

    @Override
    public void onTimeout() { /* l'écoute continue */ }

    // ---------- réveil ----------

    private void onWake() {
        long now = System.currentTimeMillis();
        if (now - lastWake < COOLDOWN_MS) return;
        lastWake = now;
        main.post(() -> {
            releaseMic();   // le micro est libre pour l'écran UniC vocal
            state = "busy";
            buzz();
            openUnic();
        });
    }

    private void buzz() {
        try {
            Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (v != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) v.vibrate(VibrationEffect.createOneShot(120, VibrationEffect.DEFAULT_AMPLITUDE));
        } catch (Exception ignored) { /* pas de vibreur */ }
    }

    private void openUnic() {
        Intent i = new Intent(this, WakeActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        boolean direct = Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || Settings.canDrawOverlays(this);
        if (direct) {
            try {
                startActivity(i);
                return;
            } catch (Exception ignored) { /* repli : notification plein écran */ }
        }
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL_CALL, "Hey UniC (appel)", NotificationManager.IMPORTANCE_HIGH));
        }
        PendingIntent pi = PendingIntent.getActivity(this, 2, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        nm.notify(NOTIF_CALL_ID, new NotificationCompat.Builder(this, CHANNEL_CALL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("UniC t'écoute")
            .setContentText("Touche pour parler")
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setAutoCancel(true)
            .setContentIntent(pi)
            .setFullScreenIntent(pi, true)
            .build());
    }

    @Override
    public void onDestroy() {
        stopped = true;
        releaseMic();
        if (model != null) { try { model.close(); } catch (Throwable ignored) { /* déjà fermé */ } model = null; }
        if (!"missing".equals(state) && !"error".equals(state)) state = "off";
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    // ---------- fichiers ----------

    private static void copyAssets(AssetManager am, String path, File to) throws Exception {
        String[] kids = am.list(path);
        if (kids != null && kids.length > 0) {
            if (!to.exists() && !to.mkdirs()) throw new IllegalStateException("mkdir");
            for (String k : kids) copyAssets(am, path + "/" + k, new File(to, k));
            return;
        }
        try (InputStream in = am.open(path); OutputStream out = new FileOutputStream(to)) {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        }
    }

    private static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteTree(k);
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }
}
