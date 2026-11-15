"""Real Linux acceptance using a temporary fixture, never personal work data."""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT/'workcell_linux.py'


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix='workcell-linux-qa-') as tmp:
        root = Path(tmp)
        state = root/'state'
        outside = root/'outside-secret'
        outside.write_text('not-in-workspace')
        prefix = [sys.executable, '-I', '-S', '-B', str(ENTRY), '--state', str(state)]
        def cli(*args, code=0, timeout=30):
            result = subprocess.run([*prefix, *args], capture_output=True, timeout=timeout,
                                    env=dict(os.environ, WORKCELL_SECRET='not-in-child', HTTPS_PROXY='http://127.0.0.1:9'))
            assert result.returncode == code, (args, result.returncode, result.stdout.decode(errors='replace'), result.stderr.decode(errors='replace'))
            return result
        def python(text, code=0):
            return cli('run', '--', '/usr/bin/python3', '-I', '-S', '-c', text, code=code)
        cli('init')
        cli('doctor')
        assert json.loads(cli('status').stdout)['network'] == 'none'
        code = """import os,socket,ctypes,pathlib,stat
assert os.getuid()!=0 and os.geteuid()==os.getuid()
assert pathlib.Path.cwd()==pathlib.Path('/workspace')
assert os.environ['HOME']=='/home/work' and os.environ['TZ']=='UTC0'
assert 'WORKCELL_SECRET' not in os.environ and 'HTTPS_PROXY' not in os.environ
status=pathlib.Path('/proc/self/status').read_text()
assert 'NoNewPrivs:\t1' in status and 'CapEff:\t0000000000000000' in status and 'Seccomp:\t2' in status
for family in (socket.AF_INET,socket.AF_INET6,socket.AF_UNIX):
    try: socket.socket(family,socket.SOCK_STREAM)
    except PermissionError: pass
    else: raise AssertionError('Socket creation allowed')
assert not pathlib.Path(%r).exists()
assert not pathlib.Path('/mnt/c').exists() and not pathlib.Path('/run/user').exists()
assert not pathlib.Path('/etc/shadow').exists() and not pathlib.Path('/usr/local').exists()
for f in pathlib.Path('/proc/self/fd').iterdir():
    try: target=os.readlink(f)
    except FileNotFoundError: continue
    assert %r not in target,('Leaked host fd',target)
pathlib.Path('/workspace/hello.txt').write_text('你好')
pathlib.Path('/home/work/note').write_text('persist')
lib=ctypes.CDLL(None,use_errno=True)
assert lib.unshare(0x40000000)==-1 and ctypes.get_errno()==1
print('isolation-ready')
""" % (str(outside), str(root))
        assert b'isolation-ready' in python(code).stdout
        checks += ['actual-namespaces-seccomp', 'IPv4-IPv6-Unix-sockets-denied', 'host-files-environment-and-fds-hidden']
        assert (state/'workspace/hello.txt').read_text() == '你好'
        cli('init')
        python("from pathlib import Path;assert Path('/home/work/note').read_text()=='persist';assert Path('hello.txt').read_text()=='你好'")
        checks.append('workspace-and-HOME-persist-after-reopen')
        cli('run', '--', '/usr/bin/false', code=1)
        assert b'?' in python("print(chr(27)+']52;c;payload'+chr(7))").stdout
        checks += ['child-exit-code', 'terminal-controls-filtered']
        cli('run', '--timeout', '1', '--', '/usr/bin/sleep', '30', code=2)
        delayed = "import time;from pathlib import Path;time.sleep(2);Path('/workspace/late-child').write_text('unexpected')"
        parent = 'import subprocess,time;subprocess.Popen(["/usr/bin/python3","-I","-S","-c",'+repr(delayed)+']);time.sleep(30)'
        cli('run', '--timeout', '1', '--', '/usr/bin/python3', '-I', '-S', '-c', parent, code=2)
        time.sleep(3)
        assert not (state/'workspace/late-child').exists(), 'A descendant survived the timeout'
        python("from pathlib import Path;assert Path('hello.txt').read_text()=='你好'")
        checks.append('timeout-stops-task-and-descendants-and-preserves-data')
        config = state/'config.json'
        saved = config.read_bytes()
        for bad in [b'{"schema":1,"network":"host"}', b'{"schema":1,"network":"none","mount":"/"}', b'{"schema":1,"schema":1,"network":"none"}']:
            config.write_bytes(bad)
            cli('run', '--', '/usr/bin/true', code=2)
        config.write_bytes(saved)
        config.chmod(0o644)
        cli('run', '--', '/usr/bin/true', code=2)
        config.chmod(0o600)
        checks.append('config-network-mount-duplicate-and-permission-refused')
        link = state/'workspace/linked'
        os.link(outside, link)
        cli('run', '--', '/usr/bin/true', code=2)
        link.unlink()
        (state/'workspace/escape').symlink_to(outside)
        python("from pathlib import Path;assert not Path('/workspace/escape').exists()")
        (state/'workspace/escape').unlink()
        checks.append('hardlinks-refused-and-symlinks-cannot-reveal-host')
        home = state/'home'
        home.rename(state/'saved-home')
        home.symlink_to(root, target_is_directory=True)
        cli('run', '--', '/usr/bin/true', code=2)
        home.unlink()
        (state/'saved-home').rename(home)
        checks.append('linked-volume-refused')
        assert outside.read_text() == 'not-in-workspace'
        cli('doctor')
        checks.append('outside-canary-and-recovery')
        os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        distribution = {key: os_release.get(key, '').strip('"') for key in ('ID', 'VERSION_ID')}
        dependency = subprocess.run(['/usr/bin/bwrap', '--version'], capture_output=True, check=True).stdout.decode().strip()
        result = {'passed': True, 'version': '0.1.0', 'platform': sys.platform, 'checks': checks,
                  'distribution': distribution, 'python': sys.version.split()[0], 'bubblewrap': dependency,
                  'execution': 'independent temporary Linux state; real bubblewrap/seccomp',
                  'desktop_or_customer_machine_test': False}
        print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
