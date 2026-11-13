# Mise à jour de Voktora

Voktora consulte (au plus une fois par 24 h, 8 s après le démarrage) les versions GitHub de `yo-le-zz/Voktora`
(tags `vX.Y.Z`, pré-versions ignorées). Si une version plus récente existe, il propose de **télécharger** le fichier
correspondant à votre système ; le fichier doit avoir une somme SHA-256 publiée (champ `digest` de GitHub ou ressource
`<fichier>.sha256`), sinon il est refusé. Voktora ne remplace jamais son propre programme en marche : il vous indique
le fichier vérifié à installer. Menu Préférences → « Rechercher une mise à jour… » pour vérifier à la main ;
réglage `updates.check = false` pour désactiver la vérification automatique.
