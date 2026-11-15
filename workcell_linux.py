#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""WorkCell Linux: a small, offline, unprivileged batch workspace."""
import argparse
import codecs
import contextlib
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

VERSION = '0.1.0'
POLICY = {'schema': 1, 'network': 'none'}
BWRAP = '/usr/bin/bwrap'
DENIED = ('socket socketpair connect bind listen accept accept4 sendto sendmsg '
          'sendmmsg recvfrom recvmsg recvmmsg io_uring_setup io_uring_enter '
          'io_uring_register ptrace process_vm_readv process_vm_writev pidfd_getfd '
          'mount umount2 pivot_root move_mount open_tree fsopen fsconfig fsmount '
          'fspick mount_setattr setns unshare bpf keyctl add_key request_key '
          'perf_event_open userfaultfd reboot kexec_load kexec_file_load '
          'init_module finit_module delete_module swapon swapoff').split()


class Refusal(RuntimeError):
    pass


def safe_text(text):
    return ''.join(c if c.isprintable() or c in '\n\t' else '?' for c in text)


def check_host():
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise Refusal('需要 x86_64 Linux；首发验证目标为 Ubuntu 24.04。')
    if os.getuid() == 0 or os.getuid() != os.geteuid() or os.getgid() != os.getegid():
        raise Refusal('请用普通 Linux 用户运行，不要 sudo 或设置 setuid。')
    if not Path('/proc/self/mountinfo').is_file():
        raise Refusal('需要可用的 Linux procfs 和用户命名空间。')
    trusted(Path(BWRAP))
    result = subprocess.run([BWRAP, '--version'], capture_output=True, timeout=5,
                            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    match = re.fullmatch(rb'bubblewrap (\d+)\.(\d+)\.(\d+)\s*', result.stdout)
    if result.returncode or not match or tuple(map(int, match.groups())) < (0, 9, 0):
        raise Refusal('需要系统包管理器提供的 bubblewrap >= 0.9.0。')


def trusted(path):
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise Refusal('系统依赖的所有者或写权限不正确。')
    return path


def directory(path, create=False):
    """Walk with pinned directory descriptors; reject links/writable ancestors."""
    if not path.is_absolute() or '..' in path.parts or path == Path('/'):
        raise Refusal('状态目录必须是普通用户选择的绝对路径。')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=fd)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            st = os.fstat(fd)
            sticky = st.st_uid == 0 and bool(st.st_mode & stat.S_ISVTX)
            if st.st_uid not in (0, os.getuid()) or (st.st_mode & 0o022 and not sticky):
                raise Refusal('状态目录的父路径可被其他用户写入。')
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            raise Refusal('状态目录必须属于当前用户且权限为700。')
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_policy(fd):
    file = os.open('config.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        st = os.fstat(file)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600:
            raise Refusal('config.json必须是当前用户的独立600普通文件。')
        raw = os.read(file, 4097)
        if len(raw) > 4096:
            raise Refusal('配置文件过大。')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise Refusal('配置含有重复字段。')
                result[key] = value
            return result
        value = json.loads(raw, object_pairs_hook=unique)
        if value != POLICY or type(value.get('schema')) is not int:
            raise Refusal('本版仅支持schema=1、network=none，不接受额外挂载或联网配置。')
    finally:
        os.close(file)


def initialize(path):
    if path.exists():
        fd = directory(path)
        try:
            read_policy(fd)
            for name in ('home', 'workspace'):
                child = volume(fd, name)
                os.close(child)
        finally:
            os.close(fd)
        return
    fd = directory(path, create=True)
    try:
        for name in ('home', 'workspace'):
            os.mkdir(name, 0o700, dir_fd=fd)
        file = os.open('config.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(file, 'w', encoding='utf-8') as out:
            json.dump(POLICY, out)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
    finally:
        os.close(fd)


def volume(fd, name):
    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    st = os.fstat(child)
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        os.close(child)
        raise Refusal('HOME/workspace必须属于当前用户且权限为700。')
    return child


def check_volumes(path):
    # Refuse mount injection and hard links to files outside the intended data.
    for row in Path('/proc/self/mountinfo').read_text().splitlines():
        name = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), row.split()[4])
        if Path(name) == path or path in Path(name).parents:
            raise Refusal('状态目录及其内部不能包含额外挂载。')
    for base in (path/'home', path/'workspace'):
        for here, dirs, files in os.walk(base, followlinks=False):
            for name in dirs + files:
                st = (Path(here)/name).lstat()
                if stat.S_ISREG(st.st_mode) and st.st_nlink != 1:
                    raise Refusal('数据目录含有硬链接；请复制普通文件后重试。')
                if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
                    raise Refusal('数据目录只接受普通文件、目录和符号链接。')


def memory_file(data):
    fd = os.memfd_create('workcell-linux', os.MFD_CLOEXEC)
    os.write(fd, data)
    os.lseek(fd, 0, os.SEEK_SET)
    return fd


def filter_file():
    lib = ctypes.CDLL('libseccomp.so.2')
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    ctx = lib.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW; foreign ABIs are killed.
    if not ctx:
        raise Refusal('无法创建seccomp过滤器。')
    fd = memory_file(b'')
    try:
        for name in DENIED + ['clone3']:
            number = lib.seccomp_syscall_resolve_name(name.encode('ascii'))
            action = 0x00050000 | (errno.ENOSYS if name == 'clone3' else errno.EPERM)
            if number < 0 or lib.seccomp_rule_add(ctx, action, number, 0) != 0:
                raise Refusal('无法建立所需系统调用限制。')
        if lib.seccomp_export_bpf(ctx, fd) != 0:
            raise Refusal('无法导出seccomp过滤器。')
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except BaseException:
        os.close(fd)
        raise
    finally:
        lib.seccomp_release(ctx)


def stream(command, fds, timeout):
    env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8'}
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, close_fds=True, pass_fds=fds,
                          env=env, cwd='/', start_new_session=True) as proc:
        try:
            start, count = time.monotonic(), 0
            with selectors.DefaultSelector() as poll:
                for source, dest in ((proc.stdout, sys.stdout), (proc.stderr, sys.stderr)):
                    poll.register(source, selectors.EVENT_READ, (dest, codecs.getincrementaldecoder('utf-8')('replace')))
                while poll.get_map():
                    if time.monotonic() - start > timeout:
                        raise Refusal('任务超时；本次进程已关闭，HOME/workspace保留。')
                    for key, _ in poll.select(0.1):
                        raw = os.read(key.fd, 16384)
                        count += len(raw)
                        if count > 64*1024*1024:
                            raise Refusal('任务输出超过64MiB；请把大量结果写入/workspace。')
                        dest, decoder = key.data
                        dest.write(safe_text(decoder.decode(raw, final=not raw)))
                        dest.flush()
                        if not raw:
                            poll.unregister(key.fileobj)
            return proc.wait(timeout=max(0.1, timeout-(time.monotonic()-start)))
        except BaseException:
            proc.kill()  # bubblewrap's parent-death chain also kills its sandbox.
            proc.wait()
            raise


def run(path, args, timeout):
    if not args or args[0].startswith('-'):
        raise Refusal('run后使用 -- 和要运行的Linux命令。')
    check_host()
    with contextlib.ExitStack() as stack:
        fd = directory(path)
        stack.callback(os.close, fd)
        read_policy(fd)
        check_volumes(path)
        home, work = volume(fd, 'home'), volume(fd, 'workspace')
        stack.callback(os.close, home)
        stack.callback(os.close, work)
        seccomp = filter_file()
        passwd = memory_file(('work:x:%d:%d:WorkCell:/home/work:/bin/sh\n' % (os.getuid(), os.getgid())).encode())
        group = memory_file(('work:x:%d:\n' % os.getgid()).encode())
        for file in (seccomp, passwd, group):
            stack.callback(os.close, file)
        command = [BWRAP, '--unshare-all', '--unshare-user', '--unshare-net',
                   '--unshare-pid', '--unshare-ipc', '--unshare-uts',
                   '--disable-userns', '--cap-drop', 'ALL', '--new-session',
                   '--die-with-parent', '--hostname', 'workcell', '--clearenv']
        for name in ('bin', 'sbin', 'lib', 'lib64'):
            source = Path('/usr')/name
            if source.is_dir():
                command += ['--ro-bind', str(trusted(source)), str(source)]
                command += ['--symlink', 'usr/'+name, '/'+name]
        command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                    '--tmpfs', '/run', '--dir', '/etc', '--dir', '/home',
                    '--ro-bind-data', str(passwd), '/etc/passwd',
                    '--ro-bind-data', str(group), '/etc/group']
        if Path('/etc/ld.so.cache').is_file():
            command += ['--ro-bind', str(trusted(Path('/etc/ld.so.cache'))), '/etc/ld.so.cache']
        command += ['--bind', '/proc/self/fd/'+str(home), '/home/work',
                    '--bind', '/proc/self/fd/'+str(work), '/workspace',
                    '--setenv', 'HOME', '/home/work', '--setenv', 'USER', 'work',
                    '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8',
                    '--setenv', 'LC_ALL', 'C.UTF-8', '--setenv', 'TZ', 'UTC0',
                    '--setenv', 'TMPDIR', '/tmp', '--chdir', '/workspace',
                    '--seccomp', str(seccomp), '--', *args]
        return stream(command, (home, work, seccomp, passwd, group), timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description='WorkCell Linux：默认断网的命令行批处理工作区')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--state', type=Path, default=Path.home()/'.local/share/workcell-linux')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('init', help='创建独立数据目录；已有正确目录保持数据')
    sub.add_parser('status', help='读取版本、目录和固定离线策略')
    sub.add_parser('doctor', help='实际启动一个无联网的短命诊断命令')
    launch = sub.add_parser('run', help='运行一个离线命令，标准输入关闭')
    launch.add_argument('--timeout', type=int, default=300)
    launch.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        check_host()
        if args.action == 'init':
            initialize(args.state)
            print('已准备独立HOME/workspace；默认断网。')
            return 0
        fd = directory(args.state)
        try:
            read_policy(fd)
        finally:
            os.close(fd)
        if args.action == 'status':
            print(json.dumps({'version': VERSION, 'state': str(args.state), **POLICY}, ensure_ascii=False))
            return 0
        if args.action == 'doctor':
            result = run(args.state, ['/usr/bin/python3', '-I', '-S', '-c', "import os;assert os.getuid()!=0;print('工作区可启动；系统限制已加载，联网关闭。')"], 10)
            if result:
                raise Refusal('隔离诊断未通过；检查bubblewrap/用户命名空间/AppArmor策略，不要关闭系统防护绕过。')
            return 0
        if not 1 <= args.timeout <= 86400:
            raise Refusal('timeout必须在1至86400秒之间。')
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        return run(args.state, command, args.timeout)
    except (Refusal, OSError, ValueError, subprocess.SubprocessError) as error:
        print('WCL-E01 '+safe_text(str(error)), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('已中断，工作文件保留。', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
