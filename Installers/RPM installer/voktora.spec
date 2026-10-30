# ─────────────────────────────────────────────────────────────────────────────
# Voktora — voktora.spec
# Paquet RPM BINAIRE : l'application est déjà compilée par Nuitka (voir
# Installers/linux_common.sh), ce spec se contente de la déposer au bon endroit.
# Il n'est pas destiné à être reconstruit depuis les sources par rpmbuild -ba.
#
# Variables passées par build_rpm.sh (--define) :
#   voktora_version  version sans préfixe « v » ni tiret (ex. 1.0.4)
#   voktora_stage    arborescence installée préparée (voir voktora_stage_tree)
#   voktora_date     date du jour au format du %changelog (ex. Fri Oct 30 2026)
# ─────────────────────────────────────────────────────────────────────────────

%global debug_package %{nil}
%global _build_id_links none
# Le binaire Nuitka embarque ses propres bibliothèques Qt : ne pas les retoucher ni les analyser.
%global __strip /bin/true
%global __os_install_post %{nil}
%global __brp_check_rpaths %{nil}
AutoReqProv: no

Name:           voktora
Version:        %{voktora_version}
Release:        1
Summary:        Voktora — Project Instance Manager
License:        MIT
URL:            https://github.com/yo-le-zz/Voktora
ExclusiveArch:  x86_64
Packager:       yolezz <https://github.com/yo-le-zz>

# Dépendances système exprimées par bibliothèque (soname) et non par nom de paquet :
# les noms varient entre Fedora, RHEL et openSUSE, les sonames restent identiques.
Requires:       libGL.so.1()(64bit)
Requires:       libEGL.so.1()(64bit)
Requires:       libOpenGL.so.0()(64bit)
Requires:       libglib-2.0.so.0()(64bit)
Requires:       libfontconfig.so.1()(64bit)
Requires:       libxkbcommon-x11.so.0()(64bit)
Requires:       libxcb-icccm.so.4()(64bit)
Requires:       libxcb-image.so.0()(64bit)
Requires:       libxcb-keysyms.so.1()(64bit)
Requires:       libxcb-randr.so.0()(64bit)
Requires:       libxcb-render-util.so.0()(64bit)
Requires:       libxcb-xkb.so.1()(64bit)
Requires:       libxcb-xinerama.so.0()(64bit)
Requires:       libxcb-cursor.so.0()(64bit)

%description
Voktora est un gestionnaire de projets de développement avec interface
graphique : instances et intents, coffre chiffré, profils d'exécution, hooks,
snapshots, dashboard de santé et système de plugins. Authentification GitHub
App ou OAuth. Créé par yolezz.

%prep
# Rien à préparer : le contenu est déjà compilé.

%build
# Rien à compiler.

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}
cp -a "%{voktora_stage}/." %{buildroot}/

%post
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || :
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q /usr/share/icons/hicolor >/dev/null 2>&1 || :
fi

%postun
# $1 vaut 0 uniquement lors d'une désinstallation complète (pas lors d'une mise à jour).
if [ "$1" -eq 0 ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database /usr/share/applications >/dev/null 2>&1 || :
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q /usr/share/icons/hicolor >/dev/null 2>&1 || :
    fi
fi

%files
%defattr(-,root,root,-)
/opt/voktora
/usr/bin/voktora
/usr/share/applications/voktora.desktop
/usr/share/icons/hicolor/256x256/apps/voktora.png
/usr/share/metainfo/io.github.yo_le_zz.Voktora.metainfo.xml
%license /usr/share/licenses/voktora/LICENSE

%changelog
* %{voktora_date} yolezz <https://github.com/yo-le-zz> - %{voktora_version}-1
- Paquet RPM construit automatiquement par la CI de Voktora.
