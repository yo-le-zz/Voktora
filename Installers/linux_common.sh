#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Voktora — linux_common.sh
# Fonctions partagées par build_deb.sh et build_rpm.sh (à inclure avec `source`) :
#   - voktora_clean_version   : normalise le numéro de version
#   - voktora_compile         : compile UNE fois avec Nuitka (réutilisé par .deb et .rpm)
#   - voktora_stage_tree      : construit l'arborescence installée (/opt, /usr/bin, icône, .desktop…)
# Ainsi les deux paquets contiennent exactement les mêmes fichiers.
# ─────────────────────────────────────────────────────────────────────────────

# Retire un éventuel préfixe « v »/« V » (convention de tag git, ex. « v1.0.4 »).
voktora_clean_version() {
    local v="${1#v}"
    v="${v#V}"
    printf '%s' "$v"
}

# Compile avec Nuitka --standalone dans $DIST_DIR/nuitka_out/main.dist.
# Ne recompile pas si le résultat existe déjà (sauf VOKTORA_FORCE_COMPILE=1) : en CI,
# le .deb est construit en premier, le .rpm réutilise sa compilation.
voktora_compile() {
    local root="$1" dist_dir="$2"
    ONEDIR="$dist_dir/nuitka_out/main.dist"
    if [[ -x "$ONEDIR/voktora" && "${VOKTORA_FORCE_COMPILE:-0}" != "1" ]]; then
        echo ">>> Compilation Nuitka déjà présente : $ONEDIR (réutilisée)"
        return 0
    fi
    rm -rf "$dist_dir/nuitka_out"
    mkdir -p "$dist_dir"
    echo ""
    echo ">>> Compilation Nuitka..."
    python -m nuitka \
      --standalone \
      --remove-output \
      --enable-plugin=pyside6 \
      --include-qt-plugins=iconengines,imageformats,platforms,platformthemes,tls,xcbglintegrations \
      --disable-console \
      --linux-icon="$root/assets/Voktora.png" \
      --output-dir="$dist_dir/nuitka_out" \
      --output-filename=voktora \
      "$root/voktora/main.py"

    # Ressources lues à l'exécution à côté du binaire
    cp -r "$root/voktora/themes"      "$ONEDIR/themes"
    cp -r "$root/assets"              "$ONEDIR/assets"
    cp    "$root/voktora/version.txt" "$ONEDIR/version.txt"
}

# Construit l'arborescence du système installé dans $1 (dossier vide ou inexistant).
# Arguments : DEST ROOT ONEDIR VERSION
voktora_stage_tree() {
    local dest="$1" root="$2" onedir="$3" version="$4"
    local install_dir="/opt/voktora"

    rm -rf "$dest"
    mkdir -p "$dest$install_dir"
    cp -r "$onedir/." "$dest$install_dir/"
    chmod +x "$dest$install_dir/voktora"
    # Rien d'inscriptible par le groupe ou les autres dans un paquet installé en root.
    chmod -R go-w "$dest$install_dir"

    mkdir -p "$dest/usr/bin"
    ln -s "$install_dir/voktora" "$dest/usr/bin/voktora"

    mkdir -p "$dest/usr/share/icons/hicolor/256x256/apps"
    cp "$root/assets/Voktora.png" "$dest/usr/share/icons/hicolor/256x256/apps/voktora.png"

    mkdir -p "$dest/usr/share/applications"
    cat > "$dest/usr/share/applications/voktora.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=Voktora
Comment=Project Instance Manager — by yolezz
Exec=$install_dir/voktora
Icon=voktora
Categories=Development;Utility;
Terminal=false
StartupWMClass=Voktora
Keywords=project;git;manager;developer;
DESKTOP

    mkdir -p "$dest/usr/share/metainfo"
    cat > "$dest/usr/share/metainfo/io.github.yo_le_zz.Voktora.metainfo.xml" << METAINFO
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>io.github.yo_le_zz.Voktora</id>
  <name>Voktora</name>
  <summary>Project Instance Manager</summary>
  <description>
    <p>Gestionnaire de projets de développement : instances, intents, coffre chiffré,
    profils d'exécution, hooks, snapshots, dashboard et plugins.</p>
  </description>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <url type="homepage">https://github.com/yo-le-zz/Voktora</url>
  <launchable type="desktop-id">voktora.desktop</launchable>
  <releases>
    <release version="$version"/>
  </releases>
</component>
METAINFO

    mkdir -p "$dest/usr/share/licenses/voktora"
    cp "$root/LICENSE" "$dest/usr/share/licenses/voktora/LICENSE"
}
