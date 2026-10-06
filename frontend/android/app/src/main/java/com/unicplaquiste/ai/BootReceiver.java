package com.unicplaquiste.ai;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Après un redémarrage du téléphone : remet l'écoute de « Hey UniC » si le patron l'avait activée. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        if (UnicWakeService.enabled(context)) UnicWakeService.start(context);
    }
}
