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
import android.os.PowerManager;
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

    private static String cleanNumber(String raw) {
        return raw == null ? "" : raw.replaceAll("[^0-9+]", "");
    }
}
