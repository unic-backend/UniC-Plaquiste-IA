package com.unicplaquiste.ai;

import android.app.Notification;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Parcelable;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import java.util.ArrayList;
import java.util.List;

/**
 * Garde en mémoire (sur le téléphone seulement) les dernières notifications reçues, téléphone verrouillé ou non,
 * pour que UniC vocal puisse dire « qu'est-ce que j'ai reçu » et lire un message à voix haute.
 * Rien n'est envoyé au serveur. L'accès doit être accordé par le patron : Réglages › Accès aux notifications.
 */
public class UnicNotificationService extends NotificationListenerService {

    public static class Item {
        public String key, pkg, app, title, text, category;
        public long time;
        public boolean removed;
    }

    private static final int MAX_ITEMS = 80;
    private static final long KEEP_MS = 24L * 3600 * 1000;
    private static final List<Item> ITEMS = new ArrayList<>();

    /** Copie des notifications des dernières 24 h, la plus récente en premier. */
    public static synchronized List<Item> snapshot(boolean includeRemoved) {
        long limit = System.currentTimeMillis() - KEEP_MS;
        List<Item> out = new ArrayList<>();
        for (int i = ITEMS.size() - 1; i >= 0; i--) {
            Item it = ITEMS.get(i);
            if (it.time < limit) continue;
            if (it.removed && !includeRemoved) continue;
            out.add(it);
        }
        return out;
    }

    private static synchronized void put(Item item) {
        for (int i = 0; i < ITEMS.size(); i++) {
            if (ITEMS.get(i).key.equals(item.key)) { ITEMS.remove(i); break; }   // mise à jour d'une conversation : on garde la plus récente
        }
        ITEMS.add(item);
        while (ITEMS.size() > MAX_ITEMS) ITEMS.remove(0);
    }

    private static synchronized void markRemoved(String key) {
        for (Item it : ITEMS) if (it.key.equals(key)) it.removed = true;
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            if (sbn == null || sbn.getNotification() == null || getPackageName().equals(sbn.getPackageName())) return;
            Notification n = sbn.getNotification();
            if ((n.flags & Notification.FLAG_GROUP_SUMMARY) != 0) return;     // résumé de groupe : doublon
            if ((n.flags & Notification.FLAG_ONGOING_EVENT) != 0) return;      // lecteur de musique, appel en cours…
            Bundle ex = n.extras;
            if (ex == null) return;
            Item it = new Item();
            it.key = sbn.getKey();
            it.pkg = sbn.getPackageName();
            it.app = appLabel(it.pkg);
            it.category = n.category == null ? "" : n.category;
            it.time = sbn.getPostTime();
            it.title = str(ex.getCharSequence(Notification.EXTRA_TITLE));
            it.text = bestText(ex);
            if (it.title.isEmpty() && it.text.isEmpty()) return;
            put(it);
        } catch (Exception ignored) {
            // une notification illisible ne doit jamais faire tomber le service
        }
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
        if (sbn != null) markRemoved(sbn.getKey());
    }

    private String appLabel(String pkg) {
        try {
            PackageManager pm = getPackageManager();
            ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
            CharSequence label = pm.getApplicationLabel(ai);
            return label == null ? pkg : label.toString();
        } catch (Exception e) {
            return pkg;
        }
    }

    private static String str(CharSequence c) {
        return c == null ? "" : c.toString().trim();
    }

    /** Dernier message d'une conversation (style messagerie), sinon le texte long, sinon le texte court. */
    private static String bestText(Bundle ex) {
        Parcelable[] msgs = ex.getParcelableArray(Notification.EXTRA_MESSAGES);
        if (msgs != null && msgs.length > 0 && msgs[msgs.length - 1] instanceof Bundle) {
            String t = str(((Bundle) msgs[msgs.length - 1]).getCharSequence("text"));
            if (!t.isEmpty()) return t;
        }
        String big = str(ex.getCharSequence(Notification.EXTRA_BIG_TEXT));
        if (!big.isEmpty()) return big;
        CharSequence[] lines = ex.getCharSequenceArray(Notification.EXTRA_TEXT_LINES);
        if (lines != null && lines.length > 0) return str(lines[lines.length - 1]);
        return str(ex.getCharSequence(Notification.EXTRA_TEXT));
    }
}
