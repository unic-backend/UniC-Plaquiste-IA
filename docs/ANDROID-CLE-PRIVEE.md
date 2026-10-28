# Clé de signature Android : passer de la clé publique à ta clé privée

## Le constat (vérifié)
- `frontend/android/app/unic-debug.keystore` est dans le dépôt, avec le mot de passe **public `android`** (c'est la clé « debug » habituelle d'Android).
- `build.gradle` l'utilise **seulement si** aucune clé privée n'est fournie : si les secrets GitHub `UNIC_KEYSTORE_B64` et `UNIC_KEYSTORE_PASSWORD` existent, l'APK est signé avec TA clé privée (mécanisme déjà en place, `.github/workflows/android.yml`).
- **Je ne peux pas savoir si tes secrets sont posés** (GitHub ne me les montre pas). Pour le savoir : GitHub › Settings › Secrets and variables › Actions › vérifie la présence de `UNIC_KEYSTORE_B64`.

## État vérifié le 28/10/2026 : clé privée EN PLACE
APK de `main` (Android APK, run 358) lu avec `keytool -printcert -jarfile` :
- signataire : `CN=UniC Plaquiste, O=UniC Plaquiste, L=Dakar, C=SN`, SHA-256 `F3:67:AA:1B:F2:12:DC:0B:48:70:AD:76:59:C5:F3:BA:74:16:68:58:10:B5:F2:41:13:4B:86:70:CA:22:ED:C4` ;
- clé publique du dépôt (`unic-debug.keystore`) : `CN=UniC AI Debug`, SHA-256 `98:98:4E:BD:…:3B:EE:71` → **non utilisée**.

Les secrets `UNIC_KEYSTORE_*` sont donc posés : rien à faire. La clé du dépôt ne sert qu'aux constructions sans secrets.
Pour revérifier : télécharger l'APK (Actions › Android APK › artefact) puis `keytool -printcert -jarfile app-debug.apk`.
Les étapes plus bas ne servent que si la clé privée devait être recréée.

## Le risque réel (honnête)
Quelqu'un qui possède la clé publique peut fabriquer un faux APK **de même signature** que le tien. Pour qu'il compte, **tu dois l'installer toi-même** (hors Play Store) : il faut donc te tromper. Risque : **faible à modéré**, pas une faille à distance. Mais une clé publique ne protège rien : mieux vaut une clé privée.

## Passer à la clé privée (une fois, sur un ordinateur)
1. Crée la clé (remplace le mot de passe par une longue phrase secrète, **garde-la dans un gestionnaire de mots de passe**) :
   `keytool -genkeypair -v -keystore unic.keystore -alias unic -keyalg RSA -keysize 2048 -validity 10000`
2. Encode-la : `base64 -w0 unic.keystore` (Mac : `base64 -i unic.keystore`).
3. GitHub › Settings › Secrets and variables › Actions › New repository secret :
   - `UNIC_KEYSTORE_B64` = le texte obtenu à l'étape 2
   - `UNIC_KEYSTORE_PASSWORD` = ton mot de passe
4. Relance « Android APK » (Actions › Run workflow).
5. **Garde une copie du fichier `unic.keystore` hors de GitHub** (clé USB, coffre). Si tu la perds, tu ne pourras plus mettre l'appli à jour.

## Conséquence à connaître
Changer de clé change la signature : Android refuse de mettre à jour par-dessus l'ancienne appli. Il faut **désinstaller puis réinstaller** une fois. Les données de l'appli sont sur le serveur : tu ressaisis seulement ton code d'accès.

## Ce qu'il ne faut JAMAIS faire
- Coller la clé, son mot de passe ou le code base64 dans un chat (y compris avec moi) ou dans le code.
- Supprimer `unic-debug.keystore` du dépôt : le build sans secrets cesserait de fonctionner (rien n'est supprimé sans ton accord).
