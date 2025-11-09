Ce projet met en pratique le principe de l’attaque d’anniversaire présenté en cours, en l’appliquant à des fonctions de hachage modernes (**SHA-256** ou **SHA3-256**).
L’objectif est de trouver deux messages différents `x1 ≠ x2` tels que les `prefix_len_hex` premiers caractères hexadécimaux de `H(x1)` et `H(x2)` soient identiques.

## Principe général

- On génère un grand nombre de valeurs aléatoires sur 64 bits
- Pour chacune on calcule le hash (SHA-256 ou SHA3-256)
- On extrait uniquement le préfixe demandé (par exemple 12 ou 14 hex)
- On stocke toutes ces valeurs dans **une table**, puis on **trie la table par préfixe**
- Une fois la table triée, **deux entrées consécutives avec le même préfixe** correspondent à une collision sur ce préfixe

C’est exactement la méthode vue en cours : “générer ≈ 2^{n/2} valeurs, trier, chercher les doublons”. Le tri permet d’éviter de comparer tout le monde avec tout le monde, et la recherche devient linéaire.

## Pourquoi trier plutôt que Floyd (tortue-lièvre) ?

En cours on a aussi vu les algorithmes de détection de cycle (Floyd et Brent), mais ici on ne parcourt pas **une fonction itérative** de la forme `x_{i+1} = f(x_i)`. On génère plein de messages indépendants pour couvrir l’espace de hash. Dans ce contexte :

- le **tri + recherche de doublons** est la méthode la plus rapide et la plus sûre pour trouver toutes les collisions présentes dans un pannel d'échantillons données ~= 5 min pour 14 préfix identique
- Floyd est plus adapté lorsque l'on atteint des **tailles de calcul** necessitant une **mémoire supérieur à 60GO**, dans notre cas l'allocation de mémoire le plus haut est de **40GO** avec **14** préfix identique

Donc j'ai décidé de suivre la méthode du cours **“attaque d’anniversaire optimisée par tri”**.

## Optimisation mémoire

Stocker pour chaque valeur un tuple Python `(prefix_str, x)` est très coûteux (string + int + tuple). Pour réduire ça, on encode chaque entrée dans **un seul entier Python** :

```python
packed = (prefix_int << 64) | x
```

- `prefix_int` contient le préfixe du hash (sur `prefix_len_hex * 4` bits),
- `x` est le message aléatoire sur 64 bits.

**Avantage** : un seul objet Python par entrée ce qui donne moins d’overhead et moins de pression mémoire tout en etant plus rapide à trier.

## Multiprocessing

Il reste 2 parties lourdes : générer + hasher et trier.

### Génération / hachage
- c’est la partie la plus coûteuse en CPU
- on la parallélise : plusieurs processus génèrent chacun une portion du total et renvoient leurs listes au processus principal.

### Tri parallèle
- au lieu de trier une seule liste énorme dans un seul process, on découpe la liste en plusieurs morceaux
- on trie chaque morceau dans un process séparé
- on fusionne ensuite les listes triées (`heapq.merge`)
- la recherche de doublon se fait pendant ou juste après la fusion

**Résultat** : on utilise vraiment plusieurs cœurs, pas seulement pour le hash mais aussi pour le tri.

## Attention sur la RAM

Même compacté, le nombre d’entrées explose vite :

- Un préfixe de 12 hex alloue environ 3GO
- Un préfixe de 14 hex alloue environ 34GO

On peut calculer l'espace mémoire qui sera utilisé en determinant le nombre de hash à stocker et en faisant une approximation sur son cout de stockage, pour un préfix de 14 hex, on calculera 2^28 hash soit 268 435 456, si 1 hash prend 67 octet on aura donc 17GO alloué, on double cette espace pour la gestion du tri on arrive à 34 GO.

## Usage typique

```bash
python3 collision_birthday_attack.py --target-prefix 12 --algo sha256 --max-samples 20000000 --workers 8 --sort-chunks 8
```

- `--target-prefix` : nombre de caractères hex à faire matcher
- `--algo` : `sha256` ou `sha3_256`
- `--max-samples` : nombre total d’échantillons à générer
- `--workers` : nombre de processus de génération [par défaut il prend le maximum de core du système]
- `--sort-chunks` : nombre de morceaux pour le tri parallèle

Le programme affiche ensuite si une collision a été trouvée et écrit les deux messages correspondants dans un dossier du projet.

