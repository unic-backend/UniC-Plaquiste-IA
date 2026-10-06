package com.unicplaquiste.ai;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class WakeMatcherTest {
    private static String fin(String text, double conf, String word) {
        return "{\"result\":[{\"conf\":" + conf + ",\"end\":1.2,\"start\":0.6,\"word\":\"" + word + "\"}],\"text\":\"" + text + "\"}";
    }

    @Test public void appelCompletDeclencheMemeEnProvisoire() {
        assertTrue(WakeMatcher.matches("{\"partial\":\"hé unique\"}", true, 0.6));
        assertTrue(WakeMatcher.matches("{\"partial\" : \"ok unique\"}", true, 0.6));
    }

    @Test public void uniqueSeulNeDeclenchePasEnProvisoire() {
        assertFalse(WakeMatcher.matches("{\"partial\":\"unique\"}", true, 0.6));
    }

    @Test public void uniqueSeulDeclencheEnFinalSiSur() {
        assertTrue(WakeMatcher.matches(fin("unique", 0.93, "unique"), false, 0.6));
        assertFalse(WakeMatcher.matches(fin("unique", 0.31, "unique"), false, 0.6));
    }

    @Test public void appelCompletEnFinalExigeAussiLaConfiance() {
        assertTrue(WakeMatcher.matches("{\"text\":\"hé unique\",\"result\":[{\"conf\":0.9,\"word\":\"unique\"}]}", false, 0.6));
        assertFalse(WakeMatcher.matches("{\"text\":\"hé unique\",\"result\":[{\"conf\":0.2,\"word\":\"unique\"}]}", false, 0.6));
    }

    @Test public void resteDeLaParoleNeDeclenchePas() {
        assertFalse(WakeMatcher.matches("{\"text\":\"\"}", false, 0.6));
        assertFalse(WakeMatcher.matches("{\"text\":\"[unk]\"}", false, 0.6));
        assertFalse(WakeMatcher.matches("{\"partial\":\"\"}", true, 0.6));
        assertFalse(WakeMatcher.matches(null, false, 0.6));
        assertFalse(WakeMatcher.matches("{\"text\":\"uniquement\"}", false, 0.6));
    }

    @Test public void grammaireFermeeContientLesPhrasesEtInconnu() {
        String g = WakeMatcher.grammarJson();
        assertTrue(g.startsWith("[") && g.endsWith("]") && g.contains("\"hé unique\"") && g.contains("\"[unk]\""));
    }
}
