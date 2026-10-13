package com.unicplaquiste.ai;

import android.Manifest;
import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.os.Build;
import android.telecom.TelecomManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.provider.ContactsContract;
import android.provider.Settings;
import android.telephony.SmsManager;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import androidx.core.app.NotificationManagerCompat;

import java.util.ArrayList;
import java.util.List;
import java.util.HashSet;
import java.util.Set;

/**
 * Tâches du téléphone pour UniC vocal : lire les contacts, appeler, envoyer un SMS.
 * Rien n'est fait ici sans que la page l'ait demandé APRÈS le « oui » vocal du patron.
 * Les contacts restent sur le téléphone (jamais envoyés au serveur).
 */
@CapacitorPlugin(
    name = "UnicPhone",
    permissions = {
        @Permission(strings = {Manifest.permission.READ_CONTACTS}, alias = "contacts"),
        @Permission(strings = {Manifest.permission.CALL_PHONE}, alias = "call"),
        @Permission(strings = {Manifest.permission.SEND_SMS}, alias = "sms"),
        @Permission(strings = {Manifest.permission.RECORD_AUDIO}, alias = "mic"),
        @Permission(strings = {Manifest.permission.ANSWER_PHONE_CALLS}, alias = "answer")
    }
)
public class UnicPhonePlugin extends Plugin {

    private static final int MAX_CONTACTS = 5000;
    private static final int MAX_SMS_CHARS = 1000;

    // ---------- contacts ----------

    @PluginMethod
    public void listContacts(PluginCall call) {
        if (getPermissionState("contacts") != PermissionState.GRANTED) {
            requestPermissionForAlias("contacts", call, "contactsPermission");
            return;
        }
        readContacts(call);
    }

    @PermissionCallback
    private void contactsPermission(PluginCall call) {
        if (getPermissionState("contacts") == PermissionState.GRANTED) readContacts(call);
        else call.reject("Accès aux contacts refusé : autorise-le dans Réglages › Applis › UniC AI › Autorisations.");
    }

    private void readContacts(PluginCall call) {
        JSArray out = new JSArray();
        Set<String> seen = new HashSet<>();
        String[] cols = {ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME, ContactsContract.CommonDataKinds.Phone.NUMBER};
        try (Cursor c = getContext().getContentResolver().query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI, cols, null, null,
            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " ASC")) {
            if (c != null) {
                while (c.moveToNext() && out.length() < MAX_CONTACTS) {
                    String name = c.getString(0);
                    String number = c.getString(1);
                    if (name == null || number == null) continue;
                    String key = name + "|" + number.replaceAll("[^0-9+]", "");
                    if (!seen.add(key)) continue;
                    JSObject o = new JSObject();
                    o.put("name", name);
                    o.put("number", number);
                    out.put(o);
                }
            }
        } catch (Exception e) {
            call.reject("Lecture des contacts impossible.");
            return;
        }
        JSObject res = new JSObject();
        res.put("contacts", out);
        call.resolve(res);
    }

    // ---------- appel ----------

    @PluginMethod
    public void call(PluginCall call) {
        String number = cleanNumber(call.getString("number"));
        if (number.isEmpty()) {
            call.reject("Numéro invalide.");
            return;
        }
        if (getPermissionState("call") != PermissionState.GRANTED) {
            requestPermissionForAlias("call", call, "callPermission");
            return;
        }
        placeCall(call, number);
    }

    @PermissionCallback
    private void callPermission(PluginCall call) {
        String number = cleanNumber(call.getString("number"));
        if (getPermissionState("call") == PermissionState.GRANTED) {
            placeCall(call, number);
        } else {
            dial(call, number);   // sans l'autorisation : le clavier téléphonique s'ouvre avec le numéro, un toucher appelle
        }
    }

    private void placeCall(PluginCall call, String number) {
        try {
            Intent i = new Intent(Intent.ACTION_CALL, Uri.parse("tel:" + Uri.encode(number)));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
            call.resolve();
        } catch (Exception e) {
            call.reject("Appel impossible.");
        }
    }

    private void dial(PluginCall call, String number) {
        try {
            Intent i = new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(number)));
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
            JSObject res = new JSObject();
            res.put("dialedOnly", true);
            call.resolve(res);
        } catch (Exception e) {
            call.reject("Appel impossible.");
        }
    }

    // ---------- SMS ----------

    @PluginMethod
    public void sendSms(PluginCall call) {
        String number = cleanNumber(call.getString("number"));
        String text = call.getString("text");
        if (number.isEmpty() || text == null || text.trim().isEmpty()) {
            call.reject("Numéro ou message manquant.");
            return;
        }
        if (text.length() > MAX_SMS_CHARS) {
            call.reject("Message trop long.");
            return;
        }
        if (Boolean.TRUE.equals(call.getBoolean("composer", false))) {   // « prépare un SMS » : texte prêt dans Messages, jamais envoyé ici
            openComposer(call, number, text.trim());
            return;
        }
        if (getPermissionState("sms") != PermissionState.GRANTED) {
            requestPermissionForAlias("sms", call, "smsPermission");
            return;
        }
        sendNow(call, number, text.trim());
    }

    @PermissionCallback
    private void smsPermission(PluginCall call) {
        if (getPermissionState("sms") == PermissionState.GRANTED) {
            sendNow(call, cleanNumber(call.getString("number")), call.getString("text").trim());
        } else {
            openComposer(call, cleanNumber(call.getString("number")), call.getString("text").trim());   // plan B : le patron touche « Envoyer »
        }
    }

    /** Sans l'autorisation SMS (Android la bloque pour une appli installée à la main) : l'appli Messages s'ouvre, texte prêt. */
    private void openComposer(PluginCall call, String number, String text) {
        try {
            Intent i = new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(number)));
            i.putExtra("sms_body", text);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
            JSObject res = new JSObject();
            res.put("composerOnly", true);
            call.resolve(res);
        } catch (Exception e) {
            call.reject("Envoi du SMS impossible.");
        }
    }

    private void sendNow(PluginCall call, String number, String text) {
        try {
            SmsManager sms = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                ? getContext().getSystemService(SmsManager.class)
                : SmsManager.getDefault();
            ArrayList<String> parts = sms.divideMessage(text);
            sms.sendMultipartTextMessage(number, null, parts, null, null);
            call.resolve();
        } catch (Exception e) {
            call.reject("Envoi du SMS impossible.");
        }
    }

    // ---------- notifications (lecture à voix haute) ----------

    @PluginMethod
    public void notificationAccess(PluginCall call) {
        boolean on = NotificationManagerCompat.getEnabledListenerPackages(getContext()).contains(getContext().getPackageName());
        JSObject res = new JSObject();
        res.put("enabled", on);
        call.resolve(res);
    }

    @PluginMethod
    public void openNotificationSettings(PluginCall call) {
        try {
            Intent i = new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
            call.resolve();
        } catch (Exception e) {
            call.reject("Réglages indisponibles.");
        }
    }

    @PluginMethod
    public void listNotifications(PluginCall call) {
        JSArray out = new JSArray();
        List<UnicNotificationService.Item> items = UnicNotificationService.snapshot(true);
        for (UnicNotificationService.Item it : items) {
            JSObject o = new JSObject();
            o.put("id", it.key);
            o.put("pkg", it.pkg);
            o.put("app", it.app);
            o.put("title", it.title);
            o.put("text", it.text);
            o.put("category", it.category);
            o.put("time", it.time);
            o.put("removed", it.removed);
            out.put(o);
        }
        JSObject res = new JSObject();
        res.put("notifications", out);
        call.resolve(res);
    }

    @PluginMethod
    public void isLocked(PluginCall call) {
        KeyguardManager km = (KeyguardManager) getContext().getSystemService(Context.KEYGUARD_SERVICE);
        JSObject res = new JSObject();
        res.put("locked", km != null && km.isKeyguardLocked());
        call.resolve(res);
    }

    /** L'écran UniC vocal peut s'afficher par-dessus l'écran de verrouillage tant qu'il est ouvert (jamais le reste de l'appli). */
    @PluginMethod
    public void setLockScreenMode(PluginCall call) {
        final boolean on = Boolean.TRUE.equals(call.getBoolean("on", false));
        final Activity act = getActivity();
        if (act == null) {
            call.resolve();
            return;
        }
        act.runOnUiThread(() -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
                act.setShowWhenLocked(on);
                act.setTurnScreenOn(on);
            }
            call.resolve();
        });
    }

    // ---------- « Hey UniC » (mot d'appel) ----------

    private JSObject wakeInfo() {
        Context c = getContext();
        PowerManager pm = (PowerManager) c.getSystemService(Context.POWER_SERVICE);
        JSObject res = new JSObject();
        res.put("enabled", UnicWakeService.enabled(c));
        res.put("state", UnicWakeService.state);
        res.put("modelBundled", UnicWakeService.modelBundled(c));
        res.put("overlay", Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(c));
        res.put("battery", pm != null && pm.isIgnoringBatteryOptimizations(c.getPackageName()));
        res.put("mic", getPermissionState("mic") == PermissionState.GRANTED);
        return res;
    }

    @PluginMethod
    public void wakeStatus(PluginCall call) {
        call.resolve(wakeInfo());
    }

    @PluginMethod
    public void startWake(PluginCall call) {
        if (!UnicWakeService.modelBundled(getContext())) {
            call.reject("Cette version n'embarque pas le moteur du mot d'appel.");
            return;
        }
        if (getPermissionState("mic") != PermissionState.GRANTED) {
            requestPermissionForAlias("mic", call, "wakeMicPermission");
            return;
        }
        launchWake(call);
    }

    @PermissionCallback
    private void wakeMicPermission(PluginCall call) {
        if (getPermissionState("mic") != PermissionState.GRANTED) {
            call.reject("Micro refusé.");
            return;
        }
        launchWake(call);
    }

    private void launchWake(PluginCall call) {
        UnicWakeService.setEnabled(getContext(), true);
        if (!UnicWakeService.start(getContext())) {
            UnicWakeService.setEnabled(getContext(), false);
            call.reject("Android a refusé de lancer l'écoute. Ouvre UniC puis réessaie.");
            return;
        }
        call.resolve(wakeInfo());
    }

    @PluginMethod
    public void stopWake(PluginCall call) {
        UnicWakeService.setEnabled(getContext(), false);
        UnicWakeService.stop(getContext());
        call.resolve(wakeInfo());
    }

    /** L'interprète est ouvert : « Hey UniC » se tait (un mot anglais comme « unique » ne doit pas le réveiller). Le réglage reste « activé ». */
    @PluginMethod
    public void pauseWake(PluginCall call) {
        UnicWakeService.stop(getContext());
        call.resolve();
    }

    @PluginMethod
    public void resumeWake(PluginCall call) {
        if (UnicWakeService.enabled(getContext())) UnicWakeService.start(getContext());
        call.resolve();
    }

    /** L'écran reste allumé pendant l'interprète. */
    @PluginMethod
    public void keepScreenOn(PluginCall call) {
        final boolean on = Boolean.TRUE.equals(call.getBoolean("on", false));
        final Activity act = getActivity();
        if (act != null) {
            act.runOnUiThread(() -> {
                if (on) act.getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                else act.getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            });
        }
        call.resolve();
    }

    @PluginMethod
    public void openOverlaySettings(PluginCall call) {
        openSettings(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getContext().getPackageName())), call);
    }

    @PluginMethod
    public void openBatterySettings(PluginCall call) {
        openSettings(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + getContext().getPackageName())), call);
    }

    private void openSettings(Intent i, PluginCall call) {
        try {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(i);
            call.resolve();
        } catch (Exception e) {
            call.reject("Réglages indisponibles.");
        }
    }

    /** Vrai quand la page a été ouverte par « Hey UniC » (écran verrouillé possible). */
    @PluginMethod
    public void launchMode(PluginCall call) {
        JSObject res = new JSObject();
        res.put("wake", getActivity() instanceof WakeActivity);
        call.resolve(res);
    }

    /** Fin de la conversation lancée par « Hey UniC » : ferme l'écran, remet l'écoute. */
    @PluginMethod
    public void finishWake(PluginCall call) {
        Activity act = getActivity();
        if (act instanceof WakeActivity) ((WakeActivity) act).finishAndResume();
        call.resolve();
    }

    // ---------- raccrocher, casque Bluetooth ----------

    /** Raccroche l'appel en cours (demandé à voix haute par le patron). */
    @PluginMethod
    public void endCall(PluginCall call) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
            call.reject("Raccrocher par la voix demande Android 9 ou plus.");
            return;
        }
        if (getPermissionState("answer") != PermissionState.GRANTED) {
            requestPermissionForAlias("answer", call, "answerPermission");
            return;
        }
        doEndCall(call);
    }

    @PermissionCallback
    private void answerPermission(PluginCall call) {
        if (getPermissionState("answer") != PermissionState.GRANTED) {
            call.reject("Autorisation refusée : je ne peux pas raccrocher. Raccroche avec le bouton.");
            return;
        }
        doEndCall(call);
    }

    @SuppressWarnings("MissingPermission")
    private void doEndCall(PluginCall call) {
        try {
            TelecomManager tm = (TelecomManager) getContext().getSystemService(Context.TELECOM_SERVICE);
            boolean ended = tm != null && tm.endCall();
            JSObject res = new JSObject();
            res.put("ended", ended);
            call.resolve(res);
        } catch (Exception e) {
            call.reject("Je n'ai pas pu raccrocher.");
        }
    }

    /**
     * Casque / AirPods : si un casque Bluetooth est connecté, le micro passe par lui pendant la conversation
     * (sans cela Android écoute le micro du téléphone). Sans casque : rien ne change.
     */
    @PluginMethod
    @SuppressWarnings("deprecation")
    public void audioRoute(PluginCall call) {
        final boolean on = Boolean.TRUE.equals(call.getBoolean("on", false));
        JSObject res = new JSObject();
        res.put("bluetooth", false);
        try {
            AudioManager am = (AudioManager) getContext().getSystemService(Context.AUDIO_SERVICE);
            if (am == null) { call.resolve(res); return; }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                if (on) {
                    for (AudioDeviceInfo d : am.getAvailableCommunicationDevices()) {
                        if (d.getType() == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || d.getType() == AudioDeviceInfo.TYPE_BLE_HEADSET) {
                            res.put("bluetooth", am.setCommunicationDevice(d));
                            break;
                        }
                    }
                } else {
                    am.clearCommunicationDevice();
                }
            } else if (am.isBluetoothScoAvailableOffCall()) {
                if (on) {
                    am.startBluetoothSco();
                    am.setBluetoothScoOn(true);
                    res.put("bluetooth", am.isBluetoothScoOn());
                } else {
                    am.setBluetoothScoOn(false);
                    am.stopBluetoothSco();
                }
            }
        } catch (Exception ignored) { /* pas de casque ou refus : le micro du téléphone sert */ }
        call.resolve(res);
    }

    // ---------- écoute (dictée) : signaux exacts « micro ouvert » et erreurs visibles ----------

    private SpeechRecognizer recognizer;
    private final Handler ui = new Handler(Looper.getMainLooper());

    /** Ouvre le micro pour UNE phrase. Événements : ready (micro vraiment ouvert), speech, partial, final, error. */
    @PluginMethod
    public void listen(PluginCall call) {
        if (getPermissionState("mic") != PermissionState.GRANTED) {
            requestPermissionForAlias("mic", call, "listenPermission");
            return;
        }
        startListen(call);
    }

    @PermissionCallback
    private void listenPermission(PluginCall call) {
        if (getPermissionState("mic") != PermissionState.GRANTED) {
            call.reject("Micro refusé : autorise-le dans Réglages › Applis › UniC AI › Autorisations.");
            return;
        }
        startListen(call);
    }

    private void startListen(final PluginCall call) {
        final String lang = call.getString("language", "fr-FR");
        ui.post(() -> {
            try {
                destroyRecognizer();
                if (!SpeechRecognizer.isRecognitionAvailable(getContext())) {
                    call.reject("Reconnaissance vocale absente sur ce téléphone.");
                    return;
                }
                recognizer = SpeechRecognizer.createSpeechRecognizer(getContext());
                recognizer.setRecognitionListener(new RecognitionListener() {
                    @Override public void onReadyForSpeech(Bundle p) { emit("ready", null); }
                    @Override public void onBeginningOfSpeech() { emit("speech", null); }
                    @Override public void onRmsChanged(float v) { }
                    @Override public void onBufferReceived(byte[] b) { }
                    @Override public void onEndOfSpeech() { emit("endSpeech", null); }
                    @Override public void onEvent(int t, Bundle p) { }
                    @Override public void onPartialResults(Bundle b) { emit("partial", firstText(b)); }
                    @Override public void onResults(Bundle b) { emit("final", firstText(b)); }
                    @Override public void onError(int code) {
                        JSObject o = new JSObject();
                        o.put("code", code);
                        notifyListeners("error", o);
                    }
                });
                Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang);
                i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
                i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
                // Pause tolérée avant de couper la phrase : par défaut Android ferme le micro après ~1 s de silence (phrases coupées).
                i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2200L);
                i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1800L);
                i.putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, getContext().getPackageName());
                recognizer.startListening(i);
                call.resolve();
            } catch (Exception e) {
                call.reject("Le micro n'a pas pu s'ouvrir.");
            }
        });
    }

    private void emit(String event, String text) {
        JSObject o = new JSObject();
        if (text != null) o.put("text", text);
        notifyListeners(event, o);
    }

    private static String firstText(Bundle b) {
        ArrayList<String> m = b == null ? null : b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        return m == null || m.isEmpty() ? "" : m.get(0);
    }

    private void destroyRecognizer() {
        if (recognizer != null) {
            try { recognizer.cancel(); recognizer.destroy(); } catch (Exception ignored) { /* déjà détruit */ }
            recognizer = null;
        }
    }

    @PluginMethod
    public void stopListen(PluginCall call) {
        ui.post(() -> { destroyRecognizer(); call.resolve(); });
    }

    // ---------- voix de réponse : synthèse vocale d'Android, sortie au choix (haut-parleur ou Bluetooth) ----------
    // La phrase est d'abord synthétisée dans un fichier, puis lue par un MediaPlayer dont la SORTIE est imposée (setPreferredDevice) :
    // sans cela Android envoie le son vers un appareil Bluetooth connecté (écouteurs, montre, voiture), même loin, et le téléphone « parle dans le vide ».

    private static final class Utter {
        final String id, text, lang, output;
        final float rate;
        Utter(String id, String text, float rate, String lang, String output) { this.id = id; this.text = text; this.rate = rate; this.lang = lang; this.output = output; }
    }

    private android.speech.tts.TextToSpeech tts;
    private boolean ttsOk = false;
    private boolean ttsStarting = false;
    private final ArrayList<Utter> ttsQueue = new ArrayList<>();
    private final java.util.HashMap<String, Utter> ttsFiles = new java.util.HashMap<>();   // phrases en cours de synthèse vers un fichier
    private final java.util.HashSet<String> ttsDirect = new java.util.HashSet<>();   // repli : lecture directe du moteur
    private boolean ttsBusy = false;
    private android.media.MediaPlayer player;
    private String playingId;   // phrase en cours de lecture

    private void emitTts(final String event, final String id, final int code) {
        ui.post(() -> {
            JSObject o = new JSObject();
            o.put("id", id);
            o.put("code", code);
            notifyListeners(event, o);
        });
    }

    private static boolean isBluetoothOut(AudioDeviceInfo d) {
        int t = d.getType();
        return t == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP || t == AudioDeviceInfo.TYPE_BLUETOOTH_SCO
                || (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && (t == AudioDeviceInfo.TYPE_BLE_HEADSET || t == AudioDeviceInfo.TYPE_BLE_SPEAKER));
    }

    /** Sortie imposée : « speaker » = haut-parleur du téléphone, « bluetooth » = l'appareil Bluetooth connecté ; « auto » ou introuvable = choix d'Android. */
    private AudioDeviceInfo pickOutput(String output) {
        try {
            AudioManager am = (AudioManager) getContext().getSystemService(Context.AUDIO_SERVICE);
            if (am == null || output == null) return null;
            AudioDeviceInfo sco = null;
            for (AudioDeviceInfo d : am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)) {
                if ("speaker".equals(output) && d.getType() == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER) return d;
                if ("bluetooth".equals(output) && isBluetoothOut(d)) {
                    if (d.getType() == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) sco = d; else return d;
                }
            }
            return sco;
        } catch (Exception e) {
            return null;
        }
    }

    /** Appareil Bluetooth de sortie connecté (nom), pour l'afficher dans UniC vocal. */
    @PluginMethod
    public void audioOutputs(PluginCall call) {
        JSObject res = new JSObject();
        res.put("bluetooth", "");
        try {
            AudioManager am = (AudioManager) getContext().getSystemService(Context.AUDIO_SERVICE);
            if (am != null) {
                for (AudioDeviceInfo d : am.getDevices(AudioManager.GET_DEVICES_OUTPUTS)) {
                    if (isBluetoothOut(d)) {
                        CharSequence n = d.getProductName();
                        res.put("bluetooth", n == null || n.length() == 0 ? "Bluetooth" : n.toString());
                        break;
                    }
                }
                res.put("volume", am.getStreamVolume(AudioManager.STREAM_MUSIC));
            }
        } catch (Exception ignored) { /* pas d'information : on affiche le haut-parleur */ }
        call.resolve(res);
    }

    private void withTts(final Runnable job, final String failId) {
        if (ttsOk && tts != null) { job.run(); return; }
        ttsWaitingJobs.add(new Object[]{failId, job});
        if (ttsStarting) return;
        ttsStarting = true;
        tts = new android.speech.tts.TextToSpeech(getContext().getApplicationContext(), status -> ui.post(() -> {
            ttsStarting = false;
            if (status == android.speech.tts.TextToSpeech.SUCCESS && tts != null) {
                ttsOk = true;
                tts.setOnUtteranceProgressListener(new android.speech.tts.UtteranceProgressListener() {
                    @Override public void onStart(String utteranceId) { }
                    @Override public void onDone(final String utteranceId) { ui.post(() -> ttsSynthDone(utteranceId)); }
                    @Override public void onError(String utteranceId) { ui.post(() -> ttsSynthFailed(utteranceId, -1)); }
                    @Override public void onError(String utteranceId, int errorCode) { ui.post(() -> ttsSynthFailed(utteranceId, errorCode)); }
                });
                for (Object[] w : new ArrayList<>(ttsWaitingJobs)) ((Runnable) w[1]).run();
            } else {
                for (Object[] w : new ArrayList<>(ttsWaitingJobs)) emitTts("ttsError", (String) w[0], -2);
                tts = null;
            }
            ttsWaitingJobs.clear();
        }));
    }
    private final ArrayList<Object[]> ttsWaitingJobs = new ArrayList<>();

    /** Synthèse terminée : lecture du fichier (sortie imposée) ou, en repli, fin de la lecture directe. */
    private void ttsSynthDone(String id) {
        if (ttsDirect.remove(id)) { emitTts("ttsDone", id, 0); ttsBusy = false; ttsNext(); return; }
        Utter u = ttsFiles.remove(id);
        if (u == null) return;
        playFile(u);
    }

    private void ttsSynthFailed(String id, int code) {
        if (ttsDirect.remove(id)) { emitTts("ttsError", id, code); ttsBusy = false; ttsNext(); return; }
        Utter u = ttsFiles.remove(id);
        if (u == null) return;
        // la synthèse vers un fichier a échoué : repli, le moteur parle directement (sortie choisie par Android)
        ttsDirect.add(u.id);
        int r = tts.speak(u.text, android.speech.tts.TextToSpeech.QUEUE_FLUSH, null, u.id);
        if (r != android.speech.tts.TextToSpeech.SUCCESS) { ttsDirect.remove(u.id); emitTts("ttsError", u.id, -3); ttsBusy = false; ttsNext(); }
    }

    private java.io.File ttsFile(String id) {
        return new java.io.File(getContext().getCacheDir(), "tts_" + id.replaceAll("[^A-Za-z0-9_]", "") + ".wav");
    }

    private void playFile(final Utter u) {
        final java.io.File f = ttsFile(u.id);
        try {
            android.media.MediaPlayer mp = new android.media.MediaPlayer();
            player = mp;
            mp.setAudioAttributes(new android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_MEDIA)
                    .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH).build());
            mp.setDataSource(f.getAbsolutePath());
            AudioDeviceInfo dev = pickOutput(u.output);
            if (dev != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) mp.setPreferredDevice(dev);   // sortie imposée (Android 9+) ; avant : choix d'Android
            playingId = u.id;
            takeFocus();
            mp.setOnCompletionListener(m -> { releasePlayer(m); playingId = null; f.delete(); emitTts("ttsDone", u.id, 0); ttsBusy = false; ttsNext(); });
            mp.setOnErrorListener((m, what, extra) -> { releasePlayer(m); playingId = null; f.delete(); emitTts("ttsError", u.id, -5); ttsBusy = false; ttsNext(); return true; });
            mp.setOnPreparedListener(m -> m.start());
            mp.prepareAsync();
        } catch (Exception e) {
            f.delete();
            emitTts("ttsError", u.id, -5);
            ttsBusy = false;
            ttsNext();
        }
    }

    private AudioManager.OnAudioFocusChangeListener focusListener;
    private android.media.AudioFocusRequest focusReq;

    /** Prend la parole « en priorité courte » : la musique se met en pause, et un appel entrant ou une autre appli qui prend le son coupe la voix d'UniC. */
    private void takeFocus() {
        try {
            AudioManager am = (AudioManager) getContext().getSystemService(Context.AUDIO_SERVICE);
            if (am == null || focusListener != null) return;
            focusListener = change -> {
                if (change == AudioManager.AUDIOFOCUS_LOSS || change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) ui.post(this::ttsStopAll);
            };
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                focusReq = new android.media.AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                        .setAudioAttributes(new android.media.AudioAttributes.Builder()
                                .setUsage(android.media.AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                                .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH).build())
                        .setOnAudioFocusChangeListener(focusListener).build();
                am.requestAudioFocus(focusReq);
            } else {
                am.requestAudioFocus(focusListener, AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT);
            }
        } catch (Exception ignored) { /* pas de focus : la voix parle quand même */ }
    }

    private void giveFocus() {
        try {
            AudioManager am = (AudioManager) getContext().getSystemService(Context.AUDIO_SERVICE);
            if (am != null && focusListener != null) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && focusReq != null) am.abandonAudioFocusRequest(focusReq);
                else am.abandonAudioFocus(focusListener);
            }
        } catch (Exception ignored) { /* déjà rendu */ }
        focusListener = null;
        focusReq = null;
    }

    private void releasePlayer(android.media.MediaPlayer m) {
        try { m.release(); } catch (Exception ignored) { /* déjà libéré */ }
        if (player == m) player = null;
    }

    /** Phrase suivante de la file : synthèse dans un fichier. */
    private void ttsNext() {
        if (ttsBusy) return;
        if (ttsQueue.isEmpty()) { giveFocus(); return; }   // plus rien à dire : on rend le son (la musique reprend) ; entre deux phrases on le garde
        final Utter u = ttsQueue.remove(0);
        ttsBusy = true;
        withTts(() -> {
            try {
                java.util.Locale loc = java.util.Locale.forLanguageTag(u.lang);
                if (tts.isLanguageAvailable(loc) < android.speech.tts.TextToSpeech.LANG_AVAILABLE) { emitTts("ttsError", u.id, -4); ttsBusy = false; ttsNext(); return; }
                tts.setLanguage(loc);
                tts.setSpeechRate(u.rate > 0 ? u.rate : 1.0f);
                AudioManager am = (AudioManager) getContext().getSystemService(Context.AUDIO_SERVICE);
                if (am != null && am.getStreamVolume(AudioManager.STREAM_MUSIC) == 0) emitTts("ttsMuted", u.id, 0);   // volume média à zéro : il parle sans aucun son
                ttsFiles.put(u.id, u);
                int r = tts.synthesizeToFile(u.text, new Bundle(), ttsFile(u.id), u.id);
                if (r != android.speech.tts.TextToSpeech.SUCCESS) ttsSynthFailed(u.id, -3);
            } catch (Exception e) {
                ttsFiles.remove(u.id);
                emitTts("ttsError", u.id, -3);
                ttsBusy = false;
                ttsNext();
            }
        }, u.id);
    }

    private void ttsStopAll() {
        for (Utter q : ttsQueue) emitTts("ttsDone", q.id, 0);   // phrases abandonnées : l'écran n'attend plus
        for (String k : ttsFiles.keySet()) emitTts("ttsDone", k, 0);
        for (String k : ttsDirect) emitTts("ttsDone", k, 0);
        if (playingId != null) emitTts("ttsDone", playingId, 0);
        playingId = null;
        ttsQueue.clear();
        ttsFiles.clear();
        ttsDirect.clear();
        ttsBusy = false;
        try { if (player != null) { player.stop(); player.release(); } } catch (Exception ignored) { /* déjà arrêté */ }
        player = null;
        giveFocus();
        try { if (tts != null && ttsOk) tts.stop(); } catch (Exception ignored) { /* déjà arrêté */ }
    }

    /** Dit une phrase. Rend la main tout de suite ; « ttsDone » / « ttsError » (avec l'identifiant) arrivent ensuite. */
    @PluginMethod
    public void speak(final PluginCall call) {
        final String text = call.getString("text", "");
        final String id = call.getString("id", "t" + System.nanoTime());
        final float rate = call.getFloat("rate", 1.0f);
        final String lang = call.getString("lang", "fr-FR");
        final String output = call.getString("output", "auto");
        final boolean flush = Boolean.TRUE.equals(call.getBoolean("flush", false));
        call.resolve();
        ui.post(() -> {
            if (flush) ttsStopAll();
            if (text == null || text.trim().isEmpty()) { emitTts("ttsDone", id, 0); return; }
            ttsQueue.add(new Utter(id, text, rate, lang, output));
            ttsNext();
        });
    }

    @PluginMethod
    public void stopSpeak(PluginCall call) {
        ui.post(() -> { ttsStopAll(); call.resolve(); });
    }

    @Override
    protected void handleOnDestroy() {
        ui.post(this::destroyRecognizer);
        ui.post(() -> { ttsStopAll(); try { if (tts != null) tts.shutdown(); } catch (Exception ignored) { /* déjà fermé */ } tts = null; ttsOk = false; });
        super.handleOnDestroy();
    }

    /** Dernier plantage de l'appli (texte + heure), pour le diagnostic dans Voix. */
    @PluginMethod
    public void lastCrash(PluginCall call) {
        android.content.SharedPreferences sp = UnicApp.prefs(getContext());
        JSObject res = new JSObject();
        res.put("text", sp.getString("text", ""));
        res.put("time", sp.getLong("time", 0));
        call.resolve(res);
    }

    @PluginMethod
    public void clearCrash(PluginCall call) {
        UnicApp.prefs(getContext()).edit().clear().apply();
        call.resolve();
    }

    private static String cleanNumber(String raw) {
        return raw == null ? "" : raw.replaceAll("[^0-9+]", "");
    }
}
