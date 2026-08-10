use std::{env, error::Error, fs, io, path::PathBuf};

const DEBUG_KEY: &str = "desktop-debug-key-not-a-real-secret";
const SEED_HASH_SIDECAR: &str = "resources/seed.sqlite3.zip.sha256";

fn main() {
    println!("cargo:rerun-if-env-changed=G2B_SERVICE_KEY");
    println!("cargo:rerun-if-changed={SEED_HASH_SIDECAR}");
    if let Err(error) = generate_embedded_configuration() {
        eprintln!("embedded build configuration failed: {error}");
        std::process::exit(1);
    }
    tauri_build::build();
}

fn generate_embedded_configuration() -> Result<(), Box<dyn Error>> {
    let profile = env::var("PROFILE")?;
    let configured = env::var("G2B_SERVICE_KEY")
        .ok()
        .filter(|value| !value.trim().is_empty());
    let key = match configured {
        Some(value) => value,
        None if profile == "release" => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "G2B_SERVICE_KEY is required for release builds",
            )
            .into());
        }
        None => DEBUG_KEY.to_owned(),
    };
    if key.contains(['\r', '\n', '\0']) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "G2B_SERVICE_KEY contains a forbidden control character",
        )
        .into());
    }

    let seed_hash_path = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").ok_or_else(|| {
        io::Error::new(io::ErrorKind::NotFound, "CARGO_MANIFEST_DIR is unavailable")
    })?)
    .join(SEED_HASH_SIDECAR);
    let seed_hash = fs::read_to_string(seed_hash_path)?;
    let seed_hash = seed_hash
        .strip_suffix("\r\n")
        .or_else(|| seed_hash.strip_suffix('\n'))
        .unwrap_or(&seed_hash);
    if seed_hash.len() != 64 || !seed_hash.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "seed source hash sidecar must contain exactly 64 hexadecimal characters",
        )
        .into());
    }

    let output = PathBuf::from(
        env::var_os("OUT_DIR")
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "OUT_DIR is unavailable"))?,
    )
    .join("embedded_api_key.rs");
    fs::write(
        output,
        format!(
            "pub const EMBEDDED_API_KEY: &str = {key:?};\npub const EMBEDDED_SEED_SHA256: &str = {seed_hash:?};\n"
        ),
    )?;
    Ok(())
}
