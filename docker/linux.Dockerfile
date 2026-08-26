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
        build-essential \
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
        libegl1 \
        libopengl0 \
        libxcb-cursor0 \
    && rm -rf /var/lib/apt/lists/*

# Force gcc/g++ explicitement : l'image officielle python:3.13-slim-bookworm
# embarque des métadonnées sysconfig qui poussent Nuitka/Scons à chercher un
# compilateur nommé "x86_64-conda-linux-gnu-gcc" (héritage du pipeline de
# build de l'image officielle) au lieu du gcc réellement installé ci-dessus.
ENV CC=gcc
ENV CXX=g++

RUN pip install --no-cache-dir nuitka pyside6 cryptography

WORKDIR /app
COPY . /app

ENTRYPOINT ["bash", "Installers/DEB installer/build_deb.sh"]