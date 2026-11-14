//! Comptage de lignes par langage : code / commentaires / lignes vides. Aucune dépendance, aucun appel à Voktora.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

#[derive(Default, Clone, Debug, PartialEq, Eq)]
pub struct Row {
    pub files: u64,
    pub code: u64,
    pub comments: u64,
    pub blank: u64,
}

#[derive(Default, Debug)]
pub struct Report {
    pub rows: BTreeMap<String, Row>,
    pub truncated: bool,
    pub skipped_binary: u64,
}

/// (nom du langage, commentaire de ligne, commentaire de bloc)
type Lang = (&'static str, &'static [&'static str], Option<(&'static str, &'static str)>);

pub fn language_of(file_name: &str) -> Option<Lang> {
    let lower = file_name.to_lowercase();
    if lower == "dockerfile" { return Some(("Dockerfile", &["#"], None)); }
    if lower == "makefile" { return Some(("Makefile", &["#"], None)); }
    let ext = lower.rsplit_once('.').map(|(_, e)| e.to_string())?;
    let c_block = Some(("/*", "*/"));
    Some(match ext.as_str() {
        "rs" => ("Rust", &["//"], c_block),
        "py" | "pyw" => ("Python", &["#"], None),
        "js" | "mjs" | "cjs" | "jsx" => ("JavaScript", &["//"], c_block),
        "ts" | "tsx" => ("TypeScript", &["//"], c_block),
        "go" => ("Go", &["//"], c_block),
        "java" => ("Java", &["//"], c_block),
        "kt" | "kts" => ("Kotlin", &["//"], c_block),
        "c" | "h" => ("C", &["//"], c_block),
        "cpp" | "cc" | "cxx" | "hpp" | "hh" => ("C++", &["//"], c_block),
        "cs" => ("C#", &["//"], c_block),
        "swift" => ("Swift", &["//"], c_block),
        "php" => ("PHP", &["//", "#"], c_block),
        "rb" => ("Ruby", &["#"], None),
        "sh" | "bash" | "zsh" => ("Shell", &["#"], None),
        "ps1" => ("PowerShell", &["#"], None),
        "lua" => ("Lua", &["--"], None),
        "sql" => ("SQL", &["--"], c_block),
        "html" | "htm" => ("HTML", &[], Some(("<!--", "-->"))),
        "xml" => ("XML", &[], Some(("<!--", "-->"))),
        "css" | "scss" => ("CSS", &[], c_block),
        "toml" => ("TOML", &["#"], None),
        "yaml" | "yml" => ("YAML", &["#"], None),
        "json" => ("JSON", &[], None),
        "md" | "markdown" => ("Markdown", &[], None),
        "qss" => ("QSS", &[], c_block),
        _ => return None,
    })
}

/// Compte un texte : retourne (code, commentaires, vides).
pub fn count_text(text: &str, line_comments: &[&str], block: Option<(&str, &str)>) -> (u64, u64, u64) {
    let (mut code, mut comments, mut blank) = (0u64, 0u64, 0u64);
    let mut in_block = false;
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() {
            blank += 1;
            continue;
        }
        if in_block {
            comments += 1;
            if let Some((_, end)) = block {
                if line.contains(end) { in_block = false; }
            }
            continue;
        }
        if line_comments.iter().any(|p| line.starts_with(p)) {
            comments += 1;
            continue;
        }
        if let Some((start, end)) = block {
            if line.starts_with(start) {
                comments += 1;
                if !line[start.len()..].contains(end) { in_block = true; }
                continue;
            }
        }
        code += 1;
    }
    (code, comments, blank)
}

pub fn count_dir(root: &Path, skip: &[String], max_files: usize) -> Report {
    let mut report = Report::default();
    let mut seen = 0usize;
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = fs::read_dir(&dir) else { continue };
        let mut entries: Vec<_> = entries.flatten().collect();
        entries.sort_by_key(|e| e.file_name());
        for entry in entries {
            let name = entry.file_name().to_string_lossy().to_string();
            let Ok(kind) = entry.file_type() else { continue };
            if kind.is_symlink() { continue; }
            if kind.is_dir() {
                if !skip.iter().any(|s| s == &name) { stack.push(entry.path()); }
                continue;
            }
            let Some((lang, lines, block)) = language_of(&name) else { continue };
            seen += 1;
            if seen > max_files {
                report.truncated = true;
                return report;
            }
            let Ok(bytes) = fs::read(entry.path()) else { continue };
            if bytes.iter().take(2048).any(|b| *b == 0) {
                report.skipped_binary += 1;
                continue;
            }
            let (code, comments, blank) = count_text(&String::from_utf8_lossy(&bytes), lines, block);
            let row = report.rows.entry(lang.to_string()).or_default();
            row.files += 1;
            row.code += code;
            row.comments += comments;
            row.blank += blank;
        }
    }
    report
}

pub fn render_markdown(name: &str, report: &Report) -> String {
    let mut rows: Vec<_> = report.rows.iter().collect();
    rows.sort_by(|a, b| b.1.code.cmp(&a.1.code).then(a.0.cmp(b.0)));
    let mut out = format!("# Lignes de code — {name}\n\n");
    if rows.is_empty() {
        out.push_str("_Aucun fichier source reconnu._\n");
        return out;
    }
    out.push_str("| Langage | Fichiers | Code | Commentaires | Vides |\n|---|---:|---:|---:|---:|\n");
    let mut total = Row::default();
    for (lang, r) in &rows {
        out.push_str(&format!("| {lang} | {} | {} | {} | {} |\n", r.files, r.code, r.comments, r.blank));
        total.files += r.files;
        total.code += r.code;
        total.comments += r.comments;
        total.blank += r.blank;
    }
    out.push_str(&format!("| **Total** | **{}** | **{}** | **{}** | **{}** |\n", total.files, total.code, total.comments, total.blank));
    if report.truncated { out.push_str("\n_Analyse tronquée : limite de fichiers atteinte._\n"); }
    if report.skipped_binary > 0 { out.push_str(&format!("\n_{} fichier(s) binaire(s) ignoré(s)._\n", report.skipped_binary)); }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counts_rust_comments_and_blank() {
        let src = "// titre\nfn main() {\n\n    /* bloc\n       suite */\n    let x = 1; // fin\n}\n";
        assert_eq!(count_text(src, &["//"], Some(("/*", "*/"))), (3, 3, 1));
    }

    #[test]
    fn single_line_block_does_not_open() {
        let src = "/* un */\ncode\n";
        assert_eq!(count_text(src, &["//"], Some(("/*", "*/"))), (1, 1, 0));
    }

    #[test]
    fn python_hash_comments() {
        assert_eq!(count_text("# a\nx = 1\n\n", &["#"], None), (1, 1, 1));
    }

    #[test]
    fn languages_by_extension_and_name() {
        assert_eq!(language_of("main.RS").unwrap().0, "Rust");
        assert_eq!(language_of("Dockerfile").unwrap().0, "Dockerfile");
        assert!(language_of("photo.png").is_none() && language_of("LICENSE").is_none());
    }

    #[test]
    fn directory_scan_skips_ignored_and_binary() {
        let dir = std::env::temp_dir().join(format!("loc-test-{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("src")).unwrap();
        fs::create_dir_all(dir.join("node_modules")).unwrap();
        fs::write(dir.join("src/a.py"), "# c\nx = 1\ny = 2\n").unwrap();
        fs::write(dir.join("src/b.js"), "let a;\n").unwrap();
        fs::write(dir.join("node_modules/x.js"), "ignoré\n").unwrap();
        fs::write(dir.join("src/bin.py"), b"\x00\x01\x02").unwrap();
        let report = count_dir(&dir, &["node_modules".to_string()], 100);
        assert_eq!(report.rows["Python"], Row { files: 1, code: 2, comments: 1, blank: 0 });
        assert_eq!(report.rows["JavaScript"].files, 1);
        assert_eq!(report.skipped_binary, 1);
        assert!(!report.truncated);
        let limited = count_dir(&dir, &[], 1);
        assert!(limited.truncated);
        let md = render_markdown("demo", &report);
        assert!(md.contains("| Python | 1 | 2 | 1 | 0 |") && md.contains("**Total**"));
        assert!(render_markdown("v", &Report::default()).contains("Aucun fichier"));
        let _ = fs::remove_dir_all(&dir);
    }
}
