//! Voktora — extension native optionnelle.
//!
//! Chaque fonction a un équivalent en Python pur dans `voktora/core/native.py` (utilisé quand cette
//! extension n'est pas installée) et doit rester **strictement équivalente** : mêmes résultats,
//! mêmes règles pour les liens symboliques, annulation par la même voie.
//!
//! Fonctions exposées :
//!   * `scan_tree(path)`                      -> (nb_fichiers, octets)       parcours parallèle
//!   * `copy_tree(src, dst, callback, threads)` -> (nb_fichiers, octets) | None  copie parallèle
//!   * `crc32_files(paths, threads)`          -> [crc32 | None, …]           hachage parallèle
//!
//! Le GIL est relâché pendant tout le travail ; il n'est repris que pour appeler la fonction de
//! progression (au plus ~20 fois par seconde).

use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use rayon::prelude::*;

const CHUNK: usize = 4 * 1024 * 1024;
const PROGRESS_INTERVAL: Duration = Duration::from_millis(50);

fn build_pool(threads: usize) -> PyResult<rayon::ThreadPool> {
    let wanted = if threads == 0 {
        std::thread::available_parallelism().map(|n| n.get()).unwrap_or(2).min(8)
    } else {
        threads
    };
    rayon::ThreadPoolBuilder::new()
        .num_threads(wanted.max(1))
        .build()
        .map_err(|e| PyOSError::new_err(format!("pool de threads : {e}")))
}

// ─────────────────────────── scan_tree ───────────────────────────

/// (fichiers, octets) d'un dossier, liens non suivis. Même règle que `archive._tree_size` :
/// lien vers un dossier ignoré ; lien vers un fichier compté (taille 0) ; erreur → +1 fichier.
fn scan_dir(dir: &Path) -> (u64, u64) {
    let Ok(read) = fs::read_dir(dir) else { return (0, 0) };
    let mut count = 0u64;
    let mut bytes = 0u64;
    let mut subdirs: Vec<PathBuf> = Vec::new();
    for entry in read.flatten() {
        let Ok(kind) = entry.file_type() else {
            count += 1;
            continue;
        };
        if kind.is_symlink() {
            if !fs::metadata(entry.path()).map(|m| m.is_dir()).unwrap_or(false) {
                count += 1;
            }
        } else if kind.is_dir() {
            subdirs.push(entry.path());
        } else {
            count += 1;
            match entry.metadata() {
                Ok(m) => bytes += m.len(),
                Err(_) => {}
            }
        }
    }
    let (c, b) = subdirs
        .par_iter()
        .map(|d| scan_dir(d))
        .reduce(|| (0, 0), |a, b| (a.0 + b.0, a.1 + b.1));
    (count + c, bytes + b)
}

#[pyfunction]
fn scan_tree(py: Python<'_>, path: String) -> PyResult<(u64, u64)> {
    let pool = build_pool(0)?;
    Ok(py.allow_threads(|| pool.install(|| scan_dir(Path::new(&path)))))
}

// ─────────────────────────── copy_tree ───────────────────────────

struct Job {
    src: PathBuf,
    dst: PathBuf,
    size: u64,
}

struct Plan {
    dirs: Vec<PathBuf>,
    files: Vec<Job>,
    links: Vec<(PathBuf, PathBuf)>,
}

fn plan_copy(src: &Path, dst: &Path) -> std::io::Result<Plan> {
    let mut plan = Plan { dirs: vec![dst.to_path_buf()], files: Vec::new(), links: Vec::new() };
    let mut stack = vec![(src.to_path_buf(), dst.to_path_buf())];
    while let Some((from, to)) = stack.pop() {
        for entry in fs::read_dir(&from)? {
            let entry = entry?;
            let kind = entry.file_type()?;
            let target = to.join(entry.file_name());
            if kind.is_symlink() {
                plan.links.push((entry.path(), target));
            } else if kind.is_dir() {
                plan.dirs.push(target.clone());
                stack.push((entry.path(), target));
            } else {
                let size = entry.metadata().map(|m| m.len()).unwrap_or(0);
                plan.files.push(Job { src: entry.path(), dst: target, size });
            }
        }
    }
    Ok(plan)
}

/// Pont vers la fonction de progression Python, partagé entre les threads.
struct Progress {
    callback: Option<PyObject>,
    done: AtomicU64,
    cancelled: AtomicBool,
    last: Mutex<Instant>,
    error: Mutex<Option<PyErr>>,
}

impl Progress {
    fn advance(&self, bytes: u64, name: &str, force: bool) {
        let total = self.done.fetch_add(bytes, Ordering::Relaxed) + bytes;
        let Some(callback) = &self.callback else { return };
        {
            let mut last = self.last.lock().unwrap();
            if !force && last.elapsed() < PROGRESS_INTERVAL {
                return;
            }
            *last = Instant::now();
        }
        Python::with_gil(|py| match callback.call1(py, (total, name)) {
            // La fonction renvoie False pour demander l'annulation ; None / True = continuer.
            Ok(value) => {
                if let Ok(flag) = value.extract::<bool>(py) {
                    if !flag {
                        self.cancelled.store(true, Ordering::Relaxed);
                    }
                }
            }
            Err(err) => {
                self.cancelled.store(true, Ordering::Relaxed);
                *self.error.lock().unwrap() = Some(err);
            }
        });
    }

    fn should_stop(&self) -> bool {
        self.cancelled.load(Ordering::Relaxed)
    }
}

fn copy_one(job: &Job, progress: &Progress) -> std::io::Result<()> {
    let name = job.src.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let mut reader = File::open(&job.src)?;
    let mut writer = File::create(&job.dst)?;
    let mut buffer = vec![0u8; CHUNK.min((job.size as usize).max(64 * 1024))];
    loop {
        if progress.should_stop() {
            return Ok(());
        }
        let read = reader.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        writer.write_all(&buffer[..read])?;
        progress.advance(read as u64, &name, false);
    }
    // Équivalent de shutil.copystat : droits et date de modification (échec silencieux).
    if let Ok(meta) = reader.metadata() {
        let _ = fs::set_permissions(&job.dst, meta.permissions());
        if let Ok(modified) = meta.modified() {
            let _ = writer.set_modified(modified);
        }
    }
    Ok(())
}

#[cfg(unix)]
fn make_link(src: &Path, dst: &Path) {
    if let Ok(target) = fs::read_link(src) {
        let _ = std::os::unix::fs::symlink(target, dst);
    }
}

#[cfg(not(unix))]
fn make_link(_src: &Path, _dst: &Path) {}

/// Copie `src` dans `dst` (dossier créé si besoin, jamais effacé). Retourne (fichiers, octets), ou
/// `None` si `callback(octets_copiés, nom)` a renvoyé False. Une exception du callback est relancée.
#[pyfunction]
#[pyo3(signature = (src, dst, callback=None, threads=0))]
fn copy_tree(
    py: Python<'_>,
    src: String,
    dst: String,
    callback: Option<PyObject>,
    threads: usize,
) -> PyResult<Option<(u64, u64)>> {
    let pool = build_pool(threads)?;
    let progress = Progress {
        callback,
        done: AtomicU64::new(0),
        cancelled: AtomicBool::new(false),
        last: Mutex::new(Instant::now() - PROGRESS_INTERVAL),
        error: Mutex::new(None),
    };

    let outcome: Result<(u64, u64), std::io::Error> = py.allow_threads(|| {
        let plan = plan_copy(Path::new(&src), Path::new(&dst))?;
        for dir in &plan.dirs {
            fs::create_dir_all(dir)?;
        }
        let total_files = plan.files.len() as u64;
        let first_error: Mutex<Option<std::io::Error>> = Mutex::new(None);
        pool.install(|| {
            plan.files.par_iter().for_each(|job| {
                if progress.should_stop() {
                    return;
                }
                if let Err(err) = copy_one(job, &progress) {
                    progress.cancelled.store(true, Ordering::Relaxed);
                    let mut slot = first_error.lock().unwrap();
                    if slot.is_none() {
                        *slot = Some(err);
                    }
                }
            });
        });
        if let Some(err) = first_error.into_inner().unwrap() {
            return Err(err);
        }
        if !progress.should_stop() {
            for (from, to) in &plan.links {
                make_link(from, to);
            }
            progress.advance(0, "", true);
        }
        Ok((total_files + plan.links.len() as u64, progress.done.load(Ordering::Relaxed)))
    });

    if let Some(err) = progress.error.lock().unwrap().take() {
        return Err(err);
    }
    match outcome {
        Err(err) => Err(PyOSError::new_err(err.to_string())),
        Ok(_) if progress.should_stop() => Ok(None),
        Ok(result) => Ok(Some(result)),
    }
}

// ─────────────────────────── crc32_files ───────────────────────────

fn crc_of(path: &str) -> Option<u32> {
    let mut file = File::open(path).ok()?;
    let mut hasher = crc32fast::Hasher::new();
    let mut buffer = vec![0u8; 1024 * 1024];
    loop {
        let read = file.read(&mut buffer).ok()?;
        if read == 0 {
            return Some(hasher.finalize());
        }
        hasher.update(&buffer[..read]);
    }
}

/// CRC32 de chaque fichier (même valeur que `zlib.crc32`), None si illisible.
#[pyfunction]
#[pyo3(signature = (paths, threads=0))]
fn crc32_files(py: Python<'_>, paths: Vec<String>, threads: usize) -> PyResult<Vec<Option<u32>>> {
    let pool = build_pool(threads)?;
    Ok(py.allow_threads(|| pool.install(|| paths.par_iter().map(|p| crc_of(p)).collect())))
}

#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn voktora_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(scan_tree, m)?)?;
    m.add_function(wrap_pyfunction!(copy_tree, m)?)?;
    m.add_function(wrap_pyfunction!(crc32_files, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}
