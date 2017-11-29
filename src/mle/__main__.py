# PYTHON_ARGCOMPLETE_OK

import argparse
import subprocess
import contextlib


def main():
    parser = argparse.ArgumentParser()

    command_argument = parser.add_argument('command')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)

    #   try to add autocompletion, if argcomplete not installed
    #   just move on with life
    with contextlib.suppress(ImportError):
        import argcomplete
        import pathlib
        import os

        commands = [command.name[4:]
                    for path in os.environ.get('PATH', '').split(':')
                    for command in pathlib.Path(path).glob('mle-*')]

        command_argument.completer = argcomplete.completers.ChoicesCompleter(commands)
        argcomplete.autocomplete(parser)

    args = parser.parse_args()

    try:
        return run_command('mle-' + args.command, args.arguments)
    except Exception as error:
        import mle.error
        return mle.error.handle(error)


def run_command(command, arguments):
    try:
        try:
            subprocess.run([command] + arguments, check=True)
        except FileNotFoundError:
            if not command.endswith('.py'):
                subprocess.run([command + '.py'] + arguments, check=True)
            else:
                raise
    except subprocess.CalledProcessError as error:
        return error.returncode
    else:
        return 0




if __name__ == '__main__':
    exit(main())


