import { useEffect, useState } from "react";
import { api, isNative } from "./api";
import { ContactButton } from "./ContactPicker";

type Rdv = { id: string; title: string; kind: string; kind_label: string; start_at: string; end_at?: string; location: string;
  client_name: string; phone: string; notes: string; status: string; remind_minutes: number };

const KINDS: [string, string][] = [["metre", "Métré"], ["visite", "Visite"], ["pose", "Pose"], ["livraison", "Livraison"], ["rdv", "Rendez-vous"], ["autre", "Autre"]];
const REMIND_BASE = 5000;   // identifiants des rappels : 5000 à 5199

const dayKey = (iso: string) => new Date(iso).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const hour = (iso: string) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** Rappels locaux sur le téléphone : X minutes avant chaque rendez-vous prévu (fonctionne hors connexion). */
async function scheduleReminders(rows: Rdv[]) {
  if (!isNative) return;
  try {
    const { LocalNotifications } = await import("@capacitor/local-notifications");
    await LocalNotifications.cancel({ notifications: Array.from({ length: 200 }, (_, i) => ({ id: REMIND_BASE + i })) }).catch(() => {});
    const perm = await LocalNotifications.requestPermissions();
    if (perm.display !== "granted") return;
    const now = Date.now();
    const list = rows.filter((r) => r.status === "planned")
      .map((r) => ({ r, at: new Date(r.start_at).getTime() - (r.remind_minutes || 0) * 60000 }))
      .filter((x) => x.at > now).slice(0, 200)
      .map((x, i) => ({ id: REMIND_BASE + i, title: `${x.r.kind_label} à ${hour(x.r.start_at)}`,
        body: [x.r.title, x.r.client_name, x.r.location].filter(Boolean).join(" · "), schedule: { at: new Date(x.at), allowWhileIdle: true } }));
    if (list.length) await LocalNotifications.schedule({ notifications: list });
  } catch { /* rappels indisponibles : l'agenda reste utilisable */ }
}

export function Agenda() {
  const [rows, setRows] = useState<Rdv[]>([]);
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState(false);
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ title: "", kind: "metre", date: today, time: "09:00", duration_min: "", location: "", client_name: "", phone: "", remind_minutes: "60" });
  const load = () => api.agenda().then((d) => { setRows(d.rdv); scheduleReminders(d.rdv); }).catch((e) => setMsg(e?.message || "Erreur"));
  useEffect(() => { load(); }, []);

  const save = async () => {
    setMsg("");
    try {
      const r = await api.addAppointment({ ...f, start: `${f.date} ${f.time}`, duration_min: f.duration_min ? Number(f.duration_min) : null,
        remind_minutes: Number(f.remind_minutes) });
      setMsg(r.conflits.length ? `Noté. ⚠️ Chevauche : ${r.conflits.join(" ; ")}` : "Rendez-vous noté.");
      setOpen(false); setF({ ...f, title: "", location: "", client_name: "", phone: "" }); load();
    } catch (e: any) { setMsg(e?.message || "Erreur"); }
  };
  const set = async (id: string, status: string) => { await api.updateAppointment(id, { status }); load(); };

  const groups: Record<string, Rdv[]> = {};
  rows.forEach((r) => { (groups[dayKey(r.start_at)] ||= []).push(r); });
  const input = (k: keyof typeof f, label: string, type = "text") => (
    <label>{label}<input type={type} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
  );
  return (
    <div className="page">
      <div className="page-inner">
        <h1>Agenda</h1>
        <p className="lede">Visites, métrés, poses, livraisons. Ou dis simplement dans le chat : « note un métré jeudi à 10 h chez Pape Diop à la Médina ».</p>
        <button className="btn btn-copper" onClick={() => setOpen(!open)}>{open ? "Fermer" : "+ Nouveau rendez-vous"}</button>
        {open && (
          <section className="card-box agenda-form">
            {input("title", "Quoi (ex. Métré salon)")}
            <label>Type<select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            <div className="two-col">{input("date", "Date", "date")}{input("time", "Heure", "time")}</div>
            <div className="two-col">{input("duration_min", "Durée (min, optionnel)", "number")}
              <label>Rappel<select value={f.remind_minutes} onChange={(e) => setF({ ...f, remind_minutes: e.target.value })}>
                {[["0", "Aucun"], ["30", "30 min avant"], ["60", "1 h avant"], ["120", "2 h avant"], ["1440", "La veille"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select></label></div>
            {input("location", "Lieu")}
            <div className="contact-head"><span>Client</span><ContactButton onPick={(c) => setF({ ...f, client_name: c.name || f.client_name, phone: c.number || f.phone })} /></div>
            <div className="two-col">{input("client_name", "Nom")}{input("phone", "Téléphone", "tel")}</div>
            <button className="btn btn-copper" disabled={f.title.trim().length < 2} onClick={save}>Enregistrer</button>
          </section>
        )}
        {msg && <p className="hint">{msg}</p>}
        {!rows.length && <p className="hint">Rien de prévu dans les 60 prochains jours.</p>}
        {Object.entries(groups).map(([day, list]) => (
          <section key={day} className="agenda-day">
            <h3>{day}</h3>
            {list.map((r) => (
              <article key={r.id} className={`agenda-item k-${r.kind}`}>
                <div className="agenda-time">{hour(r.start_at)}{r.end_at && <span>{hour(r.end_at)}</span>}</div>
                <div className="agenda-body">
                  <b>{r.title.toLowerCase().startsWith(r.kind_label.toLowerCase()) ? r.title : `${r.kind_label} · ${r.title}`}</b>
                  {(r.client_name || r.location) && <span>{[r.client_name, r.location].filter(Boolean).join(" · ")}</span>}
                  <div className="row-actions">
                    {r.phone && <a className="btn btn-line btn-small" href={`tel:${r.phone}`}>Appeler</a>}
                    {r.location && <a className="btn btn-line btn-small" target="_blank" rel="noreferrer"
                      href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(r.location + ", Dakar")}`}>Itinéraire</a>}
                    <button className="btn btn-line btn-small" onClick={() => set(r.id, "done")}>Fait</button>
                    <button className="btn btn-line btn-small" onClick={() => window.confirm("Annuler ce rendez-vous ?") && set(r.id, "cancelled")}>Annuler</button>
                  </div>
                </div>
              </article>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
