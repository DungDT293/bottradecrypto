; hooks.nsh - NSIS Pre-Install & Pre-Uninstall Hooks for Telegram Binance Signal Executor
; Dam bao dong toan bo tien trinh dang chay (App + Backend) truoc khi ghi de / go bo tap tin.

!macro NSIS_HOOK_PREINSTALL
    DetailPrint "Dang kiem tra va dong cac tien trinh cu truoc khi ghi de..."
    nsExec::Exec 'taskkill.exe /F /T /IM "backend-x86_64-pc-windows-msvc.exe"'
    nsExec::Exec 'taskkill.exe /F /T /IM "backend.exe"'
    nsExec::Exec 'taskkill.exe /F /T /IM "telegram-binance-signal-executor.exe"'
    Sleep 1500
!macroend

!macro NSIS_HOOK_PREUNINSTALL
    DetailPrint "Dang dung cac tien trinh ung dung va backend truoc khi go cai dat..."
    nsExec::Exec 'taskkill.exe /F /T /IM "backend-x86_64-pc-windows-msvc.exe"'
    nsExec::Exec 'taskkill.exe /F /T /IM "backend.exe"'
    nsExec::Exec 'taskkill.exe /F /T /IM "telegram-binance-signal-executor.exe"'
    Sleep 1500
!macroend
