// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::OpenOptions;
use std::io::Write;

#[cfg(target_os = "windows")]
fn kill_stale_backends() {
    use std::process::Command;
    let _ = Command::new("taskkill")
        .args(&["/F", "/T", "/IM", "backend-x86_64-pc-windows-msvc.exe"])
        .output();
    let _ = Command::new("taskkill")
        .args(&["/F", "/T", "/IM", "backend.exe"])
        .output();
}

#[cfg(target_os = "windows")]
fn ensure_single_instance() -> Option<windows_sys::Win32::Foundation::HANDLE> {
    use windows_sys::Win32::Foundation::{ERROR_ALREADY_EXISTS, GetLastError};
    use windows_sys::Win32::System::Threading::CreateMutexW;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        FindWindowW, SetForegroundWindow, ShowWindow, SW_RESTORE,
    };

    let mutex_name: Vec<u16> = "Local\\TelegramBinanceSignalExecutorSingleInstance"
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();

    unsafe {
        let handle = CreateMutexW(std::ptr::null(), 1, mutex_name.as_ptr());
        if handle.is_null() {
            return None;
        }

        if GetLastError() == ERROR_ALREADY_EXISTS {
            let window_title: Vec<u16> = "Telegram Binance Signal Executor - Dashboard Quản Lý"
                .encode_utf16()
                .chain(std::iter::once(0))
                .collect();
            let hwnd = FindWindowW(std::ptr::null(), window_title.as_ptr());
            if !hwnd.is_null() {
                ShowWindow(hwnd, SW_RESTORE);
                SetForegroundWindow(hwnd);
                std::process::exit(0);
            }
            // If window not found, existing process is dead/stale, allow current instance to proceed
        }

        Some(handle)
    }
}

fn main() {
    std::panic::set_hook(Box::new(|info| {
        let payload_msg = if let Some(s) = info.payload().downcast_ref::<&str>() {
            s.to_string()
        } else if let Some(s) = info.payload().downcast_ref::<String>() {
            s.clone()
        } else {
            format!("{:?}", info)
        };
        eprintln!("PANIC: {}", payload_msg);
        if let Ok(mut f) = OpenOptions::new().create(true).append(true).open("crash.log") {
            let _ = writeln!(f, "PANIC: {}", payload_msg);
        }
    }));

    #[cfg(target_os = "windows")]
    let _mutex_guard = ensure_single_instance();

    #[cfg(target_os = "windows")]
    kill_stale_backends();

    app_lib::run();
}
