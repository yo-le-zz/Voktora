# Voktora — image de compilation Windows (.msi)
#
# Fournit un environnement reproductible pour compiler Voktora avec Nuitka
# et l'empaqueter en .msi via WiX Toolset 4.x — utilisable en LOCAL, sur une
# machine Windows avec Docker Desktop configure en "Windows containers".
#
# NON utilise en CI : les runners windows-latest de GitHub Actions n'ont pas
# Docker Desktop installe. Le workflow CI compile Windows directement sur
# le runner (voir .github/workflows/build-release.yml, job "build").
#
# Utilisation :
#   docker build -f docker/windows.Dockerfile -t voktora-build-windows .
#   docker run --rm -v "$PWD\dist:C:\app\dist" voktora-build-windows [VERSION]
#
# Le paquet produit est ecrit dans dist/windows/ sur la machine hote.

FROM mcr.microsoft.com/dotnet/sdk:8.0-windowsservercore-ltsc2022

SHELL ["powershell", "-NoLogo", "-NoProfile", "-Command", "$ErrorActionPreference='Stop';"]

# -- Python -------------------------------------------------------------------
RUN Invoke-WebRequest -Uri https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe \
        -OutFile python-installer.exe ; \
    Start-Process -FilePath .\python-installer.exe -ArgumentList \
        '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0' -Wait ; \
    Remove-Item python-installer.exe

# -- WiX Toolset ---------------------------------------------------------------
RUN dotnet tool install --global wix --version 4.0.6 ; \
    $env:PATH += ';C:\Users\ContainerAdministrator\.dotnet\tools' ; \
    [Environment]::SetEnvironmentVariable('PATH', $env:PATH, 'Machine') ; \
    wix extension add --global WixToolset.UI.wixext/4.0.6

RUN python -m pip install --no-cache-dir nuitka pyside6 cryptography

WORKDIR C:/app
COPY . C:/app

ENTRYPOINT ["python", "Installers/MSI installer/build_msi.py"]
