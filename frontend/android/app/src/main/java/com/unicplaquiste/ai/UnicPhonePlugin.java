package com.unicplaquiste.ai;

import android.Manifest;
import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
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
        @Permission(strings = {Manifest.permission.SEND_SMS}, alias = "sms")
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

    private static String cleanNumber(String raw) {
        return raw == null ? "" : raw.replaceAll("[^0-9+]", "");
    }
}
