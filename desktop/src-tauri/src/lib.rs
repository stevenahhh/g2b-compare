pub mod app_state;
pub(crate) mod build_metadata {
    include!(concat!(env!("OUT_DIR"), "/embedded_api_key.rs"));
}
pub mod catalog;
pub mod comparison_selection;
pub mod data_diagnostics;
pub mod db;
pub mod estimate;
pub mod export_workbook;
pub mod offline_replay;
pub mod remote;

use std::{env, error::Error, ffi::OsString, fs, io, path::PathBuf, sync::Arc};

use app_state::{DesktopState, install_embedded_estimate_assets};
use catalog::CatalogState;
use data_diagnostics::DataDiagnosticsState;
use db::{BootstrapPaths, bootstrap_database};
use estimate::EstimateState;
use tauri::{Manager, path::BaseDirectory};

const APP_DATA_OVERRIDE_ENV: &str = "G2B_COMPARE_APP_DATA_DIR";

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let app_data = resolve_app_data_dir(
                app.path().app_data_dir()?,
                env::var_os(APP_DATA_OVERRIDE_ENV),
            );
            let paths = BootstrapPaths {
                seed_archive: app
                    .path()
                    .resolve("resources/seed.sqlite3.zip", BaseDirectory::Resource)?,
                data: app_data.join("g2b.sqlite3"),
            };
            bootstrap_database(&paths, build_metadata::EMBEDDED_SEED_SHA256)
                .map_err(|error| Box::new(error) as Box<dyn Error>)?;
            let data_diagnostics_state = DataDiagnosticsState::new(paths.data.clone());
            let estimate_state =
                EstimateState::new(&paths.data, app_data.join("estimate-view.sqlite3"))
                    .map_err(|error| Box::new(error) as Box<dyn Error>)?;
            let replay_store = Arc::new(
                offline_replay::ReplayStore::open(app_data.join("offline-replay.sqlite3"))
                    .map_err(|error| Box::new(error) as Box<dyn Error>)?,
            );
            let template_assets = install_embedded_estimate_assets(&app_data)
                .map_err(|error| Box::new(error) as Box<dyn Error>)?;
            let documents_export = app
                .path()
                .document_dir()
                .ok()
                .map(|path| path.join("G2B Compare Desktop").join("exports"));
            let export_directory = documents_export.map_or_else(
                || app_data.join("exports"),
                |path| {
                    if fs::create_dir_all(&path).is_ok() {
                        path
                    } else {
                        app_data.join("exports")
                    }
                },
            );
            fs::create_dir_all(&export_directory)?;
            let desktop_state = DesktopState::new(
                &paths.data,
                app_data.join("desktop-view.sqlite3"),
                replay_store,
                template_assets,
                export_directory,
            )
            .map_err(|error| Box::new(error) as Box<dyn Error>)?;
            let catalog_state =
                CatalogState::new(&paths.data, app_data.join("catalog-view.sqlite3"))
                    .map_err(|error| Box::new(error) as Box<dyn Error>)?
                    .with_item_adder(Arc::new(estimate_state.clone()));
            if !app.manage(catalog_state) {
                return Err(managed_state_error("catalog"));
            }
            if !app.manage(estimate_state) {
                return Err(managed_state_error("estimate"));
            }
            if !app.manage(data_diagnostics_state) {
                return Err(managed_state_error("data diagnostics"));
            }
            if !app.manage(desktop_state) {
                return Err(managed_state_error("desktop"));
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            catalog::commands::search_products,
            catalog::commands::search_relations,
            catalog::commands::add_catalog_item,
            catalog::commands::open_product,
            catalog::commands::load_catalog_view,
            catalog::commands::save_catalog_view,
            catalog::commands::get_catalog_cache_status,
            estimate::commands::list_estimates,
            estimate::commands::create_estimate,
            estimate::commands::read_estimate,
            estimate::commands::update_estimate,
            estimate::commands::refresh_estimate_comparisons,
            estimate::commands::delete_estimate,
            estimate::commands::load_estimate_view,
            estimate::commands::save_estimate_view,
            app_state::export_estimate_workbook,
            app_state::copy_estimate_table,
            app_state::load_desktop_view,
            app_state::save_desktop_view,
            app_state::get_reconciliation_status,
            app_state::replay_pending_changes,
            app_state::resolve_reconciliation_conflict,
            data_diagnostics::get_data_status,
            data_diagnostics::run_data_sync,
            data_diagnostics::run_data_diagnostics,
        ])
        .run(tauri::generate_context!())
        .unwrap_or_else(|error| {
            eprintln!("데스크톱 앱을 시작하지 못했습니다: {error}");
            std::process::exit(1);
        });
}

fn managed_state_error(name: &str) -> Box<dyn Error> {
    Box::new(io::Error::new(
        io::ErrorKind::AlreadyExists,
        format!("{name} application state is already managed"),
    ))
}

fn resolve_app_data_dir(default: PathBuf, override_value: Option<OsString>) -> PathBuf {
    override_value
        .filter(|value| !value.is_empty())
        .map_or(default, PathBuf::from)
}

#[cfg(test)]
mod tests {
    use std::{ffi::OsString, path::PathBuf};

    use super::resolve_app_data_dir;

    #[test]
    fn app_data_override_is_explicit_and_empty_values_use_platform_default() {
        let default = PathBuf::from("platform-default");
        let isolated = PathBuf::from("isolated-qa");

        assert_eq!(
            resolve_app_data_dir(default.clone(), Some(isolated.clone().into_os_string())),
            isolated
        );
        assert_eq!(
            resolve_app_data_dir(default.clone(), Some(OsString::new())),
            default
        );
    }
}
