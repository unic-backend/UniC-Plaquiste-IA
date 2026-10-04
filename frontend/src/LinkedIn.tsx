import { useEffect, useState } from "react";
import * as I from "./Icons";
import { net, type LinkedInStatus, type Post } from "./api";

/** Connexion LinkedIn : le patron crée son appli LinkedIn, colle Client ID / Secret, puis autorise. Aucun mot de passe LinkedIn ne transite. */
export function LinkedInConnect({ say, onChange }: { say: (m: string) => void; onChange?: () => void }) {
  const [st, setSt] = useState<LinkedInStatus | null>(null);
  const [cid, setCid] = useState("");
  const [secret, setSecret] = useState("");
  const [page, setPage] = useState("");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const refresh = () => net.linkedinStatus().then((s) => { setSt(s); setCid((c) => c || s.client_id); setPage((p) => p || s.page_id); onChange?.(); }).catch((e) => say(e.message));
  useEffect(() => { refresh(); }, []);

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try { await fn(); if (ok) say(ok); } catch (e: any) { say(e.message || "Erreur"); } finally { setBusy(false); }
  };
  const copyUri = async () => { try { await navigator.clipboard.writeText(st?.redirect_uri || ""); say("Adresse copiée."); } catch { say("Copie impossible : sélectionne l'adresse."); } };
  if (!st) return null;

  return (
    <section className="card-box">
      <label>Connexion LinkedIn</label>
      {st.connected ? (
        <>
          <p className="post-body"><I.Check size={16} /> {st.name || "Compte"} relié · {st.days_left ?? "?"} jours restants</p>
          <p className="hint">Le jeton dure 60 jours : reconnecte-toi avant la fin. {st.page_scope && st.page_id ? "Page entreprise reliée." : "Profil perso seulement."}</p>
          <div className="row">
            <button className="btn btn-line btn-small" disabled={busy} onClick={() => run(async () => { setLink((await net.linkedinAuthUrl(false)).url); }, "Lien prêt : touche « Ouvrir LinkedIn ».")}>Reconnecter</button>
            <button className="btn btn-ghost btn-small" disabled={busy}
              onClick={() => { if (window.confirm("Déconnecter LinkedIn ? Le jeton sera effacé du serveur.")) run(async () => { await net.linkedinDisconnect(); await refresh(); }, "LinkedIn déconnecté."); }}>Déconnecter</button>
          </div>
        </>
      ) : (
        <>
          <p className="hint">Rien n'est publié sans ton « Publier ». Il faut une appli LinkedIn gratuite (5 minutes).</p>
          <button className="btn btn-line btn-small" onClick={() => setOpen((o) => !o)}>{open ? "Masquer les étapes" : "Voir les étapes"}</button>
          {open && (
            <ol className="steps">
              <li>Ouvre <a href="https://www.linkedin.com/developers/apps/new" target="_blank" rel="noopener noreferrer">linkedin.com/developers</a> → <b>Create app</b>. Nom : UniC AI. Page LinkedIn : choisis ta Page UniC (obligatoire pour LinkedIn).</li>
              <li>Onglet <b>Products</b> : ajoute <b>« Share on LinkedIn »</b> et <b>« Sign In with LinkedIn using OpenID Connect »</b>.</li>
              <li>Onglet <b>Auth</b> → « Authorized redirect URLs » : ajoute cette adresse exactement :
                <div className="copy-line"><code>{st.redirect_uri}</code><button className="btn btn-line btn-small" onClick={copyUri}>Copier</button></div></li>
              <li>Toujours dans <b>Auth</b> : copie le <b>Client ID</b> et le <b>Client Secret</b>, colle-les ci-dessous.</li>
            </ol>
          )}
        </>
      )}
      {!st.connected && (
        <>
          <input autoComplete="off" placeholder="Client ID" value={cid} onChange={(e) => setCid(e.target.value)} aria-label="Client ID" />
          <input type="password" autoComplete="off" placeholder={st.app_saved ? "Client Secret (déjà enregistré)" : "Client Secret"} value={secret} onChange={(e) => setSecret(e.target.value)} aria-label="Client Secret" />
          <input inputMode="numeric" autoComplete="off" placeholder="Identifiant de la Page (facultatif, chiffres)" value={page} onChange={(e) => setPage(e.target.value)} aria-label="Identifiant de la Page" />
          <button className="btn btn-copper" disabled={busy || cid.trim().length < 8 || (!secret && !st.app_saved)}
            onClick={() => run(async () => { await net.linkedinSaveApp(cid, secret, page); setSecret(""); setLink((await net.linkedinAuthUrl(false)).url); await refresh(); }, "Enregistré. Touche « Ouvrir LinkedIn ».")}>
            Enregistrer et connecter
          </button>
        </>
      )}
      {link && <a className="btn btn-copper open-link" href={link} target="_blank" rel="noopener noreferrer">Ouvrir LinkedIn pour autoriser</a>}
      {link && <button className="btn btn-line btn-small" onClick={() => { setLink(""); refresh(); }}>C'est fait, actualiser</button>}
      {st.connected && st.page_id && !st.page_scope && (
        <>
          <p className="hint">Page entreprise : LinkedIn exige que ton appli ait reçu l'accès « Community Management API » (demande validée par LinkedIn, délai non garanti).</p>
          <button className="btn btn-line btn-small" disabled={busy} onClick={() => run(async () => { setLink((await net.linkedinAuthUrl(true)).url); }, "Lien prêt : touche « Ouvrir LinkedIn ».")}>Relier la Page</button>
        </>
      )}
    </section>
  );
}

/** Boutons de publication sur un post LinkedIn approuvé : photo facultative, profil ou Page. */
export function LinkedInPublish({ post, connected, pageReady, say, onDone }: { post: Post; connected: boolean; pageReady: boolean; say: (m: string) => void; onDone: () => void }) {
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async (target: "profile" | "page") => {
    setBusy(true);
    try { await net.linkedinPublish(post.id, target, photo); say(target === "page" ? "Publié sur la Page LinkedIn." : "Publié sur ton profil LinkedIn."); onDone(); }
    catch (e: any) { say(e.message || "Publication impossible"); }
    finally { setBusy(false); }
  };
  if (!connected) return <p className="hint">Connecte LinkedIn ci-dessus pour publier d'ici, ou utilise « Partager ».</p>;
  return (
    <div className="li-publish">
      <label className="btn btn-line btn-small file-btn"><I.Camera size={14} /> {photo ? photo.name.slice(0, 18) : "Ajouter une photo"}
        <input type="file" accept="image/*" hidden onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
      </label>
      <button className="btn btn-copper btn-small" disabled={busy} onClick={() => go("profile")}>Publier sur mon profil</button>
      {pageReady && <button className="btn btn-copper btn-small" disabled={busy} onClick={() => go("page")}>Publier sur la Page</button>}
    </div>
  );
}
