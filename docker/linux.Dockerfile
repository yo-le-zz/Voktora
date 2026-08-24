# Voktora — image de compilation Linux (.deb)
#
# Fournit un environnement reproductible pour compiler Voktora avec Nuitka
# et l'empaqueter en .deb, identique en local et en CI.
#
# Utilisation :
#   docker build -f docker/linux.Dockerfile -t voktora-build-linux .
#   docker run --rm -v "$PWD/dist:/app/dist" voktora-build-linux [VERSION]
#
# Le paquet produit est ecrit dans dist/linux/ sur la machine hote.

FROM python:3.13-slim-bookworm

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
        git \
        patchelf \
        dpkg-dev \
        ccache \
        libxcb-xinerama0 \
        libxcb-icccm4 \
        libxcb-image0 \
        libxcb-keysyms1 \
        libxcb-randr0 \
        libxcb-render-util0 \
        libxcb-xkb1 \
        libxkbcommon-x11-0 \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir nuitka pyside6 cryptography

WORKDIR /app
COPY . /app

ENTRYPOINT ["bash", "Installers/DEB installer/build_deb.sh"]
