import { apiUrl, getCode, isNative } from "./api";
import { useEffect, useState } from "react";

/** Lecture à voix haute des réponses. Moteurs : voix du téléphone (gratuit) ou voix ElevenLabs (serveur, voix clonée possible). */
export type VoicePref = { engine: "device" | "eleven"; deviceVoice: string; rate: number };
const KEY = "unic.voice";

export function getPref(): VoicePref {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "{}"); return { engine: v.engine === "eleven" ? "eleven" : "device", deviceVoice: v.deviceVoice || "", rate: Number(v.rate) || 1 }; }
  catch { return { engine: "device", deviceVoice: "", rate: 1 }; }
}
export function setPref(p: Partial<VoicePref>): VoicePref {
  const n = { ...getPref(), ...p };
  try { localStorage.setItem(KEY, JSON.stringify(n)); } catch { /* ignoré */ }
  return n;
}

/** Texte lisible : sans Markdown, tableaux, liens ni sources (le serveur nettoie aussi, par sécurité). */
export function speakable(text: string): string {
  return text.split("\n\n**Sources**")[0]
    .replace(/```[\s\S]*?```/g, " ").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/https?:\/\/\S+/g, " ")
    .replace(/^\s*\|.*\|\s*$/gm, " ").replace(/^\s{0,3}#{1,6}\s*/gm, "").replace(/^\s*[-*•]\s+/gm, "")
    .replace(/[*_`>~]+/g, "").replace(/m²|m2/g, " mètres carrés").replace(/FCFA/g, " francs CFA")
    .replace(/\s*\n+\s*/g, ". ").replace(/\s{2,}/g, " ").replace(/\.{2,}/g, ".").trim();
}

type Listener = () => void;
let playing: string | null = null;
let loading: string | null = null;
let audio: HTMLAudioElement | null = null;
const cache = new Map<string, string>();
const listeners = new Set<Listener>();
const emit = () => listeners.forEach((l) => l());

export function stop(): void {
  try { window.speechSynthesis?.cancel(); } catch { /* ignoré */ }
  if (audio) { audio.pause(); audio = null; }
  playing = null; loading = null; emit();
}

export function deviceVoices(): SpeechSynthesisVoice[] {
  try { return (window.speechSynthesis?.getVoices() || []).filter((v) => v.lang.toLowerCase().startsWith("fr")); } catch { return []; }
}

export function speakDevice(text: string, voiceURI = "", rate = 1, onEnd?: () => void): boolean {
  const synth = window.speechSynthesis;
  if (!synth || typeof SpeechSynthesisUtterance === "undefined") return false;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "fr-FR"; u.rate = rate;
  const v = deviceVoices().find((x) => x.voiceURI === voiceURI);
  if (v) u.voice = v;
  u.onend = () => onEnd?.();
  u.onerror = () => onEnd?.();
  synth.speak(u);
  return true;
}

async function elevenBlob(text: string, voiceId = ""): Promise<string> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const code = getCode();
  if (code) headers.set("X-Access-Code", code);
  const res = await fetch(apiUrl("/api/voice/speak"), { method: "POST", headers, body: JSON.stringify({ text, voice_id: voiceId }) });
  if (!res.ok) {
    let d = res.statusText;
    try { d = (await res.json()).detail || d; } catch { /* ignoré */ }
    throw new Error(typeof d === "string" ? d : "Lecture impossible");
  }
  return URL.createObjectURL(await res.blob());
}

/** Lit (ou arrête) le message `id`. Rend un message d'erreur lisible, ou "" si tout va bien. */
export async function toggle(id: string, text: string): Promise<string> {
  if (playing === id || loading === id) { stop(); return ""; }
  stop();
  const pref = getPref();
  const spoken = speakable(text);
  if (!spoken) return "Rien à lire dans ce message.";
  if (pref.engine === "device") {
    playing = id; emit();
    const ok = speakDevice(spoken, pref.deviceVoice, pref.rate, () => { if (playing === id) { playing = null; emit(); } });
    if (!ok) { playing = null; emit(); return "Ce téléphone n'a pas de voix de lecture. Installe « Synthèse vocale Google » dans les réglages Android."; }
    return "";
  }
  loading = id; emit();
  try {
    let url = cache.get(id);
    if (!url) { url = await elevenBlob(spoken); cache.set(id, url); }
    if (loading !== id) return "";   // arrêté pendant le chargement
    audio = new Audio(url);
    audio.onended = () => { if (playing === id) { playing = null; emit(); } };
    loading = null; playing = id; emit();
    await audio.play();
    return "";
  } catch (e: any) {
    loading = null; playing = null; emit();
    return e?.message || "Lecture impossible.";
  }
}

export function clearCache(): void { cache.forEach((u) => URL.revokeObjectURL(u)); cache.clear(); }

export function useSpeech(id: string): "idle" | "loading" | "playing" {
  const [, tick] = useState(0);
  useEffect(() => { const l = () => tick((n) => n + 1); listeners.add(l); return () => { listeners.delete(l); }; }, []);
  return playing === id ? "playing" : loading === id ? "loading" : "idle";
}

export const canSpeakOnDevice = (): boolean => typeof window !== "undefined" && "speechSynthesis" in window;
export { isNative };
