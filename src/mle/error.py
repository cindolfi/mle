

UNKNOWN_ERROR = -1
MODEL_NOT_FOUND = -2
ENVIRONMENT_NOT_FOUND = -3
ENVIRONMENT_EXISTS = -4
METADATA_NOT_FOUND = -5
METADATA_EXISTS = -6
TENSORBOARD = -7
KEY_ERROR = -8
VALUE_ERROR = -9
TYPE_ERROR = -10


def print_error(*items):
    import sys
    from . import colored
    colored.print(*items, color='red', file=sys.stderr)


def handle(error):
    import subprocess
    from . import environment

    if isinstance(error, environment.ModelNotFoundError):
        errno = MODEL_NOT_FOUND
    elif isinstance(error, environment.EnvironmentNotFoundError):
        errno = ENVIRONMENT_NOT_FOUND
    elif isinstance(error, environment.EnvironmentExistsError):
        errno = ENVIRONMENT_EXISTS
    elif isinstance(error, environment.ConfigurationNotFoundError):
        errno = METADATA_NOT_FOUND
    elif isinstance(error, environment.ConfigurationExistsError):
        errno = METADATA_EXISTS
    elif isinstance(error, environment.tensorboard.TensorBoardError):
        errno = TENSORBOARD
    elif isinstance(error, KeyError):
        errno = KEY_ERROR
    elif isinstance(error, ValueError):
        errno = VALUE_ERROR
    elif isinstance(error, TypeError):
        errno = TYPE_ERROR
    elif isinstance(error, subprocess.CalledProcessError):
        errno = error.returncode
    else:
        try:
            errno = error.errno
        except AttributeError:
            errno = UNKNOWN_ERROR

    if errno >= UNKNOWN_ERROR and not isinstance(error, (OSError, subprocess.CalledProcessError)):
        print_error(type(error))
    print_error(error)

    return errno



