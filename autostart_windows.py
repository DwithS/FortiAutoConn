import os
import sys
import subprocess
from logger import logger

def get_paths():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        logger.error("[Autostart] APPDATA 환경 변수를 찾을 수 없습니다.")
        sys.exit(1)
        
    startup_dir = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    shortcut_path = os.path.join(startup_dir, "FortiAutoConn.lnk")
    
    # run.bat이 있는 절대 경로 확인
    current_dir = os.path.abspath(os.path.dirname(__file__))
    target_path = os.path.join(current_dir, "run.bat")
    
    return startup_dir, shortcut_path, target_path, current_dir

def install():
    startup_dir, shortcut_path, target_path, current_dir = get_paths()
    
    if not os.path.exists(target_path):
        logger.error(f"[Autostart] 대상 실행 파일({target_path})이 존재하지 않습니다. 먼저 setup.bat을 실행해 주세요.")
        return False
        
    logger.info(f"[Autostart] Windows 시작 프로그램 등록 중: {shortcut_path}")
    
    # WScript.Shell COM 객체를 활용하여 PowerShell로 바로가기 생성
    # WindowStyle = 7은 최소화(Minimized) 상태로 실행하여 부팅 시 검은 CMD 창이 노출되지 않도록 방지합니다.
    ps_script = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
    $Shortcut.TargetPath = '{target_path}'
    $Shortcut.WorkingDirectory = '{current_dir}'
    $Shortcut.WindowStyle = 7
    $Shortcut.Description = 'FortiAutoConn Auto Start'
    $Shortcut.Save()
    """
    
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info("[Autostart] Windows 로그인 시 자동 실행 등록 성공!")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"[Autostart] 바로가기 등록 실패: {e.stderr}")
        return False

def uninstall():
    _, shortcut_path, _, _ = get_paths()
    
    if os.path.exists(shortcut_path):
        try:
            os.remove(shortcut_path)
            logger.info(f"[Autostart] Windows 자동 실행 등록 해제 완료: {shortcut_path}")
            return True
        except Exception as e:
            logger.error(f"[Autostart] 자동 실행 바로가기 삭제 실패: {e}")
            return False
    else:
        logger.info("[Autostart] 등록된 자동 실행 바로가기가 없습니다.")
        return True

def status():
    _, shortcut_path, _, _ = get_paths()
    is_installed = os.path.exists(shortcut_path)
    
    if is_installed:
        print("Status: INSTALLED")
        print(f"Path: {shortcut_path}")
    else:
        print("Status: NOT_INSTALLED")
        
    return is_installed

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python autostart_windows.py [install | uninstall | status]")
        sys.exit(1)
        
    action = sys.argv[1].lower()
    
    if action == "install":
        success = install()
        sys.exit(0 if success else 1)
    elif action == "uninstall":
        success = uninstall()
        sys.exit(0 if success else 1)
    elif action == "status":
        status()
        sys.exit(0)
    else:
        print(f"알 수 없는 옵션: {action}")
        print("옵션: install, uninstall, status")
        sys.exit(1)
