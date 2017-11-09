"""
Run tensordboard from Python
"""
import subprocess
import time

import psutil


__all__ = ['start', 'stop', 'restart',
           'suspend', 'resume', 'suspender',
           'is_running', 'status', 'TensorBoardError']


class TensorBoardError(Exception):
    def __init__(self, message, is_running):
        super().__init__(message)
        self.is_running = is_running


try:
    import tensorflow

    def is_running():
        try:
            _find_process()
            return True
        except _NotRunning:
            return False


    def status():
        try:
            return 'running:  tensorboard ' + ' '.join(_find_process().cmdline()[2:])
        except _NotRunning:
            return 'not running'


    def start(logdir, host='127.0.0.1', port='6006', reload_interval=10, purge=False, cmdargs=None):
        if is_running():
            raise TensorBoardError('tensor board is already running',
                                is_running=True)

        if cmdargs is None:
            cmdargs = list()

        if '--logdir' not in cmdargs:
            cmdargs.extend(['--logdir', str(logdir)])

        if '--host' not in cmdargs:
            cmdargs.extend(['--host', host])

        if '--port' not in cmdargs:
            cmdargs.extend(['--port', port])

        if '--reload_interval' not in cmdargs:
            cmdargs.extend(['--reload_interval', str(reload_interval)])

        if purge:
            if '--purge_orphaned_data' not in cmdargs and '--nopurge_orphaned_data' not in cmdargs:
                cmdargs.append('--purge_orphaned_data')

        subprocess.Popen(['tensorboard'] + cmdargs,
                        stderr = subprocess.DEVNULL)

        if not is_running():
            raise TensorBoardError('failed to start tensor board',
                                is_running=False)


    def stop():
        try:
            process = _find_process()
            process.terminate()
        except _NotRunning:
            pass

        if is_running():
            raise TensorBoardError('failed to stop tensor board',
                                is_running=True)


    def restart():
        if not is_running():
            raise TensorBoardError('tensor board is not running',
                                is_running=False)

        suspend()
        resume(purge=True)


    def suspend():
        global _suspended

        try:
            process = _find_process()

            _suspended = _SuspendedProcess(process)

            process.terminate()
            time.sleep(0.2)

            if is_running():
                raise TensorBoardError('failed to suspend tensor board',
                                    is_running=True)
        except _NotRunning:
            pass


    def resume(purge=False, extra_args=None):
        global _suspended

        if not is_running() and _suspended is not None:

            if extra_args is None:
                extra_args = list()

            extra_args = _suspended.cmdline + extra_args

            if len(extra_args) > 0:
                if purge:
                    while '--nopurge_orphaned_data' in extra_args:
                        extra_args.remove('--nopurge_orphaned_data')
                else:
                    while '--purge_orphaned_data' in extra_args:
                        extra_args.remove('--purge_orphaned_data')

            if purge:
                if '--purge_orphaned_data' not in extra_args:
                    extra_args.append('--purge_orphaned_data')
            else:
                if '--nopurge_orphaned_data' not in extra_args:
                    extra_args.append('--nopurge_orphaned_data')

            try:
                subprocess.Popen(['tensorboard'] + extra_args,
                                cwd=_suspended.cwd,
                                env=_suspended.environ,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
            finally:
                _suspended = None

        if not is_running():
            raise TensorBoardError('failed to resume tensor board',
                                is_running=False)


    class suspender:
        def __init__(self, purge=False):
            self.purge = purge

        def __enter__(self):
            self.was_running = is_running()
            if self.was_running:
                suspend()

        def __exit__(self, *exc):
            if self.was_running:
                resume(purge=self.purge)




    class _NotRunning(Exception):
        pass

    class _SuspendedProcess:
        def __init__(self, process):
            self.cmdline = process.cmdline()[2:]
            self.cwd = process.cwd()
            self.environ = process.environ()

    _suspended = None


    def _find_process():
        for pid in psutil.pids():
            try:
                process = psutil.Process(pid)
                if process.name() == 'tensorboard':
                    return process
            except psutil.NoSuchProcess:
                pass

        raise _NotRunning()


except ImportError:
    def is_running():
        raise NotImplementedError('tensorflow is not installed')

    def status():
        raise NotImplementedError('tensorflow is not installed')

    def start(*args, **kwds):
        raise NotImplementedError('tensorflow is not installed')

    def stop():
        raise NotImplementedError('tensorflow is not installed')

    def restart():
        raise NotImplementedError('tensorflow is not installed')

    def suspend():
        raise NotImplementedError('tensorflow is not installed')

    def resume(*args, **kwds):
        raise NotImplementedError('tensorflow is not installed')

    class suspender:
        def __init__(self, *args, **kwds):
            pass

        def __enter__(self):
            pass

        def __exit__(self, *exc):
            pass






