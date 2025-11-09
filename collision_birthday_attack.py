import argparse
import hashlib
import os
import time
import random
import multiprocessing as mp
import heapq
import signal
from typing import List


# Dossier où seront écrits les résultats
BASE_DIR = "Collision_Birthday"

# Valeurs par défaut
DEFAULT_ALGO = "sha256"
DEFAULT_PREFIX = 10
DEFAULT_MAX_SAMPLES = 7_000_000  # à adapter selon la RAM disponible
DEFAULT_WORKERS = os.cpu_count() or 1
DEFAULT_SORT_CHUNKS = DEFAULT_WORKERS  # même nombre que workers, par défaut

def ensure_dir(path: str) -> None:
    """
    Crée le dossier s'il n'existe pas
    """
    os.makedirs(path, exist_ok=True)


def make_hash_func(algo: str):
    """
    Retourne une fonction de hachage correspondant au nom d'algorithme demandé.
    La fonction retournée prend des bytes en entrée et renvoie le digest (bytes)
    """
    if algo == "sha256":
        def hash_function(data: bytes) -> bytes:
            return hashlib.sha256(data).digest()
    elif algo == "sha3_256":
        def hash_function(data: bytes) -> bytes:
            return hashlib.sha3_256(data).digest()
    else:
        raise ValueError("Algorithme de hachage inconnu : {}".format(algo))

    return hash_function


def worker_generate_packed(count: int,prefix_len_hex: int,algo: str,seed: int) -> List[int]:
    """
    Fonction exécutée dans un processus worker

    Elle génère `count` valeurs aléatoires x à partir d'une seed, calcule leurs hash, extrait le préfixe demandé, et packe le tout dans un seul entier :
        packed = (prefix_int << 64) | x

    On renvoie une liste d'entiers "packed"
    """
    rng = random.Random(seed)
    hash_function = make_hash_func(algo)

    prefix_bits = prefix_len_hex * 4
    needed_bytes = (prefix_bits + 7) // 8

    packed_list: List[int] = []

    for _ in range(count):
        # Génére un message de 64 bits
        x = rng.getrandbits(64)
        data = x.to_bytes(8, "big")

        # Hacher le message
        digest = hash_function(data)

        # Extraire juste les octets nécessaires au préfixe
        prefix_bytes = digest[:needed_bytes]

        # Convertir en entier
        prefix_int = int.from_bytes(prefix_bytes, "big")

        # Supprimer les bits en trop dans le dernier octet
        extra_bits = needed_bytes * 8 - prefix_bits
        if extra_bits > 0:
            prefix_int >>= extra_bits

        # Pack dans un seul entier : préfixe en haut, x en bas
        packed = (prefix_int << 64) | x
        packed_list.append(packed)

    return packed_list


def unpack_prefix_and_x(packed: int) :
    """
    Dépacke un entier en (prefix_int, x)
    """
    x = packed & ((1 << 64) - 1)
    prefix_int = packed >> 64
    return prefix_int, x


def split_list(data: List[int], parts: int) -> List[List[int]]:
    """
    Découpe une liste en `parts` sous-listes de taille aussi égale que possible
    """
    n = len(data)
    if parts <= 1 or n == 0:
        return [data]

    chunk_size = n // parts
    remainder = n % parts

    result: List[List[int]] = []
    start = 0
    for i in range(parts):
        size = chunk_size + (1 if i < remainder else 0)
        end = start + size
        result.append(data[start:end])
        start = end

    return result


def sort_chunk(chunk: List[int]) -> List[int]:
    """
    Trie une sous-liste qui sera exécuté dans un process séparé
    """
    chunk.sort()
    return chunk


def merge_sorted_lists(sorted_lists) :
    """
    Fusionne plusieurs listes déjà triées en un seul flux trié.
    """
    return heapq.merge(*sorted_lists)

def init_worker():
    signal.signal(signal.SIGINT, signal.SIG_IGN)

def main():
    """
    Point d'entrée principal du programme
    """
    parser = argparse.ArgumentParser(description="Collision sur préfixe par table unique + tri parallèle")
    parser.add_argument("--target-prefix","-t",type=int,default=DEFAULT_PREFIX,help="Nombre de caractères hexadécimaux du préfixe (par défaut {})".format(DEFAULT_PREFIX),)
    parser.add_argument("--algo","-a",type=str,default=DEFAULT_ALGO,choices=["sha256", "sha3_256"],help="Algorithme de hachage à utiliser sha256 ou sha3_256",)
    parser.add_argument("--max-samples","-n",type=int,default=DEFAULT_MAX_SAMPLES,help="Nombre total d'échantillons à générer",)
    parser.add_argument("--workers","-w",type=int,default=DEFAULT_WORKERS,help="Nombre de processus pour la génération",)
    parser.add_argument("--sort-chunks","-s",type=int,default=DEFAULT_SORT_CHUNKS,help="Nombre de morceaux pour le tri parallèle",)

    args = parser.parse_args()

    prefix_len_hex = args.target_prefix
    algo = args.algo
    max_samples = args.max_samples
    workers = args.workers
    sort_chunks = args.sort_chunks

    ensure_dir(BASE_DIR)

    print("Algorithme           :", algo)
    print("Préfixe cible        :", prefix_len_hex, "hex")
    print("Échantillons demandés:", max_samples)
    print("Workers génération   :", workers)
    print("Morceaux de tri      :", sort_chunks)

    # Répartition des échantillons entre les workers
    base_count = max_samples // workers
    remainder = max_samples % workers

    counts: List[int] = []
    for index in range(workers):
        worker_count = base_count
        if index < remainder:
            worker_count += 1
        if worker_count > 0:
            counts.append(worker_count)

    start_time = time.time()

    print("Génération en cours...")
    packed_all: List[int] = []
    
    gen_pool = mp.Pool(processes=len(counts), initializer=init_worker)
    try:
        async_jobs = []
        for index, count in enumerate(counts):
            seed = (int(time.time()) ^ (os.getpid() << 16) ^ (index << 8)) & 0xFFFFFFFF
            async_jobs.append(
                gen_pool.apply_async(worker_generate_packed, (count, prefix_len_hex, algo, seed))
            )

        for job in async_jobs:
            part = job.get()
            packed_all.extend(part)

    except KeyboardInterrupt:
        print("\n[MAIN] Ctrl+C pendant la génération -> arrêt immédiat des workers.")
        gen_pool.terminate()
        gen_pool.join()
        return
    else:
        gen_pool.close()
        gen_pool.join()
    
    gen_time = time.time()
    print("  Génération terminée en {:.2f} secondes ({} entrées).".format(gen_time - start_time,len(packed_all)))

    print("Tri parallèle en cours...")

    sublists = split_list(packed_all, sort_chunks)
    # on n'a plus besoin de la grosse référence
    packed_all = None

    # limite le nombre de process de tri
    sort_procs = min(len(sublists), os.cpu_count() or 1)
    sort_pool = mp.Pool(processes=sort_procs, initializer=init_worker)

    sorted_sublists: List[List[int]] = []
    try:
        async_sort_jobs = []
        for sub in sublists:
            async_sort_jobs.append(sort_pool.apply_async(sort_chunk, (sub,)))

        for job in async_sort_jobs:
            sorted_part = job.get()
            sorted_sublists.append(sorted_part)

    except KeyboardInterrupt:
        print("\n[MAIN] Ctrl+C pendant le tri -> arrêt immédiat des workers de tri.")
        sort_pool.terminate()
        sort_pool.join()
        return
    else:
        sort_pool.close()
        sort_pool.join()
    
    sort_time = time.time()
    print("  Tri terminé en {:.2f} secondes.".format(sort_time - gen_time))

    print("Fusion des morceaux triés et recherche de doublons...")

    merged_iter = merge_sorted_lists(sorted_sublists)
    hash_function = make_hash_func(algo)
    previous_packed = None
    collision = None

    try:
        for packed in merged_iter:
            if previous_packed is not None:
                prev_prefix, prev_x = unpack_prefix_and_x(previous_packed)
                cur_prefix, cur_x = unpack_prefix_and_x(packed)

                if prev_prefix == cur_prefix and prev_x != cur_x:
                    # re-vérification
                    hash1 = hash_function(prev_x.to_bytes(8, "big")).hex()
                    hash2 = hash_function(cur_x.to_bytes(8, "big")).hex()
                    if hash1[:prefix_len_hex] == hash2[:prefix_len_hex]:
                        collision = (prev_prefix, prev_x, cur_x, hash1, hash2)
                        break

            previous_packed = packed
    except KeyboardInterrupt:
        print("\n[MAIN] Ctrl+C pendant la fusion/recherche -> arrêt.")
        return

    end_time = time.time()

    if collision is not None:
        prefix_int, x1, x2, hash1, hash2 = collision
        print("=== COLLISION TROUVÉE ===")
        print("Préfixe (int)   :", prefix_int)
        print("x1              :", "{:016x}".format(x1))
        print("x2              :", "{:016x}".format(x2))
        print("hash1           :", hash1)
        print("hash2           :", hash2)

        run_root = os.path.join(BASE_DIR, "pref_{:02d}".format(prefix_len_hex))
        ensure_dir(run_root)

        file1 = os.path.join(run_root,"{}_p{:02d}_x1_{:016x}.bin".format(algo, prefix_len_hex, x1))
        file2 = os.path.join(run_root,"{}_p{:02d}_x2_{:016x}.bin".format(algo, prefix_len_hex, x2))

        with open(file1, "wb") as f1:
            f1.write(x1.to_bytes(8, "big"))

        with open(file2, "wb") as f2:
            f2.write(x2.to_bytes(8, "big"))

        print("Fichiers écrits dans :", run_root)
    else:
        print("Aucune collision trouvée dans ces échantillons")
        print("Augmentez --max-samples ou réduisez --target-prefix")

    print("Temps total :", "{:.2f} secondes".format(end_time - start_time))


if __name__ == "__main__":
    mp.freeze_support()
    main()
