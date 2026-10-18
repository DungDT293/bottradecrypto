use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{
    menu::{MenuBuilder, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager, State, WindowEvent,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackendInfo {
    pub instance_id: String,
    pub host: String,
    pub port: u16,
    pub session_token: String,
    pub pid: Option<u32>,
    pub status: String,
}

#[derive(Debug, Deserialize)]
struct HandshakeFile {
    instance_id: Option<String>,
    status: String,
    host: String,
    port: u16,
    session_token: String,
    pid: Option<u32>,
}

pub struct AppState {
    pub backend_info: Arc<Mutex<Option<BackendInfo>>>,
    pub child_process: Arc<Mutex<Option<Child>>>,
    pub project_root: PathBuf,
    pub data_dir: PathBuf,
}

fn locate_project_root() -> PathBuf {
    let exe_dir = std::env::current_exe().ok().and_then(|p| p.parent().map(|p| p.to_path_buf()));
    let candidates = vec![
        std::env::current_dir().unwrap_or_default(),
        exe_dir.clone().unwrap_or_default(),
        exe_dir.clone().unwrap_or_default().join(".."),
        std::env::current_dir().unwrap_or_default().join(".."),
        std::env::current_dir().unwrap_or_default().join("../.."),
    ];

    for base in candidates {
        if base.join("backend").join("launcher.py").exists() || base.join("config.yaml").exists() {
            return base.canonicalize().unwrap_or(base);
        }
    }

    if let Some(dir) = exe_dir {
        return dir;
    }

    PathBuf::from(r"e:\TOOL DUNG CODE\bottradecrypto")
}

fn resolve_data_dir() -> PathBuf {
    if let Ok(app_data) = std::env::var("APPDATA") {
        let dir = PathBuf::from(app_data).join("telegram_binance_signal_executor");
        let _ = fs::create_dir_all(&dir);
        return dir;
    }
    let fallback = locate_project_root().join("data");
    let _ = fs::create_dir_all(&fallback);
    fallback
}

fn spawn_python_backend(root: &Path, data_dir: &Path) -> Result<(Child, BackendInfo), String> {
    let handshake_path = data_dir.join("backend_handshake.json");
    // Invariant: Remove any stale handshake file prior to spawning
    let _ = fs::remove_file(&handshake_path);

    let exe_dir = std::env::current_exe().unwrap_or_default().parent().unwrap_or(Path::new("")).to_path_buf();

    // Ensure default config exists in data_dir on fresh machines
    let config_in_data = data_dir.join("config.yaml");
    if !config_in_data.exists() {
        let default_config_candidates = vec![
            root.join("config.yaml"),
            exe_dir.join("config.yaml"),
            exe_dir.join("resources").join("config.yaml"),
            root.join("config.example.yaml"),
            PathBuf::from(r"e:\TOOL DUNG CODE\bottradecrypto\config.yaml"),
        ];
        for cand in default_config_candidates {
            if cand.exists() {
                let _ = fs::copy(&cand, &config_in_data);
                break;
            }
        }
    }

    // Ensure default .env exists in data_dir
    let env_in_data = data_dir.join(".env");
    if !env_in_data.exists() {
        let default_env_candidates = vec![
            root.join(".env"),
            exe_dir.join(".env"),
            exe_dir.join("resources").join(".env"),
            PathBuf::from(r"e:\TOOL DUNG CODE\bottradecrypto\.env"),
        ];
        for cand in default_env_candidates {
            if cand.exists() {
                let _ = fs::copy(&cand, &env_in_data);
                break;
            }
        }
    }

    // Ensure telegram_user.session exists in data_dir and data_dir/data
    let session_in_data = data_dir.join("telegram_user.session");
    let session_sub_dir = data_dir.join("data");
    let _ = fs::create_dir_all(&session_sub_dir);
    let session_in_sub = session_sub_dir.join("telegram_user.session");

    let session_candidates = vec![
        root.join("data").join("telegram_user.session"),
        root.join("telegram_user.session"),
        exe_dir.join("data").join("telegram_user.session"),
        exe_dir.join("telegram_user.session"),
        PathBuf::from(r"e:\TOOL DUNG CODE\bottradecrypto\data\telegram_user.session"),
    ];
    for cand in session_candidates {
        if cand.exists() {
            if !session_in_data.exists() {
                let _ = fs::copy(&cand, &session_in_data);
            }
            if !session_in_sub.exists() {
                let _ = fs::copy(&cand, &session_in_sub);
            }
            break;
        }
    }

    // Ensure historical trading_state.db exists in data_dir and data_dir/data
    let db_in_sub = session_sub_dir.join("trading_state.db");
    let db_in_root = data_dir.join("trading_state.db");
    let db_candidates = vec![
        root.join("data").join("trading_state.db"),
        root.join("trading_state.db"),
        exe_dir.join("data").join("trading_state.db"),
        exe_dir.join("trading_state.db"),
        PathBuf::from(r"e:\TOOL DUNG CODE\bottradecrypto\data\trading_state.db"),
    ];
    for cand in db_candidates {
        if cand.exists() {
            let src_len = fs::metadata(&cand).map(|m| m.len()).unwrap_or(0);
            let dst_len = fs::metadata(&db_in_sub).map(|m| m.len()).unwrap_or(0);
            if !db_in_sub.exists() || (dst_len < 100_000 && src_len > dst_len) {
                let _ = fs::copy(&cand, &db_in_sub);
            }
            let root_len = fs::metadata(&db_in_root).map(|m| m.len()).unwrap_or(0);
            if !db_in_root.exists() || (root_len < 100_000 && src_len > root_len) {
                let _ = fs::copy(&cand, &db_in_root);
            }
            break;
        }
    }

    // 1. Check if packaged sidecar binary exists
    let sidecar_candidates = vec![
        exe_dir.join("backend-x86_64-pc-windows-msvc.exe"),
        exe_dir.join("backend.exe"),
        exe_dir.join("binaries").join("backend-x86_64-pc-windows-msvc.exe"),
        root.join("desktop").join("src-tauri").join("binaries").join("backend-x86_64-pc-windows-msvc.exe"),
        root.join("binaries").join("backend-x86_64-pc-windows-msvc.exe"),
        root.join("backend-x86_64-pc-windows-msvc.exe"),
    ];

    let mut sidecar_exe: Option<PathBuf> = None;
    for cand in sidecar_candidates {
        if cand.exists() {
            sidecar_exe = Some(cand);
            break;
        }
    }

    let mut cmd = if let Some(exe_path) = sidecar_exe {
        let mut c = Command::new(exe_path);
        c.current_dir(data_dir);
        c.args(&[
            "--data-dir",
            data_dir.to_str().unwrap_or("./data"),
            "--config",
            config_in_data.to_str().unwrap_or("config.yaml"),
        ]);
        c
    } else {
        // Fallback to python command in dev mode
        let python_bin = std::env::var("PYTHON_PATH").unwrap_or_else(|_| "python".to_string());
        let mut c = Command::new(&python_bin);
        c.current_dir(root);
        c.args(&[
            "-m",
            "backend.launcher",
            "--data-dir",
            data_dir.to_str().unwrap_or("./data"),
            "--config",
            config_in_data.to_str().unwrap_or("config.yaml"),
        ]);
        c
    };

    cmd.env("PYTHONIOENCODING", "utf-8");
    cmd.env("PYTHONUTF8", "1");

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
        cmd.stdout(std::process::Stdio::null());
        cmd.stderr(std::process::Stdio::null());
    }

    let child = cmd
        .spawn()
        .map_err(|e| format!("Không thể khởi chạy backend: {e}"))?;

    let child_pid = child.id();

    // 2. Wait for fresh handshake file to be written and marked READY by the child process
    let start = Instant::now();
    let timeout = Duration::from_secs(25);

    while start.elapsed() < timeout {
        if handshake_path.exists() {
            if let Ok(content) = fs::read_to_string(&handshake_path) {
                if let Ok(hs) = serde_json::from_str::<HandshakeFile>(&content) {
                    if hs.status == "READY" && hs.port > 0 {
                        let actual_pid = hs.pid.or(Some(child_pid));
                        let info = BackendInfo {
                            instance_id: hs.instance_id.unwrap_or_default(),
                            host: hs.host,
                            port: hs.port,
                            session_token: hs.session_token,
                            pid: actual_pid,
                            status: "READY".to_string(),
                        };
                        return Ok((child, info));
                    }
                }
            }
        }
        thread::sleep(Duration::from_millis(250));
    }

    Err("Hết thời gian chờ backend sẵn sàng (Handshake Timeout)".to_string())
}

fn graceful_shutdown_backend(child_lock: &Arc<Mutex<Option<Child>>>, port_token: Option<(u16, String)>) {
    let mut guard = child_lock.lock().unwrap();
    if let Some(mut child) = guard.take() {
        // Attempt graceful HTTP shutdown first if port and token are known
        if let Some((port, token)) = port_token {
            let url = format!("http://127.0.0.1:{port}/api/shutdown");
            let _ = std::thread::spawn(move || {
                // Quick loopback post with curl or basic socket to trigger graceful shutdown
                let _ = Command::new("powershell")
                    .args(&[
                        "-NoProfile",
                        "-Command",
                        &format!(
                            "Invoke-RestMethod -Uri '{url}' -Method Post -Headers @{{ 'X-Session-Token' = '{token}' }} -TimeoutSec 2 -ErrorAction SilentlyContinue"
                        ),
                    ])
                    .output();
            });

            // Wait up to 3 seconds for graceful process exit
            let start = Instant::now();
            while start.elapsed() < Duration::from_secs(3) {
                if let Ok(Some(_)) = child.try_wait() {
                    return;
                }
                thread::sleep(Duration::from_millis(150));
            }
        }

        // Force kill if still running after timeout
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[tauri::command]
fn get_backend_info(state: State<AppState>) -> Result<BackendInfo, String> {
    let guard = state.backend_info.lock().unwrap();
    match &*guard {
        Some(info) => Ok(info.clone()),
        None => Err("Backend chưa sẵn sàng".to_string()),
    }
}

#[tauri::command]
fn restart_backend(state: State<AppState>) -> Result<BackendInfo, String> {
    let current_info = {
        let guard = state.backend_info.lock().unwrap();
        guard.as_ref().map(|i| (i.port, i.session_token.clone()))
    };

    graceful_shutdown_backend(&state.child_process, current_info);

    let (child, info) = spawn_python_backend(&state.project_root, &state.data_dir)?;
    {
        let mut child_guard = state.child_process.lock().unwrap();
        *child_guard = Some(child);
    }
    {
        let mut info_guard = state.backend_info.lock().unwrap();
        *info_guard = Some(info.clone());
    }

    Ok(info)
}

#[tauri::command]
fn exit_application(state: State<AppState>, _app: tauri::AppHandle) -> Result<(), String> {
    let current_info = {
        let guard = state.backend_info.lock().unwrap();
        guard.as_ref().map(|i| (i.port, i.session_token.clone()))
    };

    graceful_shutdown_backend(&state.child_process, current_info);

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        let _ = std::process::Command::new("taskkill")
            .args(&["/F", "/IM", "backend.exe", "/T"])
            .creation_flags(CREATE_NO_WINDOW)
            .output();
        let _ = std::process::Command::new("taskkill")
            .args(&["/F", "/IM", "backend-x86_64-pc-windows-msvc.exe", "/T"])
            .creation_flags(CREATE_NO_WINDOW)
            .output();
    }

    std::process::exit(0);
}

#[tauri::command]
fn hide_window(window: tauri::WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|e| e.to_string())
}

#[tauri::command]
fn is_autostart_enabled() -> bool {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        if let Ok(out) = std::process::Command::new("reg")
            .args(&["query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "/v", "TelegramBinanceSignalExecutor"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
        {
            return out.status.success();
        }
    }
    false
}

#[tauri::command]
fn enable_autostart() -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        let exe_path = std::env::current_exe().map_err(|e| e.to_string())?;
        let exe_str = exe_path.to_str().ok_or("Invalid exe path")?;
        let output = std::process::Command::new("reg")
            .args(&[
                "add",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "/v",
                "TelegramBinanceSignalExecutor",
                "/t",
                "REG_SZ",
                "/d",
                &format!("\"{}\"", exe_str),
                "/f",
            ])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .map_err(|e| e.to_string())?;
        if !output.status.success() {
            let err = String::from_utf8_lossy(&output.stderr);
            return Err(format!("Lỗi cấu hình khởi động cùng Windows: {}", err));
        }
        return Ok(());
    }
    #[cfg(not(target_os = "windows"))]
    Err("Tính năng chỉ hỗ trợ trên Windows".to_string())
}

#[tauri::command]
fn disable_autostart() -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        let _ = std::process::Command::new("reg")
            .args(&[
                "delete",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                "/v",
                "TelegramBinanceSignalExecutor",
                "/f",
            ])
            .creation_flags(CREATE_NO_WINDOW)
            .output();
        return Ok(());
    }
    #[cfg(not(target_os = "windows"))]
    Err("Tính năng chỉ hỗ trợ trên Windows".to_string())
}


#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    std::panic::set_hook(Box::new(|info| {
        if let Some(s) = info.payload().downcast_ref::<&str>() {
            eprintln!("PANIC MSG: {}", s);
        } else if let Some(s) = info.payload().downcast_ref::<String>() {
            eprintln!("PANIC MSG: {}", s);
        } else {
            eprintln!("PANIC: {:?}", info);
        }
    }));

    let project_root = locate_project_root();
    let data_dir = resolve_data_dir();
    let child_holder = Arc::new(Mutex::new(None));
    let info_holder = Arc::new(Mutex::new(None));

    let child_for_setup = Arc::clone(&child_holder);
    let info_for_setup = Arc::clone(&info_holder);
    let project_root_for_setup = project_root.clone();
    let data_dir_for_setup = data_dir.clone();

    let child_for_shutdown = Arc::clone(&child_holder);
    let info_for_shutdown = Arc::clone(&info_holder);

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .manage(AppState {
            backend_info: Arc::clone(&info_holder),
            child_process: Arc::clone(&child_holder),
            project_root,
            data_dir,
        })
        .setup(move |app| {
            if cfg!(debug_assertions) {
                let _ = app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                );
            }

            // Spawn backend on primary instance startup only
            match spawn_python_backend(&project_root_for_setup, &data_dir_for_setup) {
                Ok((child, info)) => {
                    *child_for_setup.lock().unwrap() = Some(child);
                    *info_for_setup.lock().unwrap() = Some(info);
                }
                Err(e) => {
                    eprintln!("Khởi động backend lúc init: {}", e);
                }
            }


            // Attempt to setup system tray gracefully without crashing the app
            let _ = (|| -> Result<(), Box<dyn std::error::Error>> {
                let item_show = MenuItem::with_id(app, "show_window", "Mở Cửa Sổ Dashboard", true, None::<&str>)?;
                let item_pause = MenuItem::with_id(app, "toggle_entry", "Tạm Dừng / Tiếp Tục Nhận Lệnh", true, None::<&str>)?;
                let item_quit = MenuItem::with_id(app, "quit_app", "Thoát Hoàn Toàn Ứng Dụng", true, None::<&str>)?;

                let tray_menu = MenuBuilder::new(app)
                    .item(&item_show)
                    .item(&item_pause)
                    .separator()
                    .item(&item_quit)
                    .build()?;

                let mut tray_builder = TrayIconBuilder::new()
                    .tooltip("Telegram Binance Signal Executor")
                    .menu(&tray_menu)
                    .show_menu_on_left_click(false)
                    .on_menu_event(|app, event| {
                        match event.id().as_ref() {
                            "show_window" => {
                                if let Some(window) = app.get_webview_window("main") {
                                    let _ = window.show();
                                    let _ = window.unminimize();
                                    let _ = window.set_focus();
                                }
                            }
                            "toggle_entry" => {
                                let _ = app.emit("tray_toggle_entry", ());
                            }
                            "quit_app" => {
                                if let Some(window) = app.get_webview_window("main") {
                                    let _ = window.show();
                                    let _ = window.unminimize();
                                    let _ = window.set_focus();
                                    let _ = window.emit("request_exit_confirmation", ());
                                }
                            }
                            _ => {}
                        }
                    })
                    .on_tray_icon_event(|tray, event| {
                        if let tauri::tray::TrayIconEvent::Click { button: tauri::tray::MouseButton::Left, button_state: tauri::tray::MouseButtonState::Up, .. } = event {
                            let app = tray.app_handle();
                            if let Some(window) = app.get_webview_window("main") {
                                if window.is_visible().unwrap_or(false) {
                                    let _ = window.hide();
                                } else {
                                    let _ = window.show();
                                    let _ = window.unminimize();
                                    let _ = window.set_focus();
                                }
                            }
                        }
                    });

                if let Some(icon) = app.default_window_icon() {
                    tray_builder = tray_builder.icon(icon.clone());
                }

                let _ = tray_builder.build(app)?;
                Ok(())
            })();

            // Explicitly show and bring to front on launch
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_backend_info,
            restart_backend,
            exit_application,
            hide_window,
            is_autostart_enabled,
            enable_autostart,
            disable_autostart,
        ])
        .on_window_event(move |window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.emit("request_exit_confirmation", ());
            }
        })
        .build(tauri::generate_context!())
        .expect("Lỗi khởi chạy ứng dụng")
        .run(move |_app_handle, event| match event {
            tauri::RunEvent::Exit => {
                let current_info = {
                    let guard = info_for_shutdown.lock().unwrap();
                    guard.as_ref().map(|i| (i.port, i.session_token.clone()))
                };
                graceful_shutdown_backend(&child_for_shutdown, current_info);
                #[cfg(target_os = "windows")]
                {
                    use std::os::windows::process::CommandExt;
                    const CREATE_NO_WINDOW: u32 = 0x08000000;
                    let _ = std::process::Command::new("taskkill")
                        .args(&["/F", "/IM", "backend.exe", "/T"])
                        .creation_flags(CREATE_NO_WINDOW)
                        .output();
                    let _ = std::process::Command::new("taskkill")
                        .args(&["/F", "/IM", "backend-x86_64-pc-windows-msvc.exe", "/T"])
                        .creation_flags(CREATE_NO_WINDOW)
                        .output();
                }
            }
            _ => {}
        });
}

