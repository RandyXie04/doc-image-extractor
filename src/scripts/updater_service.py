import os
import sys
import urllib.request
import urllib.error
import urllib.parse
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

GITHUB_REPO: str = 'RandyXie04/doc-image-extractor'
API_URL: str = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'

def check_latest_release() -> Dict[str, Any]:
    """
    Query GitHub Releases API with desensitized error handling.
    Safely interprets HTTP 404 as 'no releases published yet'.
    """
    try:
        req = urllib.request.Request(
            API_URL,
            headers={
                'User-Agent': 'PDF-Toolkit-App',
                'Accept': 'application/vnd.github.v3+json'
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            version = data.get('tag_name', '').lstrip('v')
            assets = data.get('assets', [])
            download_url: Optional[str] = None
            for asset in assets:
                asset_name = asset.get('name', '')
                if asset_name.endswith('.exe'):
                    raw_url = asset.get('browser_download_url', '')
                    # Validate URL host to prevent redirect hijacking
                    parsed = urllib.parse.urlparse(raw_url)
                    if parsed.scheme == 'https' and parsed.netloc in ('github.com', 'objects.githubusercontent.com'):
                        download_url = raw_url
                        break

            return {
                'status': 'success',
                'has_update': False,
                'latest_version': version,
                'release_notes': data.get('body', ''),
                'download_url': download_url,
                'msg': '檢查更新成功'
            }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # 404 Not Found indicates repository has no releases yet
            return {
                'status': 'no_releases',
                'has_update': False,
                'latest_version': None,
                'release_notes': '',
                'download_url': None,
                'msg': '目前線上尚未有發布版本，您目前運行的是本機版本。'
            }
        return {
            'status': 'error',
            'has_update': False,
            'msg': f'GitHub 服務響應異常 (HTTP {e.code})'
        }
    except (urllib.error.URLError, TimeoutError):
        return {
            'status': 'error',
            'has_update': False,
            'msg': '無法連線至 GitHub 伺服器，請確認網路連線。'
        }
    except Exception:
        return {
            'status': 'error',
            'has_update': False,
            'msg': '檢查更新過程中發生未預期異常。'
        }

def perform_update(download_url: str) -> Dict[str, Any]:
    """
    Download verified binary and execute updater process securely.
    """
    if not getattr(sys, 'frozen', False):
        return {'status': 'error', 'msg': '開發調試環境不支援自我覆寫熱更新。'}
    
    # URL validation
    parsed = urllib.parse.urlparse(download_url)
    if parsed.scheme != 'https' or parsed.netloc not in ('github.com', 'objects.githubusercontent.com'):
        return {'status': 'error', 'msg': '不合法的更新下載來源。'}

    current_exe = Path(sys.executable).resolve()
    new_exe = current_exe.with_suffix('.exe.new')
    
    try:
        req = urllib.request.Request(
            download_url,
            headers={'User-Agent': 'PDF-Toolkit-App'}
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            with open(new_exe, 'wb') as f:
                while chunk := response.read(65536):
                    f.write(chunk)
        
        pid = str(os.getpid())
        updater_bat = current_exe.parent / 'updater.bat'
        
        if not updater_bat.exists():
            bat_content = (
                '@echo off\r\n'
                'set PID=%1\r\n'
                'set OLD=%2\r\n'
                'set NEW=%3\r\n'
                ':wait\r\n'
                'tasklist /FI "PID eq %PID%" 2>NUL | find "%PID%" >NUL\r\n'
                'if %ERRORLEVEL% == 0 (timeout /t 1 /nobreak >NUL & goto wait)\r\n'
                'move /y %NEW% %OLD%\r\n'
                'start "" %OLD%\r\n'
            )
            with open(updater_bat, 'w', encoding='ascii') as f:
                f.write(bat_content)
        
        subprocess.Popen(
            ['cmd.exe', '/c', str(updater_bat), pid, str(current_exe), str(new_exe)],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return {'status': 'success', 'msg': '更新包下載完成，正在重啟主程式...'}
    except Exception:
        if new_exe.exists():
            try:
                new_exe.unlink()
            except OSError:
                pass
        return {'status': 'error', 'msg': '更新下載失敗，請稍後重試。'}

