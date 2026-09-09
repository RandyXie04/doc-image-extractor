import os
import sys
import urllib.request
import json
import subprocess
from pathlib import Path

GITHUB_REPO = 'RandyXie04/doc-image-extractor'
API_URL = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'

def check_latest_release():
    try:
        req = urllib.request.Request(API_URL, headers={'User-Agent': 'PDF-Toolkit-App'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            version = data.get('tag_name', '').lstrip('v')
            assets = data.get('assets', [])
            download_url = None
            for asset in assets:
                if asset['name'].endswith('.exe'):
                    download_url = asset['browser_download_url']
                    break
            return {
                'has_update': False, # will be compared by app.py
                'latest_version': version,
                'release_notes': data.get('body', ''),
                'download_url': download_url
            }
    except Exception as e:
        print(f'[Updater] Check update error: {e}')
        return None

def perform_update(download_url):
    if not getattr(sys, 'frozen', False):
        return {'status': 'error', 'msg': 'Cannot update in dev environment.'}
    
    current_exe = Path(sys.executable)
    new_exe = current_exe.with_suffix('.exe.new')
    
    try:
        print(f'[Updater] Downloading {download_url} to {new_exe}')
        req = urllib.request.Request(download_url, headers={'User-Agent': 'PDF-Toolkit-App'})
        with urllib.request.urlopen(req) as response:
            with open(new_exe, 'wb') as f:
                f.write(response.read())
        
        pid = str(os.getpid())
        updater_bat = current_exe.parent / 'updater.bat'
        
        if not updater_bat.exists():
            # Write fallback updater.bat if missing
            bat_content = ''@echo off\nset PID=%1\nset OLD=%2\nset NEW=%3\n:wait\ntasklist /FI ""PID eq %PID%"" | find ""%PID%"" >NUL\nif %ERRORLEVEL% == 0 (timeout /t 1 >NUL & goto wait)\nmove /y %NEW% %OLD%\nstart """" %OLD%\n''
            with open(updater_bat, 'w') as f:
                f.write(bat_content)
        
        print(f'[Updater] Launching updater.bat with PID: {pid}')
        subprocess.Popen(['cmd.exe', '/c', str(updater_bat), pid, str(current_exe), str(new_exe)], creationflags=subprocess.CREATE_NO_WINDOW)
        return {'status': 'success', 'msg': 'Update prepared. Restarting...'}
    except Exception as e:
        print(f'[Updater] Update failed: {e}')
        if new_exe.exists():
            new_exe.unlink()
        return {'status': 'error', 'msg': str(e)}
