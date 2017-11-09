
import sys

from . import environment
from . import utils


UNKNOWN_ERROR = -1
NO_CURRENT_MODEL = -2
MODEL_NOT_FOUND = -3
ENVIRONMENT_NOT_FOUND = -4
ENVIRONMENT_EXISTS = -5
ENVIRONMENT_NOT_ACTIVE = -6
METADATA_NOT_FOUND = -7
METADATA_EXISTS = -8
TENSORBOARD = -9


def print_error(*items):
    print(utils.colored(*items, color='red'), file=sys.stderr)

def handle(error):
    if isinstance(error, environment.NoCurrentModelError):
        errno = NO_CURRENT_MODEL
    elif isinstance(error, environment.ModelNotFoundError):
        errno = MODEL_NOT_FOUND
    elif isinstance(error, environment.EnvironmentNotFoundError):
        errno = ENVIRONMENT_NOT_FOUND
    elif isinstance(error, environment.EnvironmentExistsError):
        errno = ENVIRONMENT_EXISTS
    elif isinstance(error, environment.EnvironmentNotActiveError):
        errno = ENVIRONMENT_NOT_ACTIVE
    elif isinstance(error, environment.ConfigurationNotFoundError):
        errno = METADATA_NOT_FOUND
    elif isinstance(error, environment.ConfigurationExistsError):
        errno = METADATA_EXISTS
    elif isinstance(error, environment.tensorboard.TensorBoardError):
        errno = TENSORBOARD
    else:
        try:
            errno = error.errno
        except AttributeError:
            errno = errno.UNKNOWN_ERROR

    if errno >= UNKNOWN_ERROR and not isinstance(error, OSError):
        print_error(type(error))
    print_error(error)

    return errno



