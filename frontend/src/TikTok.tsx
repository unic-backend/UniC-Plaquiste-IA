import { useState } from "react";
import { net, type Post } from "./api";

type Say = (m: string) => void;

/** Studio TikTok : l'IA écrit le script de la vidéo ; le patron la tourne et la publie lui-même. */
export function TikTokStudio({ say, onDraft }: { say: Say; onDraft: () => void }) {
  const [topic, setTopic] = useState("");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await net.tiktokScript(topic, details); setTopic(""); setDetails(""); onDraft(); say("Script prêt : voir « Brouillons » plus bas."); }
    catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };
  return (
    <section className="card-box">
      <label>Script de vidéo TikTok</label>
      <p className="hint">L'IA écrit l'accroche, les plans à filmer, le texte à l'écran, la légende et les hashtags. Tu filmes sur ton téléphone, puis tu publies dans TikTok.</p>
      <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Ex. Pose d'un faux plafond en 3 étapes" aria-label="Sujet de la vidéo" />
      <textarea rows={3} value={details} onChange={(e) => setDetails(e.target.value)} placeholder="Faits vrais (type de chantier, quartier, ce que tu peux filmer…)" aria-label="Faits à utiliser" />
      <button className="btn btn-copper" disabled={busy || topic.trim().length < 5} onClick={go}>Écrire le script</button>
      <button className="btn btn-line btn-small" onClick={() => setOpen((o) => !o)}>{open ? "Masquer" : "Pourquoi pas de publication automatique ?"}</button>
      {open && (
        <p className="hint">
          TikTok n'autorise la publication automatique qu'aux applis qu'il a auditées ; avant cet audit, tout ce qui est publié par une appli reste <b>privé</b>.
          L'envoi en brouillon vers ton TikTok demande aussi l'approbation de TikTok. En attendant, ce mode est le plus fiable. La demande d'accès est prête dans docs/TIKTOK_API_DEMANDE.md.
        </p>
      )}
    </section>
  );
}

/** Après tournage : copie la légende (texte avant « --- ») puis ouvre TikTok. */
export function TikTokActions({ post, say }: { post: Post; say: Say }) {
  const caption = `${post.body.split("\n---")[0].trim()}${post.hashtags ? `\n\n${post.hashtags}` : ""}`;
  const go = async () => {
    let copied = true;
    try { await navigator.clipboard.writeText(caption); } catch { copied = false; }
    say(copied ? "Légende copiée. Dans TikTok : ajoute ta vidéo, colle la légende." : "Copie impossible : sélectionne la légende à la main.");
    window.open("https://www.tiktok.com/", "_blank");
  };
  return (
    <div className="li-publish">
      <button className="btn btn-copper btn-small" onClick={go}>Copier la légende et ouvrir TikTok</button>
    </div>
  );
}
