import { lazy, type ComponentType } from "react";

/** Page chargée à la demande : l'écran de démarrage ne télécharge ni n'analyse que le strict nécessaire (plus rapide sur téléphone).
 *  Si le fichier de la page a changé depuis l'ouverture de l'appli (nouvelle version en ligne), on recharge UNE fois pour reprendre le bon. */
export function lazyPage<K extends string>(load: () => Promise<Record<K, ComponentType<any>>>, name: K) {
  return lazy(() =>
    load()
      .then((m) => ({ default: m[name] }))
      .catch((e) => {
        try {
          if (!sessionStorage.getItem("unic-chunk-reload")) {
            sessionStorage.setItem("unic-chunk-reload", "1");
            window.location.reload();
            return new Promise<never>(() => {});
          }
        } catch { /* stockage indisponible : on laisse l'erreur remonter */ }
        throw e;
      }),
  );
}
