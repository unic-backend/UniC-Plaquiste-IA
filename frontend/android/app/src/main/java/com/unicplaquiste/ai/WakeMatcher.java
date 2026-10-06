package com.unicplaquiste.ai;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Décide si ce que le moteur de mots-clés a entendu est « Hey UniC ».
 * « UniC » se prononce comme le mot français « unique » : c'est ce mot que le moteur cherche (il existe dans son vocabulaire).
 * Pur et sans Android : testable seul.
 */
final class WakeMatcher {
    private WakeMatcher() {}

    /** Mots d'appel qui précèdent « unique » : « hé unique », « ok unique »… */
    static final String[] PHRASES = {"hé unique", "hey unique", "ok unique", "salut unique", "dis unique", "unique"};

    private static final Pattern TEXT = Pattern.compile("\"(?:text|partial)\"\\s*:\\s*\"([^\"]*)\"");
    private static final Pattern CONF = Pattern.compile("\"conf\"\\s*:\\s*([0-9.]+)\\s*,[^}]*\"word\"\\s*:\\s*\"unique\"|\"word\"\\s*:\\s*\"unique\"[^}]*\"conf\"\\s*:\\s*([0-9.]+)");
    private static final Pattern CALL = Pattern.compile("(^|\\s)(hé|hey|he|ok|okay|salut|dis|oh)\\s+unique(\\s|$)");
    private static final Pattern BARE = Pattern.compile("(^|\\s)unique(\\s|$)");

    /** Le texte entendu dans un résultat JSON de Vosk (« partial » ou « text »), sinon une chaîne vide. */
    static String textOf(String json) {
        if (json == null) return "";
        Matcher m = TEXT.matcher(json);
        return m.find() ? m.group(1).trim().toLowerCase() : "";
    }

    /**
     * partial=true : résultat provisoire, on ne déclenche que sur l'appel complet (« hé unique ») pour réagir vite sans fausse alerte.
     * partial=false : résultat final, « unique » seul suffit s'il est sûr à au moins minConf (0 à 1).
     */
    static boolean matches(String json, boolean partial, double minConf) {
        String text = textOf(json);
        if (text.isEmpty()) return false;
        if (CALL.matcher(text).find()) return partial || confOk(json, minConf);
        if (partial) return false;
        return BARE.matcher(text).find() && confOk(json, minConf);
    }

    private static boolean confOk(String json, double minConf) {
        Matcher m = CONF.matcher(json);
        if (!m.find()) return true;   // pas de confiance fournie : on se fie au texte
        String v = m.group(1) != null ? m.group(1) : m.group(2);
        try {
            return Double.parseDouble(v) >= minConf;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    /** Grammaire fermée donnée au moteur : seulement ces phrases (le reste devient [unk]). */
    static String grammarJson() {
        StringBuilder sb = new StringBuilder("[");
        for (String p : PHRASES) sb.append("\"").append(p).append("\", ");
        return sb.append("\"[unk]\"]").toString();
    }
}
