"""
Environment management


A project environment provides a workspace for creating and evaluating
a series of models.  An environment is a directory that contains of a
configuration file and at least one set of model environments.

An environment is a directory, configuration and one or more sets
of model environments.

An environment's configuration is collection of key, value mappings
called variables.  It is constructed by logically merging the contents
of three configuration files: a local file, a global file, and a
system file.  This is done in a hiearchical manner, analgous to how
cascaded style sheets are treated.  Naming conflicts are resolved
by giving local variables precedence over global variables, which in
turn, take precedence over system variables.

Each environment has its own local configuration file.  It is named
LOCAL_CONFIG_FILENAME and is stored in the environment's directory.

A system may have one, several or no global configuration files.  A single
global configuration is generally shared by a group of environments.  Every
global configuration file is named GLOBAL_CONFIG_FILENAME.  The particular
global configuration used by an environment is searched for in the
following order,
    1.  MLE_GLOBAL_CONFIG operating system environment variable
    1.  Up the file system tree starting in the environment's directory
    2.  In the user's home directory

A single system wide configuration is shared by every environment.  It is
searched for in the following order,
    1.  MLE_SYSTEM_CONFIG operating system environment variable
    2.  SYSTEM_CONFIG_FILENAME


Configurations are stored as a single JSON object.  By convention, dot
separated names are used to group variables.  The following variables are
added as fallback defaults to all configurations:

## Environment Creation
env.directories: a list of relative directory paths created in new environments
default = []
env.on_create: a script that is run when a new environment is created
default = None
env.on_delete: a script that is run when an environment is deleted
default = None

##  Environment Logging
env.log.filename: the file name where MLE logging is directed
default = mle.log
env.log.directory: the relative path to the environment's logging output
default = logs

## Model Environment Naming
model.prefix: relative path to the directory containing model environments
default =
model.active_name: the name of the symbolic link to the active model environment's directory
default = model
model.directory_name: the name of a model environment's directory (without the identifier)
default = model

## Model Environment Creation
model.on_create: a script that is run when a new model environment is created
default = None
model.on_delete: a script that is run when a model environment is deleted
default = None
model.directories: a list of directories created in new model environments
default = []
model.summary: file name used for general model information
default = summary

##  Model Environment Logging
model.log.default: the file name used by default for model environment logging
default = train.log
model.log.directory: the relative path to a model environment's logging output
default = logs

##  Logging
log.default:
default = mle.log

log.extension:
default = .log

log.editor: the default program used to edit log files
defaut = nano

##  General
editor: the default program used to edit files
default = nano


model.prefix: '',
model.directories: [],
model.active_name: 'model',
model.directory_name: 'model',
model.on_create: None,
model.on_delete: None,
model.summary: 'summary',
model.log.default: 'train.log',
model.log.directory: 'logs',
log.default: 'mle.log',
log.extension: '.log',
log.editor: 'nano',
env.directories: [],
env.on_create: None,
env.on_delete: None,
env.log.filename: 'mle.log',
env.log.directory: 'logs',
editor: 'nano',


#   Model Environment
A model environment is a workspace for creating and evaluating a single model.
It is assigned a unique non-negative integer identifier and consists of a
directory and a configuration.

The full path to the directory is constructed by joining the project
environment's directory, the relative path stored in the environment
variable 'model.prefix', and the name of the directory.  The name of
the directory is the concatenation of the project environment's
'model.directory_name' variable and the model environment's identifier.


Every model environment contains an optional file that gives a summary
of the model.  This exact contents and format of this file is application
specific but it is intended to include information such as model parameters,
training parameters and metrics, evaluation statistics, etc.  The summary
file's name is stored in the environment variable 'model.summary'.  It
is accessible as an absolute pathlib.Path object via the ModelEnvironment
summary_path property.


#   Multiple Model Environment Sets

An environment can support multiple sets of model environments
by using its 'model.prefix' variable to choose amongst various
subdirectories.




#   Example Layout

projects/
    .mle.config
    my_project/
        .mle.environ (w/ model.prefix = models)
        src/
        logs/
        models/
            model/ (symbolic link to the active model directory)
            model0/
                metadata
                summary
                logs/
            model1/
                metadata
                summary
                logs/
            model4/
                metadata
                summary
                logs/

    your_project/
        .mle.environ (w/ model.prefix = '')
        src/
        logs/
        model/ (symbolic link to the active model directory)
        model0/
            .mle.model
            summary
            logs/
        model1/
            .mle.model
            summary
            logs/
        model4/
            .mle.model
            summary
            logs/





"""
import pathlib
import os.path
import re
import shutil
import json
import bisect
import weakref
import threading
import contextlib
import copy
import types
import subprocess
import numbers
import sys
import abc
import logging
import collections

import watchdog.events
import watchdog.observers

from . import tensorboard
from . import configuration
from .callbacks import CallbackSet
from .synchronized import synchronized
from . import orderedset



DEFAULT_CONFIGURATION = {
    'model.prefix': '',
    'model.directories': list(),
    'model.active_name': 'model',
    'model.directory_name': 'model',
    'model.on_create': None,
    'model.on_delete': None,
    'model.summary': 'summary',
    'model.log.default': 'train.log',
    'model.log.directory': 'logs',
    'log.default': 'mle.log',
    'log.extension': '.log',
    'log.editor': 'nano',
    'env.directories': list(),
    'env.on_create': None,
    'env.on_delete': None,
    'env.log.filename': 'mle.log',
    'env.log.directory': 'logs',
    'config.editor': 'nano',
    'editor': 'nano',
}

GLOBAL_CONFIG_FILENAME = '.mle.config'
SYSTEM_CONFIG_FILENAME = '/etc/mle.config'
LOCAL_CONFIG_FILENAME = '.mle.environ'
MODEL_CONFIG_FILENAME = '.mle.model'



class EnvironmentException(Exception):
    """Base class for all Environment exceptions"""


class ConfigurationNotFoundError(EnvironmentException):
    def __init__(self, level):
        super().__init__('{} configuration not found'.format(level))


class ConfigurationExistsError(EnvironmentException):
    def __init__(self, path):
        super().__init__('configuration already exists: '
                         '{}'.format(path))



class EnvironmentNotFoundError(EnvironmentException):
    def __init__(self, path):
        if path:
            super().__init__('\'{}\' is not an environment'.format(path))
        else:
            super().__init__('environment not found')

class EnvironmentExistsError(EnvironmentException):
    def __init__(self, path):
        super().__init__('\'{}\' is already an environment'.format(path))



class ModelNotFoundError(EnvironmentException):
    def __init__(self, environment, model):
        if model is None:
            message = ('environment \'{}\' does not have '
                       'an active model'.format(environment.directory))
        else:
            message = ('environment \'{}\' does not have '
                       'model \'{}\''.format(environment.directory, model))
        super().__init__(message)
        self.environment = environment
        self.model = model


class ModelExistsError(EnvironmentException):
    def __init__(self, environment, model):
        super().__init__('model \'{}\' already exists '
                         'in environment \'{}\''.format(model, environment.directory))
        self.environment = environment
        self.model = model




def _read_only_copy_default_configuration():
    return types.MappingProxyType(copy.deepcopy(DEFAULT_CONFIGURATION))




def as_path(path):
    return pathlib.Path(str(path))


def create_configuration(path, variables=None):
    """
    Create an environment configuration file

    Args:
        variables(mapping): key/value pairs to write to the configuration file
    """
    path = as_path(path)
    if path.exists():
        raise ConfigurationExistsError(path)

    if variables is None:
        variables = dict()

    with path.open('w') as file:
        json.dump(variables, file, indent=4, sort_keys=True)



def find_system_configuration():
    """
    Find the system configuration file

    Returns:
        The path (pathlib.Path) to the system configuration file

    Raises:
        ConfigurationNotFoundError
    """
    config_path = os.environ.get('MLE_SYSTEM_CONFIG', '')

    if config_path:
        config_path = pathlib.Path(config_path)
    else:
        config_path = pathlib.Path(SYSTEM_CONFIG_FILENAME)

    if not config_path.exists():
        raise ConfigurationNotFoundError('system')

    return config_path


def create_system_configuration():
    """
    Create a system configuration file
    """
    config_path = os.environ.get('MLE_SYSTEM_CONFIG', '')
    if config_path:
        config_path = pathlib.Path(config_path)
    else:
        config_path = pathlib.Path(SYSTEM_CONFIG_FILENAME)

    create_configuration(config_path,
                         DEFAULT_CONFIGURATION)
    return system_configuration()


def system_configuration():
    """
    System configuration object factory

    Returns:
        Configuration object

    Raises:
        ConfigurationNotFoundError
    """
    config = configuration.Configuration(find_system_configuration())
    config.defaults = _read_only_copy_default_configuration()

    return config





def find_global_configuration(path=None):
    """
    Find the global configuration file

    If path is None and OS environment variable MLE_GLOBAL_CONFIG is
    set to a non-empty value, it is used as the path to the global
    configuration file.  Otherwise, this function searches for the file
    named by the GLOBAL_CONFIG_FILENAME module attribute
        1. up the file system tree starting from path
           (current directory if path is None)
        2. in the user's home directory

    Args:
        path: directory to search from or None

    Returns:
        The path (pathlib.Path) to the global configuration file used
        by environment's stored in the given path.

    Raises:
        ConfigurationNotFoundError
    """
    if path is None:
        config_path = os.environ.get('MLE_GLOBAL_CONFIG', '')
        config_path = pathlib.Path(config_path) if config_path else None
    else:
        config_path = None

    if config_path is None:
        #   search up through file system from path
        path = pathlib.Path.cwd() if path is None else as_path(path)
        if not path.is_absolute():
            path = pathlib.Path.cwd() / path

        for parent in (path / GLOBAL_CONFIG_FILENAME).parents:
            config_path = parent / GLOBAL_CONFIG_FILENAME
            if config_path.exists():
                break

        #   if not found, try looking in the user's home directory
        if not config_path.exists():
            config_path = pathlib.Path.home() / GLOBAL_CONFIG_FILENAME

    if not config_path.exists():
        raise ConfigurationNotFoundError('global')

    return config_path


def create_global_configuration(path=None):
    """
    Create a global configuration file

    If path is None and OS environment variable MLE_GLOBAL_CONFIG is
    set to a non-empty value, it is used as the path to the global
    configuration file.  If path is None and the MLE_GLOBAL_CONFIG
    is not set, path is set to the current working directory.

    Args:
        path: the directory containing the global configuration file
    """
    if path is None:
        path = os.environ.get('MLE_GLOBAL_CONFIG', '')
        path = pathlib.Path(path) if path else None

    path = pathlib.Path.cwd() if path is None else pathlib.Path(path)
    if path.is_dir():
        path = path / GLOBAL_CONFIG_FILENAME

    create_configuration(path)

    return global_configuration(path)



def global_configuration(path=None):
    """
    Global configuration objet factory

    Creates a configuration.Configuration object for the file
    returned by find_global_configuration().

    Args:
        path: directory to search from or None

    Returns:
        Configuration object

    Raises:
        ConfigurationNotFoundError
    """
    config = configuration.Configuration(find_global_configuration(path))

    try:
        config.defaults = system_configuration()
    except ConfigurationNotFoundError:
        config.defaults = _read_only_copy_default_configuration()

    return config


def find_local_configuration(subdirectory):
    """
    Find the local configuration file

    The file named by the module's LOCAL_CONFIG_FILENAME attribute
    is searched for up the file system tree starting in the given
    subdirectory argument.

    Args:
        subdirectory: directory to search from

    Returns:
        The path (pathlib.Path) to the local configuration file used
        by environment's stored in the given path.

    Raises:
        ConfigurationNotFoundError
    """
    subdirectory = as_path(subdirectory)

    if not subdirectory.is_absolute():
        subdirectory = pathlib.Path.cwd() / subdirectory

    if subdirectory.name == LOCAL_CONFIG_FILENAME:
        path = subdirectory
    elif subdirectory.exists() and not subdirectory.is_dir():
        raise ValueError('subdirectory must be a directory or a '
                         'file named {}: path = {}'.format(LOCAL_CONFIG_FILENAME,
                                                           subdirectory))
    else:
        for parent in (subdirectory / LOCAL_CONFIG_FILENAME).parents:
            path = parent / LOCAL_CONFIG_FILENAME
            if path.exists():
                break

    if not path.exists():
        raise ConfigurationNotFoundError('local')

    return path


def local_configuration(path='.'):
    """
    Local configuration object factory

    Creates a configuration.Configuration object for the file
    returned by find_local_configuration().

    Returns:
        Configuration object

    Raises:
        ConfigurationNotFoundError
    """
    config = configuration.Configuration(find_local_configuration(path))

    try:
        config.defaults = global_configuration(config.filepath.parent)
    except ConfigurationNotFoundError:
        try:
            config.defaults = system_configuration()
        except ConfigurationNotFoundError:
            config.defaults = _read_only_copy_default_configuration()

    return config














class Environment(configuration.Configuration):
    """
    Project environment

    Chained configuration: system, global, local


    #   Environment Creation

    Environments are created on the file system by Environment.create().  They
    are removed from the file system by Environment.remove().

    Each Environment object shares the same local, global, and system
    configuration files.  Autoloading and autosaving are both disabled by
    default.  This means that different Environment objects are generally
    not consistent with each other or the environment's configuration file.

        env1 = Environment('some/environment')
        env2 = Environment('some/environment')
        assert env1['model.prefix'] == env2['model.prefix']

    Changes to 'model.prefix' in env1 are not propagated to env2

        env1['model.prefix'] = 'other/prefix'
        assert env2['model.prefix'] != env1['model.prefix']

    Since env1 wasn't saved after the change, env1 and the configuration
    file are not longer consistent, but env2 still is consistent with the file.

        env3 = Environment('some/environment')
        assert env3['model.prefix'] != env1['model.prefix']
        assert env3['model.prefix'] == env2['model.prefix']

    Saving env1 makes it consistent with the configuration file,
    but env2 and env3 are no longer consistent with the file.

        env1.save()
        env4 = Environment('some/environment')
        assert env2['model.prefix'] != env1['model.prefix']
        assert env3['model.prefix'] != env1['model.prefix']
        assert env4['model.prefix'] == env1['model.prefix']

    Loading env2 makes it consistent with both env1 and the file.

        env2.load()
        assert env2['model.prefix'] == env1['model.prefix']
        assert env3['model.prefix'] != env1['model.prefix']
        assert env4['model.prefix'] == env1['model.prefix']

    The autosave and autoload features of configuration.Configuration
    can be used enforce consistency between environment objects and
    the configuration file.

        env1 = Environment()
        env1.autosave = True
        env1.autoload = True

        env2 = Environment()
        env2.autoload = True

    Now changes to 'model.prefix' in env1 are propagated to env2.

        env1['model.prefix'] = 'other/prefix'

    The change is immediately made to the configuration file.

        env3 = Environment()
        assert env3['model.prefix'] == env1['model.prefix']

    But, some time must be allowed for the file system monitoring
    thread to detect the change to env1 and autoload env2.

        time.sleep(0.2)
        assert env3['model.prefix'] == env1['model.prefix']

    But, since env2.autosave is False, changes are not propagated from
    env2 to env1.

        env2['model.directory_name'] = 'other_name'
        time.sleep(0.2)
        assert env1['model.directory_name'] != env2['model.directory_name']



    ## Search procedure

    Default Environment construction can be controlled globally from
    within or from outside of an application.
    Default construction of environment objects can be controlled by the
    application or externally.

    Typically, an application uses a single, globally selected environment.
    The default construction of Environment objects provides a mechanism
    to control which environment configuration file is used.  When an
    Environment is constructed without any arguments (or equivalently with
    path=None), the environment's configuration file is searched for:
        1.  Up the file system tree starting in the current directory
        2.  Up the file system tree starting in Environment.default_directory
        3.  In the directory given by the OS environment variable: MLE_ACTIVE_ENVIRONMENT
        4.  In the directory given by the global configuration variable: env.active

    This strategy makes it easy to globally choose which environment a
    program uses from within the application as well as externally via
    the configuration file or shell.

    The constructed_from attribute gives the source used to find the
    configuration file.  It is a 2-tuple equal containing a string
    identifying the source and a pathlib.Path:
    If the path is not None,

        constructed_from = ('path', path)

    Otherwise,
    If the environment's configuation file was found from the current directory,

        constructed_from = ('cwd', pathlib.Path.cwd())

    If the environment's configuation file was found from Environment.default_directory,

        constructed_from = ('default_directory', Environment.default_directory)

    If the environment's configuation file was found in $MLE_ACTIVE_ENVIRONMENT

        constructed_from = ('MLE_ACTIVE_ENVIRONMENT', os.environ['MLE_ACTIVE_ENVIRONMENT'])

    If the environment's configuation file was found in env.active

        constructed_from = ('env.active', global_configuration()['env.variable'])



    #   Model Access & Creation

    Model environments are created on the file system with the create_model()
    method.  ModelEnvironment objects are constructed with the model() factory
    function.

    #   ------------------------------------------------------------------------
    #   Callbacks
    #   ------------------------------------------------------------------------

    In addition to the callbacks provided by configuration.Configuration,
    Environment provide a mechanism for notifying when a model environment
    is created, discarded, and made active.

    Callback functions for model environment creation take a single
    ModelEnvironment argument and are added and removed with the
    add_create_model_callback() and remove_create_model_callback() methods.

    Callback functions for model environment removal take a single
    ModelEnvironment argument and are added and removed with the
    add_discard_model_callback() and remove_discard_model_callback() methods.

    Active model change callback functions take two ModelEnvironment arguments,
    the first is the current active model and the second is the previous active
    model.  They are added and removed with the add_active_model_change_callback()
    and remove_active_model_change_callback() methods.

    Callbacks are triggered by calls to the create_model(), discard_model(),
    discard_models() methods and the active_model property.  They are also
    triggered by changes file system.  For example, if the user deletes a
    model environment directory either from within the program or from
    the operating system, all discard model callbacks will be called.
    """
    default_directory = None

    @synchronized
    def __init__(self, path=None):
        self.log = logging.getLogger('mle')
        path = self._find_directory(path).resolve()

        super().__init__(path / LOCAL_CONFIG_FILENAME)

        self.autosave = False
        self.autoload = False

        try:
            #   try to use global as defaults
            self.defaults = global_configuration(path)
        except ConfigurationNotFoundError:
            try:
                #   global not found, try to use system as defaults
                self.defaults = system_configuration()
            except ConfigurationNotFoundError:
                #   global & system not found, use default dict as defaults
                self.defaults = _read_only_copy_default_configuration()

        #   defer building _models_manager until it is needed
        self._models_manager = None
        self.build_identifier_parser()

        #   this should come after self.defaults = ...
        #   so that callbacks aren't triggered by self.defaults = ...
        self.add_callback('model.prefix', self._on_model_path_configuration_changed)
        self.add_callback('model.directory_name', self._on_model_path_configuration_changed)
        self.add_callback('model.active_name', self._on_model_path_configuration_changed)

        self._active_model_change_callbacks = CallbackSet()
        self._active_model = None
        self._update_active_model()

        self._discard_model_callbacks = CallbackSet()
        self._create_model_callbacks = CallbackSet()


    def _find_directory(self, path):
        if path is None:
            try:
                directory = Environment.find('.').resolve()
                self.constructed_from = ('cwd', pathlib.Path.cwd())

            except EnvironmentNotFoundError:
                self.log.debug('failed to find environment from None')

                directory = self._find_directory_from_default_directory()

                if directory is None:
                    directory = self._find_directory_from_os_environ()

                if directory is None:
                    directory = self._find_directory_from_global_configuration()

                if directory is None:
                    raise
        else:
            path = as_path(path)
            directory = pathlib.Path(path)
            if directory.name == LOCAL_CONFIG_FILENAME:
                directory = directory.parent

            if not (directory / LOCAL_CONFIG_FILENAME).exists():
                raise EnvironmentNotFoundError(directory)

            self.constructed_from = ('path', path)

        return directory


    def _find_directory_from_default_directory(self):
        if Environment.default_directory is not None:
            try:
                directory = Environment.find(Environment.default_directory)
            except EnvironmentNotFoundError:
                self.log.error('failed to find environment from '
                               'Environment.default_directory: ',
                               Environment.default_directory)
                raise
            else:
                self.constructed_from = ('default_directory',
                                         Environment.default_directory)
        else:
            directory = None
            self.log.debug('skipped Environment.default_directory: ',
                           Environment.default_directory)

        return directory


    def _find_directory_from_os_environ(self):
        active = os.environ.get('MLE_ACTIVE_ENVIRONMENT', '')
        if active:
            try:
                directory = pathlib.Path(active)
                _ = (directory / LOCAL_CONFIG_FILENAME).resolve()
            except FileNotFoundError:
                self.log.error('failed to find environment at '
                        'MLE_ACTIVE_ENVIRONMENT: ', active)
                raise
            else:
                self.constructed_from = ('MLE_ACTIVE_ENVIRONMENT', active)
        else:
            directory = None
            self.log.debug('skipped MLE_ACTIVE_ENVIRONMENT: ', active)

        return directory


    def _find_directory_from_global_configuration(self):
        try:
            global_config = global_configuration()
        except ConfigurationNotFoundError:
            directory = None
            self.log.debug('skipped global env.active: '
                           'global configuration not found')
        else:
            active = global_config.get('env.active', '')
            if active:
                conifg_path = global_config.filepath.parent

                try:
                    directory = pathlib.Path(active)
                    if directory.is_absolute():
                        directory = directory.relative_to(conifg_path)

                    directory = conifg_path / directory

                    _ = (directory / LOCAL_CONFIG_FILENAME).resolve()
                except (FileNotFoundError, ValueError):
                    self.log.error('failed to find environment at '
                                   'global env.active: ', active)
                    raise
                else:
                    self.constructed_from = ('env.active', active)
            else:
                directory = None
                self.log.debug('skipped global env.active: ', active)

        return directory


    @synchronized
    def __del__(self):
        #   if __init__ raises exeception, _models_manager may not have been set
        with contextlib.suppress(AttributeError):
            if self._models_manager:
                self._models_manager.remove_environment(self)
                self._models_manager = None


    @classmethod
    def create(cls, path='.', config=None, enforce_create_script=True):
        """
        Create an environment in the file system

        This function creates
            1.  the environment's directory
            2.  a local configuration file
            3.  a directory given by self['model.prefix']
            4.  a directory given by self['env.log.directory']
            5.  all directories given by self['env.directories']
            6.  executes the script given by self['env.on_create']

        If an exception occurs and the environment's directory did
        not exist prior to calling this function, the environment's
        directory will be deleted before raising the error.

        Args:
            path(path-like): environment's directory
                If None, use the current working directory
            config(dict): initial environment configuration
            enforce_create_script(bool): if True, raise an
                exception if the create script fails.

        Returns:
            An Environment object

        Raises:
            subprocess.CalledProcessError: if enforce_create_script
                is True and the create script exits with a non-zero code.
            EnvironmentExistsError: if the given path is an environment
                directory, contained within an environment directory,
                or is the ancestor of an environment directory.
            ValueError: if the given path exists and is not a directory
        """
        try:
            existing_path = cls.find(path)
        except EnvironmentNotFoundError:
            pass
        else:
            raise EnvironmentExistsError(existing_path)

        path = as_path(path)
        if not path.is_absolute():
            path = pathlib.Path.cwd() / path

        #   make sure there aren't any environments below path
        if path.is_dir():
            for descendent in path.glob('**/*'):
                if descendent.name == LOCAL_CONFIG_FILENAME:
                    raise EnvironmentExistsError(descendent.parent)

        #   remember if the given path already exists so that
        #   it won't be removed if creation fails
        path_existed = path.exists()
        if path_existed:
            if not path.is_dir():
                raise ValueError('environment path must be a directory')
        else:
            path.mkdir(parents=True, exist_ok=False)

        path = path.resolve()

        config_path = path / LOCAL_CONFIG_FILENAME
        create_configuration(config_path, config)

        try:
            environment = Environment(config_path)

            models_directory = environment.directory / environment['model.prefix']
            models_directory.mkdir(parents=True, exist_ok=True)

            logs_directory = environment.directory / environment['env.log.directory']
            logs_directory.mkdir(parents=True, exist_ok=True)

            for directory in environment['env.directories']:
                directory = environment.directory / directory
                directory.mkdir(parents=True, exist_ok=True)

            on_create_script = environment.get('env.on_create')
            if on_create_script:
                command = [on_create_script, environment.directory]
                subprocess.run(command, check=enforce_create_script)

        except Exception:
            if not path_existed:
                shutil.rmtree(str(path), ignore_errors=True)
            raise

        return environment


    @classmethod
    def remove(cls, path, enforce_delete_script=True):
        """
        Remove an environment from the file system

        This function:
            1.  executes the script given by self['env.on_delete']
            2.  deletes the environment's configuration file

        The environment's directory is not removed.

        Args:
            path(path-like): path or None
                The environment directory is searched for using the
                same procedure as constructing an Environment.
            enforce_delete_script(bool): if True, raise an
                exception if the delete script fails.

        Returns:
            The directory (pathlib.Path) of the environment that was
            removed.

        Raises:
            subprocess.CalledProcessError: if enforce_delete_script
                is True and the delete script exits with a non-zero code.
            EnvironmentNotFoundError: if an environment wasn't found
                for the given path.
        """
        environment = Environment(path)

        on_delete_script = environment.get('env.on_delete')
        if on_delete_script:
            command = [on_delete_script, environment.directory]
            subprocess.run(command, check=enforce_delete_script)

        environment.filepath.unlink()

        return environment.directory


    @staticmethod
    def find(subdirectory):
        """
        Find an environment's directory above the subdirectory

        Returns:
            The directory (pathlib.Path) of the environment
            containing the given subdirectory.

        Raises:
            EnvironmentNotFoundError: if the subdirectory is
                not a descendent of an environment directory.
        """
        try:
            return find_local_configuration(subdirectory).parent
        except ConfigurationNotFoundError:
            raise EnvironmentNotFoundError(subdirectory) from None


    @property
    @synchronized
    def directory(self):
        return self.filepath.parent



    @property
    @synchronized
    def active_model(self):
        """
        The active model

        Raises:
            ModelNotFoundError: if the environment does not have
                an active model.
        """
        if self._active_model is None:
            raise ModelNotFoundError(self, None)
        return self._active_model


    @active_model.setter
    @synchronized
    def active_model(self, model):
        if model is None or isinstance(model, ModelEnvironment):
            changed = model is not self._active_model
        else:
            if self._active_model is None:
                changed = model is not None
            else:
                changed = model != self._active_model.identifier
            if changed:
                model = self.model(model)

        if changed:
            previous = self._active_model
            self._active_model = model

            if self._active_model is None:
                active_model_directory = None
            else:
                active_model_directory = self._active_model.directory

            active_model_symlink = self.active_model_directory

            try:
                modify_symlink = (active_model_directory is None
                                or not active_model_symlink.samefile(active_model_directory))
            except FileNotFoundError:
                modify_symlink = True

            if modify_symlink:
                #   just to be safe, before deleting the symlink make
                #   sure the user didn't name a file or directory as the
                #   active model symlink, if so don't delete it. Attempting
                #   to create it below will fail and they will be sorely
                #   disappointed, but at least their dissertation is still there!
                if active_model_symlink.is_symlink():
                    active_model_symlink.unlink()

                if active_model_directory is not None:
                    active_model_symlink.symlink_to(active_model_directory)

            self._active_model_change_callbacks(self._active_model, previous)


    @synchronized
    def _update_active_model(self):
        if self._active_model is None:
            previous_identifier = None
        else:
            previous_identifier = self._active_model.identifier

        current_identifier = self._find_active_model_identifier()

        if current_identifier != previous_identifier:
            previous_model = self._active_model
            if current_identifier is None:
                self._active_model = None
            else:
                self._active_model = self.model(current_identifier)

            self._active_model_change_callbacks(self._active_model, previous_model)

        if self._active_model is None:
            if self.active_model_directory.is_symlink():
                self.active_model_directory.unlink()


    def _find_active_model_identifier(self):
        active_path = self.active_model_directory / MODEL_CONFIG_FILENAME
        try:
            active_path = active_path.resolve()
            identifier = self.parse_model_identifier(active_path.parent)
        except FileNotFoundError:
            identifier = None

        return identifier


    @property
    @synchronized
    def active_model_directory(self):
        """The path of the symbolic link to the active model's directory"""
        return self.directory / self['model.prefix'] / self['model.active_name']


    @synchronized
    def model(self, identifier=None):
        """
        Construct a ModelEnvironment object

        If the identifier is None, which is the default, this function is
        an alias for self.active_model.

        Args:
            identifier(int): the model environment identifier or None

        Returns:
            If identifier is an integer, a new ModelEnvironment is
            constructed and returned.  If identifier is None, the
            self.active_model is returned.

        Raises:
            ValueError: if identifier is not None and less than zero
            TypeError: if identifier is not None and is not an integer
        """
        model = ModelEnvironment(self, identifier)
        if not model.filepath.exists():
            raise ModelNotFoundError(self, identifier)

        return model


    @property
    @synchronized
    def models(self):
        """An ordered, immutable set of ModelEnvironment objects"""
        if self._models_manager is None:
            self.build_model_set_manager()
        return ModelSet(self, self._models_manager.identifiers)


    @synchronized
    def create_model(self, identifier=None, enforce_create_script=True):
        """
        Create a model environment in the file system

        This function creates
            1.  the model environment's directory,
            2.  a model environment configuration file
            3.  a subdirectory given by self['model.log.directory']
            4.  all subdirectories given by self['model.directories']
            5.  executes the script given by self['model.on_create']

        If an exception occurs and the model environment's directory did
        not exists prior to calling this function, the model environment's
        directory will be deleted before raising the error.

        Args:
            identifier(int): the model environment identifier or None
                if None, the next available identifier is used
            enforce_create_script(bool): if True, raise an
                exception if the create script fails.

        Returns:
            A ModelEnvironment object

        Raises:
            subprocess.CalledProcessError: if enforce_create_script
                is True and the create script failed.
            ModelExistsError: if a model environment with the given
                identifier already exists.
            ValueError: if identifier is not None and less than zero
            TypeError: if identifier is not None and is not an integer
        """
        if identifier is None:
            try:
                model_id = 1 + self.models[-1].identifier
            except IndexError:
                model_id = 0

        model = ModelEnvironment(self, model_id)

        if model.filepath.exists():
            raise ModelExistsError(self, model_id)

        directory_existed = model.directory.exists()

        #   avoid adding model twice, once at the end of this function
        #   and the second time due to handling a file creation event
        with self._models_manager.file_monitoring_disabled():
            try:
                model.directory.mkdir(parents=True, exist_ok=True)
                model.log_directory.mkdir(parents=True, exist_ok=True)

                for subdirectory in self['model.directories']:
                    model.path(subdirectory).mkdir(parents=True, exist_ok=True)

                create_configuration(model.filepath)

                on_create_script = self.get('model.on_create')
                if on_create_script:
                    command = [on_create_script,
                            str(self.directory),
                            str(model.directory),
                            str(model.identifier)]
                    subprocess.run(command, check=enforce_create_script)

            except Exception:
                if not directory_existed:
                    shutil.rmtree(str(model.directory), ignore_errors=True)
                raise

            self._models_manager.add(model.identifier)

        return model


    @synchronized
    def discard_model(self, model, delete_directory=True, enforce_delete_script=True):
        """
        Remove a model environment

        Args:
            model: integer identifier or ModelEnvironment object
            delete_directory(bool): if True, delete the model environment's
                directory
            enforce_delete_script(bool): if True, raise an
                exception if the delete script fails.

        Raises:
            ModelNotFoundError: if the model environment does not exist
            ValueError: if model is None or less than zero
            TypeError: if model is not an integer or a ModelEnvironment
            subprocess.CalledProcessError: if enforce_delete_script
                is True and the delete script exits with a non-zero code.
        """
        with contextlib.suppress(AttributeError):
            if model.environment is not self:
                raise ValueError('model.environment is not self')

        try:
            active_model_removed = self.active_model.identifier == model.identifier
        except AttributeError:
            active_model_removed = self.active_model.identifier == model
        except ModelNotFoundError:
            active_model_removed = False

        with tensorboard.suspender(purge=True):
            self._discard_model(model, delete_directory, enforce_delete_script)

            if active_model_removed:
                self._update_active_model()


    @synchronized
    def discard_models(self, models, delete_directory=True, enforce_delete_script=True):
        """
        Remove multiple model environments

        Args:
            models: collection of integer identifiers or ModelEnvironment objects
            delete_directory(bool): if True, delete the model environment's
                directory
            enforce_delete_script(bool): if True, raise an
                exception if any of the delete scripts fail

        Raises:
            ModelNotFoundError: if any of the model environments do not exist
            ValueError: if any model is None or less than zero
            TypeError: if any model is not an integer or a ModelEnvironment
            subprocess.CalledProcessError: if enforce_delete_script
                is True and any of the delete scripts exits with a non-zero code.
        """
        if models:
            #   self._model_builder will modify self.models while
            #   looping over models because of file system event handling
            if isinstance(models, ModelSet):
                if self._models_manager is not None and models._identifiers is self._models_manager.identifiers:
                    models = self.models.copy()

            try:
                active_model_removed = self.active_model.identifier in models
            except ModelNotFoundError:
                active_model_removed = False

            with tensorboard.suspender(purge=True):
                for model in models:
                    self._discard_model(model, delete_directory, enforce_delete_script)

                if active_model_removed:
                    self._update_active_model()


    def _discard_model(self, model, delete_directory, enforce_delete_script=True):
        if model is None:
            raise ValueError('model can not be None')

        if isinstance(model, numbers.Integral):
            model = self.model(model)
        elif not isinstance(model, ModelEnvironment):
            raise TypeError('model must be a ModelEnvironment: '
                            'type = {}'.format(model))

            if not model.filepath.exists():
                raise ModelNotFoundError(self, model.identifier)

        #   avoid removing the model twice, once at the end of this function
        #   and the second time due to handling a file delete event
        with self._models_manager.file_monitoring_disabled():
            on_delete_script = model.get('model.on_delete')
            if on_delete_script is not None:
                command = [on_delete_script, self.directory,
                        str(model.directory), str(model.identifier)]
                subprocess.run(command, check=enforce_delete_script)

            self._models_manager.discard(model.identifier)

            if delete_directory:
                shutil.rmtree(str(model.directory))
            else:
                model.filepath.unlink()


    @synchronized
    def parse_model_identifier(self, path):
        """
        Parse the identifier from a model environment directory

        Args:
            path(str): path to a model environment's directory

        Returns:
            The integer identifier of the model environment's identifier
            or None if the path is not a model environment directory
        """
        match = self._identifier_parser.match(pathlib.Path(path).name)
        return int(match.groups(1)[0]) if match is not None else None


    @synchronized
    def build_identifier_parser(self):
        self._identifier_parser = re.compile(self['model.directory_name'] + r'(\d+)')


    @synchronized
    def build_model_set_manager(self):
        manager = ModelSetManager(self.directory,
                                  self['model.prefix'],
                                  self['model.directory_name'])

        if manager is not self._models_manager:
            if self._models_manager is not None:
                self._models_manager.remove_environment(self)

            self._models_manager = manager
            self._models_manager.add_environment(self)


    def _on_model_path_configuration_changed(self, current, previous):
        with synchronized(self):
            self.build_identifier_parser()

            if self._models_manager is not None:
                self.build_model_set_manager()

            self._update_active_model()





    def __hash__(self):
        return hash(super(object, self))

    def __eq__(self, other):
        return super(object, self).__eq__(other)

    def __ne__(self, other):
        return super(object, self).__ne__(other)


    @synchronized
    def add_active_model_change_callback(self, callback):
        self._active_model_change_callbacks.add(callback)


    @synchronized
    def remove_active_model_change_callback(self, callback):
        self._active_model_change_callbacks.remove(callback)


    @synchronized
    def add_discard_model_callback(self, callback):
        self._discard_model_callbacks.add(callback)


    @synchronized
    def remove_discard_model_callback(self, callback):
        self._discard_model_callbacks.remove(callback)


    @synchronized
    def add_create_model_callback(self, callback):
        self._create_model_callbacks.add(callback)


    @synchronized
    def remove_create_model_callback(self, callback):
        self._create_model_callbacks.remove(callback)










class ModelEnvironment(configuration.Configuration):
    """
    A workspace for creating and evaluating a single model instance.

    A model environment is a specially named directory within the
    project environment's directory that contains a model environment
    configuration file whose name is equal to module level
    MODEL_CONFIG_FILENAME attribute.

    The model environment directory is constructed from the project
    environment's directory, 'model.prefix' and 'model.director_name'
    variables.  Specifically, the model environment directory is:
    environment.directory / environment['model.prefix'] / environment['model.directory_name'].

    ModelEnvironment objects monitor the environment's 'model.prefix'
    and 'model.directory_name' for changes and adjusts itself accordingly.
    i.e.
    environment = Environment()

    #   choose the 'some' group of models
    environment['model.prefix'] = 'some/models'

    #   create model directory some/models/foo1
    environment['model.directory_name'] = 'foo'
    environment.create_model(1)

    #   create model directory some/models/bar1
    environment['model.directory_name'] = 'bar'
    environment.create_model(1)

    #   use Environment's model factory function to create a ModelEnvironment
    model = environment.model(1)
    assert model.is_loaded()
    assert model.directory.exists()
    assert model.directory == environment.directory / 'some/models/bar1'

    #   change to the 'other' group of models
    environment['model.prefix'] = 'other/models'
    assert not model.is_loaded()
    assert not model.directory.exists()
    assert model.directory == environment.directory / 'other/models/bar1'

    #   change to model directories named foo*
    environment['model.director_name'] = 'foo'
    assert not model.is_loaded()
    assert not model.directory.exists()
    assert model.directory == environment.directory / 'other/models/foo1'

    #   switch back to the 'some' group of models
    #   since 'some/models/foo1' exists it gets loaded
    environment['model.prefix'] = 'some/models'
    assert model.is_loaded()
    assert model.directory.exists()
    assert model.directory == environment.directory / 'some/models/foo1'


    By default, Environment objects do not detect changes to their
    underlying configuration file.  Therefore, if the environment's
    'model.prefix' or 'model.directory_name' are modified externally
    by editing the configuration file, these changes will not be
    propagated to the ModelEnvironment object.  If this is required,
    it can be accomplished by setting the reloading environment's
    configuration file.
    i.e.
    environment1 = Environment()
    environment1['model.prefix'] = 'some/models'
    model = environment.create_model(1)

    assert model.is_loaded()
    assert model.directory == environment1.directory / 'some/models/model1'

    #   create a different Environment instance that refers to the same
    #   file system environment used to construct the model environment
    environment2 = Environment()
    environment2['model.prefix'] = 'other/models'

    #   since environment1 is not environment2, model has not changed
    assert environment1['model.prefix'] == 'some/models'
    assert model.is_loaded()
    assert model.directory == environment1.directory / 'some/models/model1'

    #   saving environment2 and then reloading environment1 changes model
    environment2.save()
    environment1.load()
    assert environment1['model.prefix'] == 'other/models'
    assert not model.is_loaded()
    assert model.directory == environment.directory / 'other/models/model1'

    If the application needs to respond to changes made to the configuration
    file from outside of the program, set environment.autoload to True.



    ModelEnvironment objects are typically created from an Environment
    object using the factory functions model() and create_model()
    and the properties models and active_model.  These functions
    and properties raise a ModelNotFoundError if the model environment
    does not exist in the file system.

    Nevertheless, in some cases it may be useful to construct a
    ModelEnvironment directly.  Doing so will always succeed even
    if the model environment does not exist in the file system.

    If the model environment does not exist in the file system at
    construction time, the ModelEnvironment object can automatically
    detect its creation by setting model.autoload to true.
    i.e.
    environment = Environment()
    model = ModelEnvironment(environment, 2)
    assert not model.is_loaded()

    model.autoload = True
    environment.create_model(2)

    #   give the monitoring thread a chance to detect and load
    #   the environment's configuration file
    time.sleep(0.5)
    assert model.is_loaded()


    If the identifier passed to the constructor is None, the ModelEnvironment
    is assumed to be the active model environment.  If the environment
    has an active model environment, the identifier property will
    return its integer identifier, otherwise it will return None.
    This means that a ModelEnvironment constructed with identifier
    set to None will change when the active model is changed.
    i.e.
    #   create an environment with no active model and a model
    #   environment whose identifier is 2
    environment = Environment()
    environment.create_model(2)
    environment.active_model = None

    #   create a ModelEnvironment with identifier = None
    model = ModelEnvironment(environment, None)
    assert model.identifier is None
    assert not model.is_loaded()
    assert model.directory.name == environment['model.active_name']

    #   change the active model to model environment 2
    environment.active_model = 2
    assert model.identifier == 2
    assert model.is_loaded()
    assert model.directory.name == environment['model.directory_name'] + '2'

    Attributes:
        identifier(int): the model's integer identifier or None
        environment(Environment): the project environment
        directory(pathlib.Path): the model environment directory
        log_directory(pathlib.Path): the subdirectory used for logging
        summary_path(pathlib.Path): the model summary file
    """
    def __init__(self, environment, identifier):
        if identifier is not None and not isinstance(identifier, numbers.Integral):
            raise TypeError('model identifier must be an integer: '
                            'type ='.format(type(identifier)))

        if identifier is not None and identifier < 0:
            raise ValueError('model identifier must be >= 0: '
                             'identifier = {}'.format(identifier))

        super().__init__()
        self._environment = environment
        self._identifier = identifier

        with contextlib.suppress(FileNotFoundError):
            self._update_filepath()

        self.defaults = self._environment

        self.environment.add_callback('model.prefix', self._on_model_directory_changed)
        self.environment.add_callback('model.directory_name', self._on_model_directory_changed)


    def _on_model_directory_changed(self, current, previous):
        try:
            self._update_filepath()
        except FileNotFoundError:
            self.clear()


    def _update_filepath(self):
        if self.identifier is None:
            directory_name = self.environment['model.active_name']
        else:
            directory_name = self.environment['model.directory_name'] + str(self.identifier)
        prefix = self.environment['model.prefix']
        directory = self.environment.directory / prefix / directory_name

        self.filepath = directory / MODEL_CONFIG_FILENAME


    @property
    def identifier(self):
        if self._identifier is None:
            try:
                identifier = self.environment.active_model.identifier
            except ModelNotFoundError:
                identifier = None
        else:
            identifier = self._identifier

        return identifier


    @property
    def environment(self):
        return self._environment


    @property
    def directory(self):
        return self.filepath.parent


    @property
    def log_directory(self):
        return self.directory / self['model.log.directory']


    def path(self, path):
        """
        Construct a path relative to the model environment directory

        Args:
            path(path-like): relative path

        Returns:
            The absolute path (pathlib.Path) by joining the given path
            and self.directory

        Raises:
            ValueError
        """
        if path is None:
            raise ValueError('path is None')
        if not path:
            raise ValueError('path is empty')

        path = as_path(path)
        if path.is_absolute():
            path = path.relative_to(self.directory)

        return self.directory / path


    def log_path(self, path=None):
        """
        Construct a path relative to the model environment's log directory

        If the given path is None, the configuration variable
        'model.log.default' is used.

        Args:
            path(path-like): relative path or None

        Returns:
            The absolute path (pathlib.Path) by joining the given path
            and self.log_directory

        Raises:
            ValueError if path is None or path is empty and
            'model.log.default' not in self or self['model.log.default']
            is empty
        """
        if path is None:
            path = self['model.log.default']
        if not path:
            raise ValueError('path is empty')

        path = as_path(path)
        if path.is_absolute():
            path = path.relative_to(self.log_directory)

        return self.log_directory / path


    @property
    def summary_path(self):
        return self.directory / self['model.summary']


    def clear_logs(self):
        """Clear the contents of the model environment's log directory"""
        for item in self.log_directory.iterdir():
            if item.is_dir():
                shutil.rmtree(str(item))
            else:
                item.unlink()


    def __repr__(self):
        return '<{} ({}) identifier = {}>'.format(self.__class__,
                                                  hex(id(self)),
                                                  self.identifier)

    def __str__(self):
        return str(self.directory.relative_to(self._environment.directory))


    def __hash__(self):
        return hash((id(self._environment), self.identifier))


    def __eq__(self, other):
        """
        ModelEnvironment objects are equal if they have identical
        environments and equal identifiers.

        Args:
            other(ModelEnvironment): a model environment

        Returns:
            True if self.environment is other.environment and
            self.identifier == other.identifier
        """
        return (other is not None
                and self._environment is other._environment
                and self.identifier == other.identifier)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        """
        Compare order

        Args:
            other(ModelEnvironment): a model environment

        Returns:
            True if self.identifier < other.identifier

        Raises:
            ValueError if self.environment is not other.environment
        """
        self._check_same_environmentment(other)
        return self.identifier < other.identifier

    def __le__(self, other):
        self._check_same_environmentment(other)
        return self.identifier <= other.identifier

    def __gt__(self, other):
        self._check_same_environmentment(other)
        return self.identifier > other.identifier

    def __ge__(self, other):
        self._check_same_environmentment(other)
        return self.identifier >= other.identifier

    def _check_same_environmentment(self, other):
        if self._environment is not other._environment:
            raise ValueError('can not compare models from different environments')





class ModelSetManager:
    """
    Manages a single ModelSet shared amongst multiple Environment objects

    This class is responsible for
        1. building a set of model identifiers from existing
           file system model environments
        2. adding and removing identifiers to and from the set
        3. monitoring changes to the parent directory of model
           environments and ensuring that the set of identifiers
           remains consistent with the state of the file system

    ModelSetManager objects are used internally by Environment
    objects.  They are not part of the public API.  Nevertheless,
    designers of Environment subclasses must be aware of the
    relationship between Environment objects and ModelSetManager
    objects.

    A separate ModelSetManager object is created for each unique
    2-tuple constructed from environment variables 'model.prefix'
    and 'model.directory_name'.  It is shared by all Environment
    objects having those variables.

    env_1 = Environment()
    env_2 = Environment()
    env_3 = Environment()
    env_4 = Environment()
    env_5 = Environment()

    env_1['model.prefix'] = 'a'
    env_2['model.prefix'] = 'a'
    env_3['model.prefix'] = 'a'
    env_4['model.prefix'] = 'b'
    env_5['model.prefix'] = 'b'

    assert env_1._models_manager is env_2._models_manager
    assert env_2._models_manager is env_3._models_manager
    assert env_3._models_manager is not env_4._models_manager
    assert env_4._models_manager is env_5._models_manager

             manager_a         manager_b
             /  |  \              /\
            /   |   \            /  \
           /    |    \          /    \
        env_1 env_2 env_3    env_4  env_5

    Changing the 'model.directory' of env_5
    env_5['model.directory'] = 'x'

    assert env_1._models_manager is env_2._models_manager
    assert env_2._models_manager is env_3._models_manager
    assert env_3._models_manager is not env_4._models_manager
    assert env_4._models_manager is not env_5._models_manager

             manager_a     manager_b    manager_c
             /  |  \          |            |
            /   |   \         |            |
           /    |    \        |            |
        env_1 env_2 env_3   env_4        env_5

    Changing the 'model.prefix' of env_3,
    env_3['model.directory'] = 'b'

    assert env_1._models_manager is env_2._models_manager
    assert env_2._models_manager is not env_3._models_manager
    assert env_3._models_manager is env_4._models_manager
    assert env_4._models_manager is not env_5._models_manager

          manager_a       manager_b     manager_c
             /\              /\            |
            /  \            /  \           |
           /    \          /    \          |
        env_1  env_2    env_3  env_4     env_5
    """
    _managers_cache = dict()
    _cache_lock = threading.RLock()

    def __new__(cls, directory, prefix, directory_name):
        with ModelSetManager._cache_lock:
            manager_key = (directory, prefix, directory_name)
            try:
                manager = ModelSetManager._managers_cache[manager_key]
            except KeyError:
                manager = object.__new__(cls)
                manager.directory = directory
                manager.prefix = prefix
                manager.directory_name = directory_name
                ModelSetManager._managers_cache[manager_key] = manager

            return manager


    def __init__(self, directory, prefix, directory_name):
        try:
            #   don't initialize an object retrieved from the cache
            if not hasattr(self, 'identifiers'):
                self.identifiers = orderedset.OrderedSet()
                self._environments = weakref.WeakSet()

                self.identifier_parser = re.compile(self.directory_name + r'(\d+)')

                self.models_directory.mkdir(parents=True, exist_ok=True)

                self._event_handler = ModelDirectoryEventHandler(self)

                self._file_observer = watchdog.observers.Observer()
                self._file_watch = self._file_observer.schedule(self._event_handler,
                                                                str(self.models_directory))

                self.build_identifiers()

        except Exception:
            self._remove_self_from_builders_cache()
            raise


    def __del__(self):
        self.stop()


    def _remove_self_from_builders_cache(self):
        with ModelSetManager._cache_lock, contextlib.suppress(KeyError):
            manager_key = (self.directory, self.prefix, self.directory_name)
            del ModelSetManager._managers_cache[manager_key]


    def add_environment(self, environment):
        """Add an environment that uses this manager"""
        self._environments.add(environment)
        self.start()


    def remove_environment(self, environment):
        """Remove an environment that no longer uses this manager"""
        self._environments.discard(environment)
        if not self._environments:
            self.stop()


    def start(self):
        """Start monitoring the file system for changes"""
        if not self._file_observer.is_alive():
            self._file_observer.start()


    def stop(self):
        """Stop monitoring the file system for changes"""
        if not sys.is_finalizing() and self._file_observer.is_alive():
            self._file_observer.stop()
            self._file_observer.join()
        self._remove_self_from_builders_cache()


    @property
    def models_directory(self):
        """The parent directory (pathlib.Path) of all model environments"""
        return self.directory / self.prefix


    @synchronized
    def build_identifiers(self):
        """
        Construct set of identifiers from existing model environments

        This function does not call any environment callbacks.
        """
        self.identifiers.clear()

        for path in self.models_directory.glob(self.directory_name + '*/' + MODEL_CONFIG_FILENAME):
            model_identifier = self.parse_model_identifier(path.parent)
            if model_identifier is not None:
                self.identifiers.add(model_identifier)


    def parse_model_identifier(self, path):
        """
        Parse the integer identifier from a model environment directory

        Args:
            path(str): directory

        Returns:
            The integer identifier of the model environment or None
            if the directory is not a model environment directory.
        """
        match = self.identifier_parser.match(pathlib.Path(path).name)
        return int(match.groups(1)[0]) if match is not None else None


    def update_active_model(self, current, previous):
        #   if directory was created, just update
        if current is not None and previous is None:
            for environment in self._environments:
                with synchronized(environment), contextlib.suppress(ModelNotFoundError):
                    if environment.active_model.identifier == current:
                        environment._update_active_model()

        #   if directory was deleted, just update
        elif current is None and previous is None:
            for environment in self._environments:
                with synchronized(environment), contextlib.suppress(ModelNotFoundError):
                    if environment.active_model.identifier == previous:
                        environment._update_active_model()

        #   if the active directory was moved, set it
        elif current is not None and previous is not None:
            for environment in self._environments:
                with synchronized(environment), contextlib.suppress(ModelNotFoundError):
                    if environment.active_model.identifier == previous:
                        environment.active_model = current


    @synchronized
    def discard(self, identifier):
        """
        Remove a model identifier from the set of identifiers

        Runs discard model callbacks for all environments.

        Raises:
            KeyError: if the identifier is not in the set
        """
        self.identifiers.discard(identifier)

        for environment in self._environments:
            with synchronized(environment):
                model = ModelEnvironment(environment, identifier)
                environment._discard_model_callbacks(model)


    @synchronized
    def add(self, identifier):
        """
        Add a model identifier to the set of identifiers

        If the identifier is not already in the set,
        add model callbacks are run for all environments.
        """
        if self.identifiers.add(identifier):
            for environment in self._environments:
                with synchronized(environment):
                    model = ModelEnvironment(environment, identifier)
                    environment._create_model_callbacks(model)


    @contextlib.contextmanager
    def file_monitoring_disabled(self):
        """Context manager that temporarily disables file system monitoring"""
        with synchronized(self):
            self._file_observer.unschedule(self._file_watch)
            try:
                yield
            finally:
                self._file_watch = self._file_observer.schedule(self._event_handler,
                                                                str(self.models_directory))






class ModelDirectoryEventHandler(watchdog.events.FileSystemEventHandler):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager


    def on_created(self, event):
        if event.is_directory:
            model_identifier = self.manager.parse_model_identifier(event.src_path)
            if model_identifier is not None:
                self.manager.add(model_identifier)
                self.manager.update_active_model(current=model_identifier,
                                                 previous=None)


    def on_deleted(self, event):
        if event.is_directory:
            model_identifier = self.manager.parse_model_identifier(event.src_path)
            if model_identifier is not None:
                self.manager.discard(model_identifier)
                self.manager.update_active_model(current=None,
                                                 previous=model_identifier)


    def on_moved(self, event):
        if event.is_directory:
            source_model_identifier = self.manager.parse_model_identifier(event.src_path)
            dest_model_identifier = self.manager.parse_model_identifier(event.dest_path)

            if dest_model_identifier is not None:
                self.manager.add(dest_model_identifier)
            if source_model_identifier is not None:
                self.manager.discard(source_model_identifier)
            self.manager.update_active_model(current=dest_model_identifier,
                                             previous=source_model_identifier)




class ModelSet:
    """
    Wraps an OrderedSet of integer identifiers with an interface that converts
    identifiers to/from ModelEnvironment objects
    """
    def __init__(self, environment, identifiers):
        self._environment = environment
        self._identifiers = identifiers


    def as_identifier(self, item):
        with contextlib.suppress(AttributeError):
            item = item.identifier
        return item


    def copy(self):
        copied = self.__class__(self._environment, self._identifiers.copy())
        return copied


    def index(self, model):
        return self._identifiers.index(self.as_identifier(model))

    def __len__(self):
        return len(self._identifiers)


    def __getitem__(self, index):
        return ModelEnvironment(self._environment, self._identifiers[index])


    def __contains__(self, model):
        if isinstance(model, numbers.Integral):
            return model in self._identifiers

        return (model.environment is self._environment
                and self.as_identifier(model) in self._identifiers)


    def __iter__(self):
        return (ModelEnvironment(self._environment, identifier)
                for identifier in self._identifiers)


    def __reversed__(self):
        return reversed(list(self))


    def __eq__(self, sequence):
        if isinstance(sequence, ModelSet):
            equal = (sequence._environment is self._environment
                     and sequence._identifiers == self._identifiers)
        elif isinstance(sequence, OrderedSet):
            equal = sequence == self._identifiers
        else:
            equal = len(self) == len(sequence)
            if equal:
                for a, b in zip(self._identifiers, sequence):
                    if isinstance(b, ModelEnvironment):
                        if self._environment is not b.environment or a != b.identifier:
                            equal = False
                            break
                    elif a != b:
                        equal = False
                        break

        return equal


    def __ne__(self, sequence):
        return not self.__eq__(sequence)


    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self._identifiers)


    def __str__(self):
        return str(self._identifiers)




























































