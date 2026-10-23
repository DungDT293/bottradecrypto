@echo off
setlocal
cd /d "%~dp0"



echo [1/3] Kiem tra va don dep phien lam viec cu...
taskkill /F /IM app.exe >nul 2>&1
taskkill /F /IM backend.exe >nul 2>&1
taskkill /F /IM backend-x86_64-pc-windows-msvc.exe >nul 2>&1
del /F /Q "%LOCALAPPDATA%\com.bottradecrypto.executor\EBWebView\lockfile" >nul 2>&1
ping 127.0.0.1 -n 2 >nul

echo [2/3] Dong bo co so du lieu lich su Telegram va Binance...
del /F /Q "%APPDATA%\telegram_binance_signal_executor\*.session-shm" >nul 2>&1
del /F /Q "%APPDATA%\telegram_binance_signal_executor\*.session-wal" >nul 2>&1
del /F /Q "%APPDATA%\telegram_binance_signal_executor\*.db-shm" >nul 2>&1
del /F /Q "%APPDATA%\telegram_binance_signal_executor\*.db-wal" >nul 2>&1
del /F /Q "%APPDATA%\telegram_binance_signal_executor\data\*.session-shm" >nul 2>&1
del /F /Q "%APPDATA%\telegram_binance_signal_executor\data\*.session-wal" >nul 2>&1
del /F /Q "%APPDATA%\telegram_binance_signal_executor\data\*.db-shm" >nul 2>&1
del /F /Q "%APPDATA%\telegram_binance_signal_executor\data\*.db-wal" >nul 2>&1
if not exist "%APPDATA%\telegram_binance_signal_executor\data\trading_state.db" (
    if not exist "%APPDATA%\telegram_binance_signal_executor\data" mkdir "%APPDATA%\telegram_binance_signal_executor\data" >nul 2>&1
    if exist "%~dp0data\trading_state.db" (
        copy /y "%~dp0data\trading_state.db" "%APPDATA%\telegram_binance_signal_executor\data\trading_state.db" >nul 2>&1
    )
)
if not exist "%APPDATA%\telegram_binance_signal_executor\config.yaml" (
    copy /y "%~dp0config.yaml" "%APPDATA%\telegram_binance_signal_executor\config.yaml" >nul 2>&1
)
if not exist "%APPDATA%\telegram_binance_signal_executor\data\telegram_user.session" (
    if exist "%~dp0data\telegram_user.session" (
        copy /y "%~dp0data\telegram_user.session" "%APPDATA%\telegram_binance_signal_executor\data\telegram_user.session" >nul 2>&1
    )
)
if exist "%LOCALAPPDATA%\telegram-binance-signal-executor" (
    copy /y "%~dp0config.yaml" "%LOCALAPPDATA%\telegram-binance-signal-executor\config.yaml" >nul 2>&1
    if not exist "%LOCALAPPDATA%\telegram-binance-signal-executor\data" mkdir "%LOCALAPPDATA%\telegram-binance-signal-executor\data" >nul 2>&1
    copy /y "%~dp0data\channel_winrates_6_months.json" "%LOCALAPPDATA%\telegram-binance-signal-executor\data\channel_winrates_6_months.json" >nul 2>&1
    copy /y "%~dp0data\channel_winrates_6_months.json" "%APPDATA%\telegram_binance_signal_executor\data\channel_winrates_6_months.json" >nul 2>&1
    if exist "%~dp0dist\backend-x86_64-pc-windows-msvc.exe" (
        copy /y "%~dp0dist\backend-x86_64-pc-windows-msvc.exe" "%LOCALAPPDATA%\telegram-binance-signal-executor\backend-x86_64-pc-windows-msvc.exe" >nul 2>&1
        copy /y "%~dp0dist\backend-x86_64-pc-windows-msvc.exe" "%LOCALAPPDATA%\telegram-binance-signal-executor\backend.exe" >nul 2>&1
    )
    if exist "%~dp0desktop\src-tauri\target\release\app.exe" (
        copy /y "%~dp0desktop\src-tauri\target\release\app.exe" "%LOCALAPPDATA%\telegram-binance-signal-executor\app.exe" >nul 2>&1
    )
)


echo [3/3] Khoi dong ban phat hanh Dashboard moi nhat...
if exist "%LOCALAPPDATA%\telegram-binance-signal-executor\app.exe" (
    start "" "%LOCALAPPDATA%\telegram-binance-signal-executor\app.exe"
) else if exist "%~dp0desktop\src-tauri\target\release\app.exe" (
    start "" "%~dp0desktop\src-tauri\target\release\app.exe"
) else (
    echo Khong tim thay tap tin thuc thi Dashboard!
)

echo Hoan tat! Cua so Dashboard dang duoc mo...
:done
