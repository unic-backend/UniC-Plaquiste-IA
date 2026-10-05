/* UniC AI — bulle de discussion pour le site. Une ligne à ajouter au site :
   <script src="https://VOTRE-SERVEUR/api/public/widget.js" defer></script>
   Autonome, sans dépendance, styles préfixés « ucw- » (ne touche pas au reste du site). */
(function () {
  if (window.__ucwLoaded) return; window.__ucwLoaded = true;
  var script = document.currentScript || document.querySelector('script[src*="/api/public/widget.js"]');
  var API = script ? new URL(script.src).origin : "";
  var KEY = "ucw.session", HIST = "ucw.history";
  var css = "" +
    ".ucw-btn{position:fixed;right:18px;bottom:18px;z-index:2147483000;width:60px;height:60px;border-radius:50%;border:0;cursor:pointer;" +
    "background:#1f3a93;color:#fff;box-shadow:0 8px 24px rgba(0,0,0,.25);display:grid;place-items:center;font:600 13px/1 system-ui,sans-serif}" +
    ".ucw-btn svg{width:28px;height:28px}" +
    ".ucw-panel{position:fixed;right:18px;bottom:90px;z-index:2147483000;width:min(370px,calc(100vw - 24px));height:min(560px,calc(100vh - 120px));" +
    "background:#fff;border-radius:18px;box-shadow:0 16px 48px rgba(0,0,0,.28);display:none;flex-direction:column;overflow:hidden;" +
    "font:14.5px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1814}" +
    ".ucw-panel.ucw-open{display:flex}" +
    ".ucw-head{background:#1f3a93;color:#fff;padding:14px 16px;display:flex;align-items:center;justify-content:space-between}" +
    ".ucw-head b{font-size:15px}.ucw-head small{display:block;opacity:.85;font-size:12px;margin-top:2px}" +
    ".ucw-x{background:transparent;border:0;color:#fff;font-size:24px;cursor:pointer;line-height:1}" +
    ".ucw-msgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px;background:#f6f4ef}" +
    ".ucw-m{max-width:85%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}" +
    ".ucw-bot{background:#fff;border:1px solid #e6e0d6;align-self:flex-start;border-bottom-left-radius:4px}" +
    ".ucw-me{background:#1f3a93;color:#fff;align-self:flex-end;border-bottom-right-radius:4px}" +
    ".ucw-typing{opacity:.6;font-style:italic}" +
    ".ucw-form{display:flex;gap:8px;padding:10px;border-top:1px solid #e6e0d6;background:#fff}" +
    ".ucw-in{flex:1;border:1px solid #d9d0c4;border-radius:12px;padding:10px 12px;font:inherit;resize:none;max-height:96px}" +
    ".ucw-send{border:0;border-radius:12px;background:#f2c200;color:#1a1814;font-weight:700;padding:0 14px;cursor:pointer}" +
    ".ucw-wa{display:block;text-align:center;padding:8px;font-size:13px;color:#128c4a;text-decoration:none;background:#fff;border-top:1px solid #eee}" +
    "@media (prefers-reduced-motion:no-preference){.ucw-panel.ucw-open{animation:ucwIn .18s ease-out}}" +
    "@keyframes ucwIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}";
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  var btn = document.createElement("button");
  btn.className = "ucw-btn"; btn.setAttribute("aria-label", "Discuter avec UniC Plaquiste");
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';
  var panel = document.createElement("section");
  panel.className = "ucw-panel"; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Discussion UniC Plaquiste");
  panel.innerHTML = '<div class="ucw-head"><div><b>UniC Plaquiste</b><small>Faux plafonds · cloisons · décoration</small></div>' +
    '<button class="ucw-x" aria-label="Fermer">×</button></div><div class="ucw-msgs" aria-live="polite"></div>' +
    '<form class="ucw-form"><textarea class="ucw-in" rows="1" maxlength="600" placeholder="Votre question…" aria-label="Votre message"></textarea>' +
    '<button class="ucw-send" type="submit">Envoyer</button></form><a class="ucw-wa" target="_blank" rel="noopener">Écrire sur WhatsApp</a>';
  document.body.appendChild(panel); document.body.appendChild(btn);
  var msgs = panel.querySelector(".ucw-msgs"), form = panel.querySelector(".ucw-form"), input = panel.querySelector(".ucw-in"),
      wa = panel.querySelector(".ucw-wa"), busy = false;

  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function add(text, me, save) {
    var d = document.createElement("div"); d.className = "ucw-m " + (me ? "ucw-me" : "ucw-bot"); d.textContent = text;
    msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight;
    if (save) { var h = []; try { h = JSON.parse(get(HIST) || "[]"); } catch (e) {} h.push([me ? 1 : 0, text]); set(HIST, JSON.stringify(h.slice(-40))); }
    return d;
  }
  function setWa(n) { if (n) { wa.href = "https://wa.me/" + n + "?text=" + encodeURIComponent("Bonjour UniC Plaquiste, "); wa.style.display = "block"; } }
  var hist = []; try { hist = JSON.parse(get(HIST) || "[]"); } catch (e) {}
  if (hist.length) hist.forEach(function (h) { add(h[1], !!h[0], false); });
  else add("Bonjour 👋 Je suis l'assistant d'UniC Plaquiste. Faux plafond, cloison, décoration : dites-moi ce que vous souhaitez, je vous oriente et le gérant vous rappelle.", false, false);
  wa.style.display = "none";
  var known = get("ucw.wa"); if (known) setWa(known);

  function toggle(open) { panel.classList.toggle("ucw-open", open); if (open) setTimeout(function () { input.focus(); }, 50); }
  btn.addEventListener("click", function () { toggle(!panel.classList.contains("ucw-open")); });
  panel.querySelector(".ucw-x").addEventListener("click", function () { toggle(false); });
  input.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.submit(); } });
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim(); if (!text || busy) return;
    busy = true; input.value = ""; add(text, true, true);
    var wait = add("UniC Plaquiste écrit…", false, false); wait.classList.add("ucw-typing");
    fetch(API + "/api/public/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: get(KEY), message: text, page: location.pathname }) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        wait.remove();
        if (d.session_id) set(KEY, d.session_id);
        if (d.whatsapp) { set("ucw.wa", d.whatsapp); setWa(d.whatsapp); }
        add(d.reply || "Désolé, un souci technique. Écrivez-nous sur WhatsApp.", false, true);
      })
      .catch(function () { wait.remove(); add("Connexion impossible pour le moment. Écrivez-nous sur WhatsApp, c'est plus rapide.", false, false); })
      .finally(function () { busy = false; });
  });
})();
