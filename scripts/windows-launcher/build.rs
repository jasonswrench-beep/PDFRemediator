// Puts the program's icon, its Windows manifest and its version details into PDF Remediator.exe.
// package-windows.py passes the icon it checked (PDFR_LAUNCHER_ICON) and the oldest Visual C++ runtime the package needs
// (PDFR_MIN_VC_RUNTIME); a plain `cargo build` uses the source icon and the value written in package-windows.py.
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

fn rc_path(path: &Path) -> String {
    let text = path.display().to_string();
    let text = text.strip_prefix(r"\\?\").unwrap_or(&text).to_string();
    text.replace('\\', "\\\\").replace('"', "")
}

fn main() {
    let here = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let icon = env::var("PDFR_LAUNCHER_ICON")
        .map(PathBuf::from)
        .unwrap_or_else(|_| here.join("../../src/pdf_remediator/web_assets/PDFRemediator.ico"));
    let icon = fs::canonicalize(&icon).expect("the program icon is missing");
    let manifest = fs::canonicalize(here.join("app.manifest")).expect("app.manifest is missing");
    let minimum = env::var("PDFR_MIN_VC_RUNTIME").unwrap_or_else(|_| {
        let packager = fs::read_to_string(here.join("../package-windows.py")).expect("package-windows.py is missing");
        let line = packager.lines().find(|line| line.starts_with("MS_RUNTIME_MINIMUM = ")).expect("MS_RUNTIME_MINIMUM is missing");
        line.split('"').nth(1).expect("MS_RUNTIME_MINIMUM has no value").to_string()
    });
    assert!(
        minimum.split('.').count() == 4 && minimum.split('.').all(|part| part.parse::<u16>().is_ok()),
        "PDFR_MIN_VC_RUNTIME must look like 14.51.36247.0"
    );
    println!("cargo:rustc-env=PDFR_MIN_VC_RUNTIME={minimum}");

    let version = env::var("CARGO_PKG_VERSION").unwrap();
    let numbers: Vec<&str> = version.split('.').collect();
    let comma = format!("{},{},{},0", numbers[0], numbers[1], numbers[2]);
    let lines = [
        format!("1 ICON \"{}\"", rc_path(&icon)),
        format!("1 24 \"{}\"", rc_path(&manifest)),
        "1 VERSIONINFO".to_string(),
        format!("FILEVERSION {comma}"),
        format!("PRODUCTVERSION {comma}"),
        "FILEOS 0x40004".to_string(),
        "FILETYPE 0x1".to_string(),
        "BEGIN".to_string(),
        "  BLOCK \"StringFileInfo\"".to_string(),
        "  BEGIN".to_string(),
        "    BLOCK \"040904b0\"".to_string(),
        "    BEGIN".to_string(),
        "      VALUE \"CompanyName\", \"PDF Remediator\"".to_string(),
        "      VALUE \"FileDescription\", \"PDF Remediator\"".to_string(),
        format!("      VALUE \"FileVersion\", \"{version}\""),
        "      VALUE \"InternalName\", \"PDF Remediator\"".to_string(),
        "      VALUE \"LegalCopyright\", \"Copyright 2026 Jason S. Wrench and the PDF Remediator contributors\"".to_string(),
        "      VALUE \"OriginalFilename\", \"PDF Remediator.exe\"".to_string(),
        "      VALUE \"ProductName\", \"PDF Remediator\"".to_string(),
        format!("      VALUE \"ProductVersion\", \"{version}\""),
        "    END".to_string(),
        "  END".to_string(),
        "  BLOCK \"VarFileInfo\"".to_string(),
        "  BEGIN".to_string(),
        "    VALUE \"Translation\", 0x409, 1200".to_string(),
        "  END".to_string(),
        "END".to_string(),
    ];
    let out = PathBuf::from(env::var("OUT_DIR").unwrap()).join("launcher.rc");
    fs::write(&out, lines.join("\n") + "\n").unwrap();
    embed_resource::compile(&out, embed_resource::NONE).manifest_required().unwrap();

    println!("cargo:rerun-if-changed=app.manifest");
    println!("cargo:rerun-if-changed=../package-windows.py");
    println!("cargo:rerun-if-changed={}", icon.display());
    println!("cargo:rerun-if-env-changed=PDFR_LAUNCHER_ICON");
    println!("cargo:rerun-if-env-changed=PDFR_MIN_VC_RUNTIME");
}
