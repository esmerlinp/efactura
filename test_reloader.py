import os
import platform
import subprocess
import sys

if platform.system() == 'Darwin':
    os.environ['DYLD_FALLBACK_LIBRARY_PATH'] = '/opt/homebrew/lib'

if os.environ.get('IS_CHILD') == '1':
    print("CHILD DYLD:", os.environ.get('DYLD_FALLBACK_LIBRARY_PATH'))
    try:
        import weasyprint
        print("Child loaded weasyprint")
    except Exception as e:
        print("Child failed:", e)
else:
    print("PARENT DYLD:", os.environ.get('DYLD_FALLBACK_LIBRARY_PATH'))
    try:
        import weasyprint
        print("Parent loaded weasyprint")
    except Exception as e:
        print("Parent failed:", e)
    
    env = os.environ.copy()
    env['IS_CHILD'] = '1'
    subprocess.run([sys.executable, "test_reloader.py"], env=env)
