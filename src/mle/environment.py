"""
Environment management

The MLE system consists of a collection of environments where multiple
models can be successively trained and evaluated.  The models may be architectural
variations, trained differently, initialized differently, etc. Models
are enumerated using an integer identifier.

Each model id has a corresponding directory named model<id>.  Each model
directory contains a logs directory.  Additional directories can be created
in each model directory.  The 'model_layout' variable in the environment's
configuration is a list of relative paths that will be added to each new
model directory.

Each environment is a configuration consisting of key, value pairs.
It is constructed by combining the contents of the local .mle file with
the contents of a global configuration file (.global.mle).  The .global.mle
file is searched for in the following order:
    1. ancestors of the environment directory
    2. users home directory (i.e. ~/)
    3. /etc/mle

An example projects layout where each project is an environment:

projects/
    .global.mle
    my_project/
        .mle (w/ prefix = models)
        source.py
        logs/
        models/
            model/ (sym link to active model)
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
        .mle (w/ prefix = '')
        source.py
        logs/
        model/ (sym link to active model)
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




Each environment object has a current model property and an active model
property.  The active model property is shared amongst all environment objects;
changing the active model property on any single instance is seen by instances.
On the other hand, each environment object carries their own current model
property.  Because the active model is global (per environment) it can be
accessed and modified from outside the program (e.g. mle command line tools).
The current model property is initialized to the active model.


Configuration:
model.prefix = relative path            # prepended to model<id>
model.directories = list of rel. paths  # directories created in model<id>
model.active_name = filename            # name of sym link to active model
model.directory_name = filename         # name of model directory (id is appended)
model.default_metadata = dict           # default model metadata file contents
model.on_create                         # script run after model created
model.on_delete                         # script run before model deleted, if exit != 0 delete cancelled
model.summary = filename                # file name of mode summary file opened with mle summary
model.log.default
model.log.directory
model.metadata = filename
log.default = filename                  # defualt log file opened with mle log
log.extension = log                     # appended to log file names e.g. mle log train -> opened train.log
env.directories = list of rel. paths    # directories created in a new environment
env.on_create                           # script run after environment created
env.log.filename = filename             # environment log file
env.log.directory = relative path       # environment log directory
user = dict                             # user configuration namespace


Commands:
config key = value                      # set the config variable, --global
init                                    # create an environment, --global
create                                  # create a model
remove                                  # remove a model(s), --all, --others
activate                                # make a model the active model
meta                                    # prints model metadata
summary                                 # print model summary
log                                     # print a log file, --environment
"""
import pathlib
import os.path
import re
import shutil
import json
import bisect
import weakref
import inspect
import threading
import contextlib
import collections
import copy
import types
import time

import watchdog.events
import watchdog.observers
import wrapt

from . import tensorboard
from . import configuration







_DEFAULT_GLOBAL_CONFIGURATION = {
    'model.prefix': '',
    'model.directories': [],
    'model.active_name': 'model',
    'model.directory_name': 'model',
    'model.default_metadata': {},
    'model.on_create': None,
    'model.on_delete': None,
    'model.summary': 'summary',
    'model.log.default': 'train.log',
    'model.log.directory': 'logs',
    'model.metadata': 'metadata',
    'log.default': 'mle.log',
    'log.extension': 'log',
    'env.directories': [],
    'env.on_create': None,
    'env.log.filename': 'mle.log',
    'env.log.directory': 'logs',
    'user': {},
}


def global_configuration(path=None):
    """
    Find the global configuration for the given path

    Searchs for
        1. if os environment variable MLE_GLOBAL_CONFIG is set, use it
        2. .global.mle in path
        3. .global.mle in ancestors of path
        4. ~/.global.mle
        5. /etc/mle/config

    Args:
        path:

    Returns:
        Configuration object

    Raises:
        ConfigurationNotFoundError
    """
    def create_configuration(config_path):
        if config_path is None:
            config = None
        else:
            try:
                config = configuration.Configuration(config_path.resolve())
            except FileNotFoundError:
                config = None
        return config

    if path is None:
        path = pathlib.Path.cwd()
    else:
        path = pathlib.Path(_expand(str(path)))

    #   try using the environment variable
    config = create_configuration(os.environ.get('MLE_GLOBAL_CONFIG'))

    #   check in the given path
    if config is None:
        config = create_configuration(path / '.global.mle')

    #   check in ancestors of the given path
    while config is None and path != path.parent:
        config = create_configuration(path / '.global.mle')

    #   check in the home directory
    if config is None:
        config = create_configuration(pathlib.home() / '.global.mle')

    #   check in the system's /etc directory
    if config is None:
        config = create_configuration(pathlib.Path('/etc/mle/config'))

    if config is None:
        raise ConfigurationNotFoundError()

    config.defaults = copy.deepcopy(_DEFAULT_GLOBAL_CONFIGURATION)

    return config






class ModelMetadata:
    def __init__(self, path):
        self._data = dict()
        self._path = path
        self.load()

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        previous_value = self._data.get(key, None)
        if previous_value != value:
            self._data[key] = value
            self.save()

    def __delitem__(self, key):
        del self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get(self, key, default=None):
        return self._data.get(key, default)

    def setdefault(self, key, default):
        if key not in self._data:
            self[key] = default
        return self._data[key]


    def save(self):
        with self._path.open('w') as file:
            json.dump(self._data, file, indent=4)


    def load(self):
        with self._path.open('r') as file:
            self._data = json.load(file)






class ModelEnvironment:
    def __init__(self, environ, identifer):
        self._environ = environ
        self._identifier = identifier
        self._metadata = None

        if self.identifer is None:
            directory_name = self._environ['model.active_name']
        else:
            directory_name = self._environ['model.directory_name'] + str(self.identifer)

        prefix = self._environ['model.prefix']
        self._directory = self._environ.path / prefix / directory_name


    @property
    def identifier(self):
        return self._identifier

    @property
    def directory(self):
        self._directory

    @property
    def log_directory(self):
        return self.directory / self._environ['model.log.directory']

    def file_path(self, path):
        return self.directory / path

    def log_path(self, path):
        if path is None:
            path = self._environ['model.log.default']
        return self.log_directory / path

    @property
    def summary_path(self):
        return self.directory / self._environ['model.summary']

    @property
    def metadata_path(self):
        return self.directory / self._environ['model.metadata']

    @property
    def metadata(self):
        if self._metadata is None:
            self._metadata = ModelMetadata(self.metadata_path)
        return self._metadata


    def clear_logs(self):
        for item in self.log_directory().iterdir():
            if item.is_dir():
                shutil.rmtree(str(item))
            else:
                item.unlink()


    def __repr__(self):
        return '<{} ({}) identifier = {}>'.format(self.__class__,
                                                  hex(id(self)),
                                                  self.identifer)

    def __str__(self):
        return str(self.directory.relative_to(self._environ.path))




class Environment(configuration.Configuration):
    """
    Project environment

    #   ------------------------------------------------------------------------
    #   Environment Creation
    #   ------------------------------------------------------------------------

    #   creates a new environment in the current working directory
    #   this creates a '.mle' file and uses it to construct an Environment object
    environ = Environment.create()

    #   or, instantiate an existing environment in the current working directory
    #   this uses an existing '.mle' file to construct an Environment object
    environ = Environment()

    #   ------------------------------------------------------------------------
    #   Model Access & Creation
    #   ------------------------------------------------------------------------

    #   use the model that has been designated as the active model
    #   (the active model can be selected by an external program or
    #   another environment object within the program)
    print(environ.model().directory)

    #   or, create a new model directory/context
    #   and access the model's context by id
    model_id = environ.create_model()
    print(environ.model(model_id).directory)

    #   or, set the environment's current_model_id
    #   to avoid carrying around the model_id everywhere
    #   (this only impacts the single Environment instance)
    def do_something(environ):
        print(environ.model().directory)

    environ.current_model_id = model_id
    do_something(environ)

    #   to go back to using the active model
    environ.current_model_id = None
    print(environ.model().directory)

    #   to make a model the active model
    #   (this affects all environment objects as well as
    #   external/os level tools)
    environ.activate(model_id)


    Notes:
        ModelEnvironment objects should not be long lived and should not
        be cached.  They may be invalidated if the environment's .mle file
        is modified.  Instead, model information should be accessed using
        the pattern (where model_id can be None):
            environ.model(model_id).<attribute>
        Iterating over all models should be done with:
            for model in environ.models:
                model.<attribute>
    """
    def __init__(self, path):
        if path is None:
            path = pathlib.Path.cwd()
        else:
            path = pathlib.Path(_expand(str(path)))

        #   while path is a descendent of the environment directory
        while not (path / '.mle').exists():
            path = path.parent
            if path == path.parent:
                raise EnvironmentNotFoundError()

        self._path = path.resolve()
        self._global_config = global_configuration(self._path)
        self._models = None
        self._current_model_id = None

        self.defaults = self._global_config


    @classmethod
    def create(cls, path):
        """
        Create a new environment

        Create an empty .mle file and use it to create an Environment object

        Args:
            path(path-like): path to the environment directory

        Returns:
            An Environment object
        """
        if path is None:
            path = pathlib.cwd()
        else:
            path = pathlib.Path(_exapnd(str(path))).resolve()

        with (path / '.mle').open('w') as file:
            file.write('{}\n')

        return Environment(path)


    @property
    def path(self):
        return self._path


    def activate(self, model_id):
        """Make model the active model"""
        active_path = self.path / self['model.prefix'] / self['model.active_name']
        self.model(model_id).directory.symlink_to(active_path)


    @property
    def current_model(self):
        if self._current_model_id is None:
            return None
        return self.model(self._current_model_id)


    @current_model.setter
    def current_model(self, current_model):
        try:
            self._current_model_id = current_model.identifer
        except AttributeError:
            self._current_model_id = current_model


    def model(self, identifer=None):
        """
        Model dependent operations/values

        If identifer is None, the current_model_id is used.
        However, if current_model_id is None, the active model
        is used.
        """
        if identifer is None:
            identifer = self._current_model_id

        return ModelEnvironment(self, identifer)


    @property
    def models(self):
        if self._models is None:
            #   build list of model indices from directory names
            self._models = ModelIndexSet(self)
            path = self.path / self['model.prefix']
            for model_path in path.glob(self['model.directory_name'] + '*'):
                if model_path.is_dir():
                    model = ModelEventHandler.parse_model_identifier(model_path)
                    self._models._add(model)
        return self._models




    def create_model(self):
        try:
            model_id = 1 + self.models[-1]
        except IndexError:
            model_id = 0

        model = self.model(model_id)

        model.directory.mkdir(parents=True, exist_ok=False)
        model.log_directory.mkdir(parents=True, exist_ok=False)

        for path in self['model.directories']:
            (model.directory / path).mkdir(parents=True, exist_ok=True)

        #   run on_create - TODO: flesh this out
        with contextlib.suppress(KeyError):
            subprocess.run([self['model.on_create'], self.path, model.directory, model.identifer])

        self.models._add(model.identifer)

        return model


    def discard_model(self, model):
        with tensorboard.suspender(purge=True):
            try:
                self._discard_model(model.identifer)
            except AttributeError:
                self._discard_model(model)


    def discard_models(self, models):
        if models:
            with tensorboard.suspender(purge=True):
                for model in models:
                    try:
                        self._discard_model(model.identifer)
                    except AttributeError:
                        self._discard_model(model)


    def discard_all_models(self):
        self.discard_models(self.models.copy())


    def discard_other_models(self, model):
        """Remove all models except the current model"""
        others = self.models.copy()
        try:
            others._remove(model.identifer)
        except AttributeError:
            others._remove(model)
        self.discard_models(others)


    def reorder_models(self):
        """Reassigns model id numbers so they make a continguous range"""
        with tensorboard.suspender(purge=True):
            #   copy self.models because it will be
            #   modified as directories are renamed
            for i, model in enumerate(self.models.copy()):
                if i != model.identifer:
                    model.directory.rename(self.models(i).directory)


    def _discard_model(self, model):
        #   run on_delete - TODO: flesh this out
        with contextlib.suppress(KeyError):
            subprocess.run([self['model.on_delete'], self.path, model.directory, model.identifer])

        shutil.rmtree(str(model.directory))



    #   ------------------------------------------------------------------------
    #                   Chaining Global Configuration
    #   ------------------------------------------------------------------------

    def add_change_callback(self, key, callback):
        if key in self:
            super().add_change_callback(key, callback)
        else:
            self._global_config.add_change_callback(key, callback)


    def add_delete_callback(self, key, callback):
        if key in self:
            super().add_delete_callback(key, callback)
        else:
            self._global_config.add_delete_callback(key, callback)


    def _delete_callback(self, key, value):
        if self.is_delete_callbacks_enabled():
            try:
                #   falling back to global config -> change instead of delete
                new_value = self._global_config[key]
                for callback in self._change_callbacks.get(key, set()):
                    callback(new_value, value)
                    self._global_config.add_delete_callback(key, callback)
            except KeyError:
                super()._delete_callback(key, value)

    #def __setitem__(self, key, value):
        #if key not in self and key in self._global_config:
            #previous_value = self._global_config[key]
            #if previous_value != value:
                #self._change_callback(key, value, previous_value)


    def __getitem__(self, key):
        try:
            return self[key]
        except KeyError:
            return self._global_config[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return self._global_config.get(key, default)

    def items(self):
        return {**self._global_config, **self._variables}.items()

    def keys(self):
        return {**self._global_config, **self._variables}.keys()

    def values(self):
        return {**self._global_config, **self._variables}.values()






class ModelEventHandler(watchdog.events.FileSystemEventHandler):
    MODEL_DIRECTORY_PATTERN = re.compile(r'model(\d+)')

    def __init__(self, environment):
        self.environment = environment


    @staticmethod
    def parse_model_identifier(path):
        path = pathlib.Path(path)
        match = ModelEventHandler.MODEL_DIRECTORY_PATTERN.match(path.name)

        return int(match.groups(1)[0]) if match is not None else None


    def on_created(self, event):
        if event.is_directory:
            model_identifier = self.parse_model_identifier(event.src_path)
            self.add(model_identifier)


    def on_deleted(self, event):
        if event.is_directory:
            model_identifier = self.parse_model_identifier(event.src_path)
            self.remove(model_identifier, None)


    def on_moved(self, event):
        if event.is_directory:
            source_model_identifier = self.parse_model_identifier(event.src_path)
            dest_model_identifier = self.parse_model_identifier(event.dest_path)

            self.add(dest_model_identifier)
            self.remove(source_model_identifier, dest_model_identifier)


    def remove(self, model_identifier, new_current_model):
        if self.environment.current_model == model_identifier:
            self.environment.current_model = new_current_model

        self.environment._models._remove(model_identifier)


    def add(self, model_identifier):
        self.environment._models._add(model_identifier)









class ModelIndexSet:
    """Ordered set of model identifiers"""
    def __init__(self, environment, items=()):
        self._environment = environment
        self._items = list(sorted(items))

    def clear(self):
        self._items.clear()

    def copy(self):
        return self.__class__(self.environment, self)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, i):
        return ModelEnvironment(self._environment, self._items[i])

    def __iter__(self):
        return (ModelEnvironment(self._environment, item)
                for item in self._items)
        #return iter(self._items)

    def __reversed__(self):
        return reversed([ModelEnvironment(self._environment, item)
                         for item in self._items])
        #return reversed(self._items)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self._items)

    def __str__(self):
        return str(self._items)

    def __contains__(self, item):
        i = bisect.bisect_left(self._items, item)
        j = bisect.bisect_right(self._items, item)
        return item in self._items[i:j]

    def index(self, item):
        i = bisect.bisect_left(self._items, item)
        j = bisect.bisect_right(self._items, item)
        return self._items[i:j].index(item) + i

    def _add(self, item):
        if item is not None and item not in self:
            i = bisect.bisect_left(self._items, item)
            self._items.insert(i, item)

    def _remove(self, item):
        i = self.index(item)
        del self._items[i]













class environment:
    """
    Context manager that directs file operations to a model id of a Environment

    In some cases the environment's current model should be be the same
    when the context exits as it was when the context was entered.  In
    other situations, a change to the evironment's current model should be
    maintained after the context has exited.  Evaluating multiple models
    serves as an example of the former behavior, and training is an example
    of the latter.

    #   Evaluating previously trained models:
    #   We just want to evaluate the model, the environment's
    #   state should be completely restored once we are done
    start_model = Environment('foo').current_model
    for model_id in range(10):
        with environment('foo', model_id):
            model = load_model('bar.h5')
            metrics[model_id] = calculate_some_metric(model)

    assert start_model == Environment('foo').current_model

    #   Training a new model:
    #   We want train a model in using a new model id and examine the
    #   training log externally when the training is complete.  We need
    #   the environment's current model to remain set to the newly created
    #   id so that external tools (e.g. log reader) know which model was
    #   just trained (i.e. the current one).
    with environment('foo', restore_model_id=False) as environ:
        new_model = environ.create_model()
        environ.current_model = new_model
        train_the_model_with_logging(model)
        save_model(model, 'bar.h5')

    assert new_model == Environment('foo').current_model

    By default the original current model id is restored when the context
    exits.  Setting the restore_model_id argument to False will
    maintain any changes to the environment's current model.

    Args:
        environ: Environment object or name,
            if None, the currently active environment is used
        model_id(int): the id of the current model
            if None, the environment's current model is not changed
        restore_model_id(bool): if True, change the current model back to
            the current model before entering the context, otherwise keep
            the environment's current model set to the value given to
            model_id.
    """
    _stack = list()

    @classmethod
    def top(cls):
        """
        The current context's environment object

        This is used by functions defined outside of this class to
        access the context's environment.  For example, a save_model
        function might consider its file path argument as being relative
        to the context's current model path (i.e. environment.top().model_path()).

        Returns:
            The Environment object used in the most recent instance
            of the context manager.
        """
        try:
            return cls._stack[-1]
        except IndexError:
            return None


    def __init__(self, environ=None, model_id=None, restore_model_id=True):
        if environ is None or isinstance(environ, str):
            environ = Environment(environ)
        self._environ = environ
        self._model_id = model_id
        self._previous_model_id = None
        self._restore_model_id_on_exit = restore_model_id
        self._model_file_handlers = dict()


    @property
    def environ(self):
        return self._environ

    @property
    def model_id(self):
        return self._model_id


    def _update_model_file_logging_handlers(self):
        #   redirect logging to the environment
        from . import logging as kt_logging
        for logger in logging.Logger.manager.loggerDict.values():
            #   logger PlaceHolder objects don't have 'handler', ignore them
            with contextlib.suppress(AttributeError):
                for handler in logger.handlers:
                    if isinstance(handler, kt_logging.ModelFileHandler):
                        self._model_file_handlers[handler] = handler.environ
                        handler.environ = self.environ


    def _restore_model_file_logging_handlers(self):
        for handler, environ in self._model_file_handlers.items():
            handler.environ = environ


    def __enter__(self):
        #   switch to the given model
        self._previous_model_id = self.environ.current_model
        if self.model_id is not None:
            environ.current_model = self.model_id

        self._update_model_file_logging_handlers()

        environment._stack.append(self.environ)

        return self.environ


    def __exit__(self, exception_type, exception_value, traceback):
        self._restore_model_file_logging_handlers()

        if self._restore_model_id_on_exit:
            self.environ.current_model = self._previous_model_id

        environment._stack.pop()
































##   ============================================================================
##   ============================================================================
##   ============================================================================
##   ============================================================================




#__all__ = ['Environment', 'EnvironmentException',
           #'GlobalConfiguration', 'ConfigurationNotFoundError', 'MetadataExistsError',
           #'EnvironmentNotFoundError', 'EnvironmentExistsError', 'EnvironmentNotActiveError',
           #'NoCurrentModelError', 'ModelNotFoundError']


#class Configuration(collections.Mapping):
    #def __init__(self, config_filepath):
        #self._config_filepath = pathlib.Path(config_filepath)
        #self._variables = dict()
        #self._change_callbacks = dict()
        #self._change_callbacks_enabled = True
        #self._delete_callbacks = dict()
        #self._delete_callbacks_enabled = True

        ##   watch for changes to the environment's directory
        ##   and watch for modifications to the config file
        #class ConfigAutoloader(watchdog.events.FileSystemEventHandler):
            #def __init__(self, config):
                #self.config = config
                #self.ignore_change = False

            #def on_modified(self, event):
                #if event.src_path == self.config._config_filepath:
                    #if not self.ignore_change:
                        #self.environment.load()
                    #self.ignore_change = False

            #def on_moved(self, event):
                #if event.src_path == self.config._config_filepath:
                    #self.config._config_filepath = event.dest_path

        #self._autoloader = ConfigAutoloader(self)

        #self._file_watcher = watchdog.observers.Observer()
        #self._file_watcher.schedule(self._autoloader,
                                    #str(self._config_filepath.parent))
        #self._file_watcher.start()

        #self.load()



    #def save(self, **extra_variables):
        ##   ignore the next modification event because it is being
        ##   triggered by this method and doesn't require a load
        #self._autoloader.ignore_change = True

        #config = dict(self._variables.items(), **extra_variables)
        #with self._config_filepath.open('w') as file:
            #json.dump(config, file, indent=4)


    #def load(self):
        #with self._config_filepath.open('r') as file:
            #new_variables = json.load(file)

        ##   delete keys not in new_variables so callbacks are run
        #removed_keys = set(self._variables).difference(new_variables)
        #for key in removed_keys:
            #del self[key]

        ##   copy new_variables so that callbacks are run
        #for key, value in new_variables.items():
            #self[key] = value


    #def add_change_callback(self, key, callback):
        #self._change_callbacks.setdefault(key, CallbackSet()).add(callback)

    #def remove_change_callback(self, key, callback):
        #self._change_callbacks[key].remove(callback)

    #def enable_change_callbacks(self):
        #self._change_callbacks_enabled = True

    #def disable_change_callbacks(self):
        #self._change_callbacks_enabled = False

    #def is_change_callbacks_enabled(self):
        #return self._change_callbacks_enabled

    #def _change_callback(self, key, current_value, previous_value):
        #if self.is_change_callbacks_enabled():
            #for callback in self._change_callbacks.get(key, set()):
                #callback(current_value, previous_value)


    #def add_delete_callback(self, key, callback):
        #self._delete_callbacks.setdefault(key, CallbackSet()).add(callback)

    #def remove_delete_callback(self, key, callback):
        #self._delete_callbacks[key].remove(callback)

    #def enable_delete_callbacks(self):
        #self._delete_callbacks_enabled = True

    #def disable_delete_callbacks(self):
        #self._delete_callbacks_enabled = False

    #def is_delete_callbacks_enabled(self):
        #return self._delete_callbacks_enabled

    #def _delete_callback(self, key, value):
        #if self.is_delete_callbacks_enabled():
            #for callback in self._delete_callbacks.get(key, set()):
                #callback(value)


    #@contextlib.contextmanager
    #def callbacks_disabled(self, *callback_types):
        #if not callback_types:
            #callback_types = ['change', 'delete']

        #change_callbacks_enabled = self.is_change_callbacks_enabled()
        #delete_callbacks_enabled = self.is_delete_callbacks_enabled()

        #if 'change' in callback_types:
            #self.disable_change_callbacks()
        #if 'delete' in callback_types:
            #self.disable_delete_callbacks()

        #yield

        #if change_callbacks_enabled:
            #self.enable_change_callbacks()
        #if delete_callbacks_enabled:
            #self.enable_delete_callbacks()


    ##   ------------------------------------------------------------------------
    ##                           Map Interface
    ##   ------------------------------------------------------------------------
    #def __getitem__(self, key):
        #return self._variables[key]

    #def __setitem__(self, key, value):
        #previous_value = self._variables.get(key, None)
        #if previous_value != value:
            #self._variables[key] = value
            #self._change_callback(key, value, previous_value)
            #self.save()

    #def __delitem__(self, key):
        #value = self._variables.pop(key)
        #_delete_callback(key, value)
        #with contextlib.suppress(KeyError):
            #del self._callbacks[key]
        #with contextlib.suppress(KeyError):
            #del self._delete_callbacks[key]

    #def __contains__(self, key):
        #return key in self._variables

    #def __iter__(self):
        #return iter(self._variables)

    #def __len__(self):
        #return len(self._variables)

    #def keys(self):
        #return self._variables.keys()

    #def values(self):
        #return self._variables.values()

    #def items(self):
        #return self._variables.items()

    #def get(self, key, default=None):
        #return self._variables.get(key, default)

    #def setdefault(self, key, default):
        #if key not in self._variables:
            #self[key] = default
        #return self._variables[key]











#class EnvironmentException(Exception):
    #pass

#class ConfigurationNotFoundError(EnvironmentException):
    #def __init__(self):
        #self.__init__('environment root directory not found - '
                      #'missing {} file'.format(GlobalConfiguration.CONFIG_FILENAME))

#class ConfigurationExistsError(EnvironmentException):
    #def __init__(self):
        #self.__init__('environment already exists - '
                      #'found {} file'.format(GlobalConfiguration.CONFIG_FILENAME))

#class GlobalConfiguration(Configuration):
    #CONFIG_FILENAME = '.mle'
    #CONFIG_SUFFIX = '.mle'

    ##   cache of environment objects, maps name -> Environment object
    #_global_configurations_cache = dict()
    ##   used to synchronize access to _environments_cache during
    ##   __new__, __init__ & __del__
    #_creation_lock = threading.Lock()

    #def __new__(cls, root=None):
        #cls._creation_lock.acquire()

        #with cls._creation_lock:
            #if root is None:
                #root = pathlib.Path.cwd()
            #else:
                #root = pathlib.Path(_expand(str(root)))

            #while not (root / GlobalConfiguration.CONFIG_FILENAME).exists():
                #root = root.parent
                ##   i.e. if root == '/'
                #if root == root.parent:
                    #raise ConfigurationNotFoundError()

            #root.resolve()

            #try:
                #global_config = cls._global_configurations_cache[root]
            #except KeyError:
                #global_config = super().__new__(cls)
                #global_config._root = root
                #cls._global_configurations_cache[root] = global_config


        #return global_config


    #def __init__(self, root=None):
        #with type(self)._creation_lock:
            #if hasattr(self, '_current_environment'):
                #return

            #try:
                #super().__init__(self.root / GlobalConfiguration.CONFIG_FILENAME)

                #self.add_change_callback('current_environment', self._on_current_environment_changed)
                #self.add_delete_callback('current_environment', self._on_current_environment_deleted)

                ##   cache of environment objects, maps rel. path -> Environment object
                #self._environments_cache = dict()

            #except Exception:
                #del type(self)._global_configurations_cache[self._root]
                #raise


    #def __del__(self):
        #with type(self)._creation_lock:
            #with contextlib.suppress(KeyError):
                #del type(self)._global_configurations_cache[self._root]


    #@classmethod
    #def create(cls, root='.'):
        #"""
        #Creates a global configuration file

        #If a global configuration file already exists, this function returns the
        #corresponding metadata object

        #Args:
            #root: the root directory where environments will be created

        #Returns:
            #A GlobalConfiguration object corresponding to the created file

        #Raises:
            #ConfigurationExistsError if a global configuration file already
                #exists in the given root directory
        #"""
        #root = pathlib.Path(_expand(root))
        #root.resolve()

        #if (root / GlobalConfiguration.CONFIG_FILENAME).exists():
            #raise ConfigurationExistsError()

        #with (root / GlobalConfiguration.CONFIG_FILENAME).open('w') as file:
            #json.dump({'current_environment': None}, file, indent=4)

        #return cls(root)



    #@property
    #def current(self):
        #current_environment = self.get('current_environment', None)
        #if current_environment is None:
            #raise EnvironmentNotActiveError()

        #return current_environment


    #@current.setter
    #def current(self, current):
        #current = pathlib.Path(current)
        #if current.is_absolute():
            #current = current.relative_to(self.root)

        #if current is not None and not self.exists(current):
            #raise EnvironmentNotFoundError(current_name)
        #self['current_environment'] = current


    #def _on_current_environment_changed(self, current_name, previous_name):
        ##   guard against modifications to the config file from outside the program
        #if current_name is not None and not self.exists(current_name):
            #self['current_environment'] = None

    #def _on_current_environment_deleted(self, name):
        ##   guard against modifications to the config file from outside the program
        #self.add_change_callback('current_environment', self._on_current_environment_changed)
        #self.add_delete_callback('current_environment', self._on_current_environment_deleted)
        #self['current_environment'] = None


    #@property
    #def root(self):
        #return self._root


    #@property
    #def existing_environment_names(self):
        #return [path.stem for path in self.root.glob('*/*' + GlobalConfiguration.CONFIG_SUFFIX)]


    #def exists(self, name):
        #return self.build_config_path(name).exists()


    #def path_to_name(self, path):
        #if path is None:
            #raise ValueError('path is None')

        #return str(pathlib.Path(_expand(path)).relative_to(self.root))


    #def name_to_path(self, name):
        #if name is None:
            #raise ValueError('name is None')

        #return self.root / _expand(name)


    #def build_config_path(self, name):
        #config_filename = _expand(name) + GlobalConfiguration.CONFIG_SUFFIX
        #return self.name_to_path(name) / config_filename


    #def load(self):
        #super(Configuration, self).load()
        #self.setdefault('current_environment', None)

        ##   if the current environment loaded from the config file does
        ##   not have a corresponding directory, e.g. maybe the user removed it
        #with contextlib.suppress(EnvironmentNotActiveError):
            #if not self.name_to_path(self.current).exists():
                #self.current_environment = None
















#class EnvironmentNotFoundError(EnvironmentException):
    #def __init__(self, name):
        #super().__init__('environment {} does not exist'.format(name))

#class EnvironmentExistsError(EnvironmentException):
    #def __init__(self, name):
        #super().__init__('environment {} already exists'.format(name))

#class EnvironmentNotActiveError(EnvironmentException):
    #def __init__(self):
        #self.__init__('no active environment')

#class NoCurrentModelError(EnvironmentException):
    #def __init__(self, environ):
        #super().__init__('environment {} does not have '
                         #'a current model'.format(environ.name))
        #self.environ = environ

#class ModelNotFoundError(EnvironmentException):
    #def __init__(self, environ, model):
        #super().__init__('environment {} does not have '
                         #'model {}'.format(environ.name, model))
        #self.environ = environ
        #self.model = model




#class Environment(Configuration):
    #"""
    #Attributes:
        #name(str): part of the path relative to the global root
        #path(pathlib.Path): the path to the environment's directory
        #current_model(int): the id of the currently active model
            #i.e. the active model directory is <path>/model<current_model>/
        #models: an ordered set of existing model ids

    #TODO: handle rename environment directory -> invalidates cache key
    #"""
    ##   cache of environment objects, maps name -> Environment object
    #_environments_cache = dict()
    ##   used to synchronize access to _environments_cache during
    ##   __new__, __init__ & __del__
    #_creation_lock = threading.Lock()

    ##def __new__(cls, name=None):
        ##with cls._creation_lock:
            ##if name is None:
                ##global_config = GlobalConfiguration()
            ##else:
                ###   name could be an absolute path if user needs to access
                ###   the environment from a current working directory outside
                ###   the environment's global root directory
                ##root = pathlib.Path(name)
                ##if root.is_absolute():
                    ##global_config = GlobalConfiguration(root)
                    ##name = global_config.path_to_name(name)
                ##else:
                    ##global_config = GlobalConfiguration()

            ##if name is None:
                ##name = global_config.current
                ###if name is None:
                    ###raise EnvironmentNotActiveError()

            ##if not global_config.exists(name):
                ##raise EnvironmentNotFoundError(name)

            ##try:
                ##environment = cls._environments_cache[name]
            ##except KeyError:
                ##environment = super().__new__(cls)
                ##environment._name = name
                ##cls._environments_cache[name] = environment

        ##return environment


    ##def __init__(self, name=None):
        ###   skip initialization if self has already been initialized
        ##with type(self)._creation_lock:
            ##if hasattr(self, '_models'):
                ##return

            ##global_config = GlobalConfiguration()

            ##super().__init__(global_config.build_config_path(name))

            ##self._name = name

            ###   watch for adding, removing, & moving model directories
            ##self._model_handler = ModelEventHandler(self)
            ##self._model_watch = self._file_watcher.schedule(self._model_handler,
                                                            ##str(self.path))

            ###   watch moving environment path
            ##self._environ_handler = EnvironmentDirectoryHandler(self)
            ##self._environ_watch = self._file_watcher.schedule(self._environ_handler,
                                                              ##str(self.path.parent))

            ###self._name = name
            ###self._path = global_config.name_to_path(self._name)

            ###super().__init__(global_config.build_config_path(self._name))


            ###self._file_watcher.schedule(ModelEventHandler(self), str(self.path))


            ##self.path.mkdir(parents=True, exist_ok=True)
            ##self._models = self._build_models()

            ##self.add_change_callback('current_model', self._on_current_model_changed)
            ##self.add_delete_callback('current_model', self._on_current_model_deleted)

        ##except Exception:
            ##del type(self)._environments_cache[self._name]
            ##raise


    ##def __del__(self):
        ##with type(self)._creation_lock:
            ##with contextlib.suppress(KeyError):
                ##del type(self)._environments_cache[self._name]


    ##def _rename(self, name):
        ##with type(self)._creation_lock:
            ##del type(self)._environments_cache[self._name]

            ##self._name = name
            ##self._path = global_config.name_to_path(self.name)

            ###   the path changes when name changes, update file system watchers
            ##self._file_watcher.unschedule(self._model_watch)
            ##self._model_watch = self._file_watcher.schedule(self._model_handler,
                                                            ##str(self.path))

            ##self._file_watcher.unschedule(self._environ_watch)
            ##self._environ_watch = self._file_watcher.schedule(self._environ_handler,
                                                            ##str(self.path.parent))

            ##type(self)._environments_cache[self._name] = self







    #def __new__(cls, path=None):
        #with cls._creation_lock:
            ##   searches upward from path for global config
            #global_config = GlobalConfiguration(path)


            ##if path is None:
                ##path = global_config.path_to_name(global_config.current)
                ###if name is None:
                    ###raise EnvironmentNotActiveError()

            ##if not path.exists():
                ##raise EnvironmentNotFoundError(name)


            #if path is None:
                #path = global_config.current
            #else:
                #path = pathlib.Path(path)
                #if path.is_absolute():
                    #path = path.relative_to(global_config.root)


            #path.mkdir(parents=True, exist_ok=True)

            #try:
                #environment = global_config._environments_cache[path]
                ##environment = cls._environments_cache[path]
            #except KeyError:
                #environment = super().__new__(cls)
                #global_config._environments_cache[path] = environment
                ##cls._environments_cache[path] = environment

        #return environment


    #def __init__(self, path=None):
        ##   skip initialization if self has already been initialized
        #with type(self)._creation_lock:
            #if hasattr(self, '_models'):
                #return

            #super().__init__(path / GlobalConfiguration.CONFIG_SUFFIX)

            #self._path = path

            ##   watch for adding, removing, & moving model directories
            #self._model_handler = ModelEventHandler(self)
            #self._model_watch = self._file_watcher.schedule(self._model_handler,
                                                            #str(self.path))

            ##   watch moving environment path
            #self._environ_handler = EnvironmentDirectoryHandler(self)
            #self._environ_watch = self._file_watcher.schedule(self._environ_handler,
                                                              #str(self.path.parent))

            #self.path.mkdir(parents=True, exist_ok=True)
            #self._models = self._build_models()

            #self.add_change_callback('current_model', self._on_current_model_changed)
            #self.add_delete_callback('current_model', self._on_current_model_deleted)

        #except Exception:
            #del type(self)._environments_cache[self._path]
            #raise


    #def __del__(self):
        #with type(self)._creation_lock:
            #with contextlib.suppress(KeyError):
                #del type(self)._environments_cache[self._path]


    #def _rename(self, path):
        #with type(self)._creation_lock:
            #del type(self)._environments_cache[self._path]

            #self._path = path

            ##   the path changes when name changes, update file system watchers
            #self._file_watcher.unschedule(self._model_watch)
            #self._model_watch = self._file_watcher.schedule(self._model_handler,
                                                            #str(self.path))

            #self._file_watcher.unschedule(self._environ_watch)
            #self._environ_watch = self._file_watcher.schedule(self._environ_handler,
                                                            #str(self.path.parent))

            #type(self)._environments_cache[self._path] = self





    #def _build_models(self):
        ##   build list of model indices from directory names
        #models = ModelIndexSet()
        #for model_path in self.path.glob('model*'):
            #if model_path.is_dir():
                #model = ModelEventHandler.parse_model_identifier(model_path)
                #models._add(model)

        #return models


    #@classmethod
    #def create(cls, path):
        #"""
        #Create a new environment

        #Args:
            #name (str): the name of the environment

        #Returns:
            #A Environment object

        #Raises:
            #EnvironmentExistsError if the environment already exists
        #"""
        #global_config = GlobalConfiguration(path)

        #if global_config.exists(name):
            #raise EnvironmentExistsError()

        #return Environment(name)



    #def load(self):
        #super(Configuration, self).load()
        #self.setdefault('current_model', None)

        ##   if the current model load from the config does not have
        ##   a corresponding directory, e.g. maybe the user removed it
        #with contextlib.suppress(NoCurrentModelError):
            #if not self.model_path().exists():
                #self.current_model = None


    #def destroy(self):
        #shutil.rmtree(self.path)

        #global_config = GlobalConfiguration()
        #if global_config.current == self.name:
            #global_config.current = None

        #del self


    #def activate(self):
        #global_config = GlobalConfiguration()
        #global_config.current = self.name


    #def model_path(self, file_path=None, model=None):
        #model = self.current_model if model is None else model

        #model_path = self.path / 'model{}'.format(model)
        #if file_path is not None:
            #model_path = model_path / file_path

        #return model_path


    #def log_path(self, file_path=None, model=None):
        #model_path = self.model_path(model=model)

        #log_path = model_path / 'logs'
        #if file_path is not None:
            #log_path = log_path / file_path

        #return log_path


    #@property
    #def path(self):
        #return global_config.name_to_path(self.name)
        ##return self._path


    #@property
    #def name(self):
        #return self._name


    #@property
    #def models(self):
        #return self._models


    #@property
    #def current_model(self):
        #current_model = self.get('current_model')
        #if current_model is None:
            #raise NoCurrentModelError(self)

        #return current_model

    #@current_model.setter
    #def current_model(self, current_model):
        #if current_model is not None and current_model not in self.models:
            #raise ModelNotFoundError(self, current_model)
        #self['current_model'] = current_model


    #def _on_current_model_changed(self, current_model, previous_model):
        ##   guard against modifications to the config file from outside the program
        #if current_model is not None and current_model not in self.models:
            #self['current_model'] = None

    #def _on_current_model_deleted(self, model):
        ##   guard against modifications to the config file from outside the program
        #self.add_change_callback('current_model', self._on_current_model_changed)
        #self.add_delete_callback('current_model', self._on_current_model_deleted)
        #self['current_model'] = None


    #def has_current_model(self):
        #"""Returns True if a current model has been assigned"""
        #return self.get('current_model') is not None


    #def create_model(self):
        #try:
            #model = 1 + self.models[-1]
        #except IndexError:
            #model = 0

        #self.model_path(model=model).mkdir(exist_ok=False)
        #self.log_path(model=model).mkdir(exist_ok=False)
        #self.models._add(model)

        #return model


    #def discard_model(self, model):
        #with tensorboard.suspender(purge=True):
            #self._discard_model(model)


    #def discard_models(self, models):
        #if models:
            #with tensorboard.suspender(purge=True):
                #for model in models:
                    #self._discard_model(model)


    #def discard_all_models(self):
        #self.discard_models(self.models.copy())


    #def discard_other_models(self, model):
        #"""Remove all models except the current model"""
        #others = self.models.copy()
        #others._remove(model)
        #self.discard_models(others)


    #def reorder_models(self):
        #"""Reassigns model id numbers so they make a continguous range"""
        #with tensorboard.suspender(purge=True):
            #for i, model in enumerate(self.models.copy()):
                #if i != model:
                    #target = self.model_path(i)
                    #self.model_path(model=model).rename(target)


    #def _discard_model(self, model):
        #shutil.rmtree(str(self.model_path(model=model)))


    #def clear_logs(self, model=None):
        #with contextlib.suppress(NoCurrentModelError):
            #for item in self.log_path(model=model).iterdir():
                #if item.is_dir():
                    #shutil.rmtree(str(item))
                #else:
                    #item.unlink()














#class ModelEventHandler(watchdog.events.FileSystemEventHandler):
    #MODEL_DIRECTORY_PATTERN = re.compile(r'model(\d+)')

    #def __init__(self, environment):
        #self.environment = environment


    #@staticmethod
    #def parse_model_identifier(path):
        #path = pathlib.Path(path)
        #match = ModelEventHandler.MODEL_DIRECTORY_PATTERN.match(path.name)

        #return int(match.groups(1)[0]) if match is not None else None


    #def on_created(self, event):
        #if event.is_directory:
            #model_identifier = self.parse_model_identifier(event.src_path)
            #self.add(model_identifier)


    #def on_deleted(self, event):
        #if event.is_directory:
            #model_identifier = self.parse_model_identifier(event.src_path)
            #self.remove(model_identifier, None)


    #def on_moved(self, event):
        #if event.is_directory:
            #source_model_identifier = self.parse_model_identifier(event.src_path)
            #dest_model_identifier = self.parse_model_identifier(event.dest_path)

            #self.add(dest_model_identifier)
            #self.remove(source_model_identifier, dest_model_identifier)


    #def remove(self, model_identifier, new_current_model):
        #if self.environment.current_model == model_identifier:
            #self.environment.current_model = new_current_model

        #self.environment._models._remove(model_identifier)


    #def add(self, model_identifier):
        #self.environment._models._add(model_identifier)



#class EnvironmentDirectoryHandler(watchdog.events.FileSystemEventHandler):
    #def __init__(self, environment):
        #self.environment = environment

    #def on_moved(self, event):
        ##   if the environment's directory was moved
        #if event.src_path == self.environment.path:
            #try:
                #global_config = GlobalConfiguration(event.dest_path)
            #except ConfigurationNotFoundError:
                ##   the environment directory was moved outside of a mle root
                ##   note: this will lead to references to deleted objects
                #del self.environment
                #raise

            #name = global_config.path_to_name(event.dest_path)
            #self.environment._rename(name)





#class ModelIndexSet:
    #"""Ordered set of model identifiers"""
    #def __init__(self, items=()):
        #self._items = list(sorted(items))

    #def clear(self):
        #self.__init__([])

    #def copy(self):
        #return self.__class__(self)

    #def __len__(self):
        #return len(self._items)

    #def __getitem__(self, i):
        #return self._items[i]

    #def __iter__(self):
        #return iter(self._items)

    #def __reversed__(self):
        #return reversed(self._items)

    #def __repr__(self):
        #return '%s(%r)' % (self.__class__.__name__, self._items)

    #def __str__(self):
        #return str(self._items)

    #def __contains__(self, item):
        #i = bisect.bisect_left(self._items, item)
        #j = bisect.bisect_right(self._items, item)
        #return item in self._items[i:j]

    #def index(self, item):
        #i = bisect.bisect_left(self._items, item)
        #j = bisect.bisect_right(self._items, item)
        #return self._items[i:j].index(item) + i

    #def _add(self, item):
        #if item is not None and item not in self:
            #i = bisect.bisect_left(self._items, item)
            #self._items.insert(i, item)

    #def _remove(self, item):
        #i = self.index(item)
        #del self._items[i]




#def _expand(path):
    #return os.path.expanduser(os.path.expandvars(path))



#class CallbackSet:
    #"""
    #Set of weak references to callbacks

    #weakref.WeakSet does not work with bound methods.
    #This class gets around that limitation.
    #"""
    #def __init__(self):
        #self._listeners = set()


    #def add(self, listener):
        #if inspect.ismethod(listener):
            #owner = listener.__self__
            #listener = weakref.WeakMethod(listener)
            #if listener not in self._listeners:
                #weakref.finalize(owner, self._discard, listener)
        #else:
            #listener = weakref.ref(listener, self._discard)

        #self._listeners.add(listener)


    #def remove(self, listener):
        #if inspect.ismethod(listener):
            #listener = weakref.WeakMethod(listener)
        #else:
            #listener = weakref.ref(listener)

        #self._listeners.remove(listener)


    #def __iter__(self):
        #return (listener() for listener in self._listeners
                #if listener() is not None)


    #def __len__(self):
        #return len(self._listeners)


    #def _discard(self, listener):
        #try:
            #self._listeners.remove(listener)
        #except KeyError:
            #pass







#class environment:
    #"""
    #Context manager that directs file operations to a model id of a Environment

    #In some cases the environment's current model should be be the same
    #when the context exits as it was when the context was entered.  In
    #other situations, a change to the evironment's current model should be
    #maintained after the context has exited.  Evaluating multiple models
    #serves as an example of the former behavior, and training is an example
    #of the latter.

    ##   Evaluating previously trained models:
    ##   We just want to evaluate the model, the environment's
    ##   state should be completely restored once we are done
    #start_model = Environment('foo').current_model
    #for model_id in range(10):
        #with environment('foo', model_id):
            #model = load_model('bar.h5')
            #metrics[model_id] = calculate_some_metric(model)

    #assert start_model == Environment('foo').current_model

    ##   Training a new model:
    ##   We want train a model in using a new model id and examine the
    ##   training log externally when the training is complete.  We need
    ##   the environment's current model to remain set to the newly created
    ##   id so that external tools (e.g. log reader) know which model was
    ##   just trained (i.e. the current one).
    #with environment('foo', restore_model_id=False) as environ:
        #new_model = environ.create_model()
        #environ.current_model = new_model
        #train_the_model_with_logging(model)
        #save_model(model, 'bar.h5')

    #assert new_model == Environment('foo').current_model

    #By default the original current model id is restored when the context
    #exits.  Setting the restore_model_id argument to False will
    #maintain any changes to the environment's current model.

    #Args:
        #environ: Environment object or name,
            #if None, the currently active environment is used
        #model_id(int): the id of the current model
            #if None, the environment's current model is not changed
        #restore_model_id(bool): if True, change the current model back to
            #the current model before entering the context, otherwise keep
            #the environment's current model set to the value given to
            #model_id.
    #"""
    #_stack = list()

    #@classmethod
    #def top(cls):
        #"""
        #The current context's environment object

        #This is used by functions defined outside of this class to
        #access the context's environment.  For example, a save_model
        #function might consider its file path argument as being relative
        #to the context's current model path (i.e. environment.top().model_path()).

        #Returns:
            #The Environment object used in the most recent instance
            #of the context manager.
        #"""
        #try:
            #return cls._stack[-1]
        #except IndexError:
            #return None


    #def __init__(self, environ=None, model_id=None, restore_model_id=True):
        #if environ is None or isinstance(environ, str):
            #environ = Environment(environ)
        #self._environ = environ
        #self._model_id = model_id
        #self._previous_model_id = None
        #self._restore_model_id_on_exit = restore_model_id
        #self._model_file_handlers = dict()


    #@property
    #def environ(self):
        #return self._environ

    #@property
    #def model_id(self):
        #return self._model_id


    #def _update_model_file_logging_handlers(self):
        ##   redirect logging to the environment
        #from . import logging as kt_logging
        #for logger in logging.Logger.manager.loggerDict.values():
            ##   logger PlaceHolder objects don't have 'handler', ignore them
            #with contextlib.suppress(AttributeError):
                #for handler in logger.handlers:
                    #if isinstance(handler, kt_logging.ModelFileHandler):
                        #self._model_file_handlers[handler] = handler.environ
                        #handler.environ = self.environ


    #def _restore_model_file_logging_handlers(self):
        #for handler, environ in self._model_file_handlers.items():
            #handler.environ = environ


    #def __enter__(self):
        ##   switch to the given model
        #self._previous_model_id = self.environ.current_model
        #if self.model_id is not None:
            #environ.current_model = self.model_id

        #self._update_model_file_logging_handlers()

        #environment._stack.append(self.environ)

        #return self.environ


    #def __exit__(self, exception_type, exception_value, traceback):
        #self._restore_model_file_logging_handlers()

        #if self._restore_model_id_on_exit:
            #self.environ.current_model = self._previous_model_id

        #environment._stack.pop()




















































##"""
##Environment management
##"""
##import pathlib
##import os.path
##import re
##import shutil
##import json
##import bisect
##import weakref
##import inspect
##import threading
##import contextlib

##import watchdog.events
##import watchdog.observers

##from . import tensorboard


##__all__ = ['Environment', 'EnvironmentException',
           ##'GlobalConfiguration', 'ConfigurationNotFoundError', 'MetadataExistsError',
           ##'EnvironmentNotFoundError', 'EnvironmentExistsError', 'EnvironmentNotActiveError',
           ##'NoCurrentModelError', 'ModelNotFoundError']


##class Configuration(collections.Mapping):
    ##def __init__(self, config_filepath):
        ##self._config_filepath = pathlib.Path(config_filepath)
        ##self._variables = dict()
        ##self._change_callbacks = dict()
        ##self._change_callbacks_enabled = True
        ##self._delete_callbacks = dict()
        ##self._delete_callbacks_enabled = True

        ###   watch for changes to the environment's directory
        ###   and watch for modifications to the config file
        ##class ConfigAutoloader(watchdog.events.FileSystemEventHandler):
            ##def __init__(self, config):
                ##self.config = config
                ##self.ignore_change = False

            ##def on_modified(self, event):
                ##if event.src_path == self.config._config_filepath:
                    ##if not self.ignore_change:
                        ##self.environment.load()
                    ##self.ignore_change = False

        ##self._autoloader = ConfigAutoloader(self)

        ##self._file_watcher = watchdog.observers.Observer()
        ##self._file_watcher.schedule(self._autoloader,
                                    ##str(self._config_filepath.parent))
        ##self._file_watcher.start()

        ##self.load()



    ##def save(self, **extra_variables):
        ###   ignore the next modification event because it is being
        ###   triggered by this method and doesn't require a load
        ##self._autoloader.ignore_change = True

        ##config = dict(self._variables.items(), **extra_variables)
        ##with self._config_filepath.open('w') as file:
            ##json.dump(config, file, indent=4)


    ##def load(self):
        ##old_variables = self._variables
        ##with self._config_filepath.open('r') as file:
            ##self._variables = json.load(file)

        ###   run deleted callbacks
        ##removed_keys = set(old_variables).difference(self._variables.keys())
        ##for key in removed_keys:
            ##self._delete_callback(key, old_variables.pop(key))

        ###   run changed callbacks
        ##for key, previous_value in old_variables.items():
            ##current_value = self._variables.get(key, None):
            ##if current_value != previous_value:
                ##self._change_callback(key, current_value, previous_value)


    ##def add_change_callback(self, key, callback):
        ##self._change_callbacks.setdefault(key, CallbackSet()).add(callback)

    ##def remove_change_callback(self, key, callback):
        ##self._change_callbacks[key].remove(callback)

    ##def enable_change_callbacks(self):
        ##self._change_callbacks_enabled = True

    ##def disable_change_callbacks(self):
        ##self._change_callbacks_enabled = False

    ##def is_change_callbacks_enabled(self):
        ##return self._change_callbacks_enabled

    ##def _change_callback(self, key, current_value, previous_value):
        ##if self.is_change_callbacks_enabled():
            ##for callback in self._change_callbacks.get(key, set()):
                ##callback(current_value, previous_value)


    ##def add_delete_callback(self, key, callback):
        ##self._delete_callbacks.setdefault(key, CallbackSet()).add(callback)

    ##def remove_delete_callback(self, key, callback):
        ##self._delete_callbacks[key].remove(callback)

    ##def enable_delete_callbacks(self):
        ##self._delete_callbacks_enabled = True

    ##def disable_delete_callbacks(self):
        ##self._delete_callbacks_enabled = False

    ##def is_delete_callbacks_enabled(self):
        ##return self._delete_callbacks_enabled

    ##def _delete_callback(self, key, value):
        ##if self.is_delete_callbacks_enabled():
            ##for callback in self._delete_callbacks.get(key, set()):
                ##callback(value)


    ##@contextlib.contextmanager
    ##def callbacks_disabled(self, *callback_types):
        ##if not callback_types:
            ##callback_types = ['change', 'delete']

        ##change_callbacks_enabled = self.is_change_callbacks_enabled()
        ##delete_callbacks_enabled = self.is_delete_callbacks_enabled()

        ##if 'change' in callback_types:
            ##self.disable_change_callbacks()
        ##if 'delete' in callback_types:
            ##self.disable_delete_callbacks()

        ##yield

        ##if change_callbacks_enabled:
            ##self.enable_change_callbacks()
        ##if delete_callbacks_enabled:
            ##self.enable_delete_callbacks()


    ###   ------------------------------------------------------------------------
    ###                           Map Interface
    ###   ------------------------------------------------------------------------
    ##def __getitem__(self, key):
        ##return self._variables[key]

    ##def __setitem__(self, key, value):
        ##previous_value = self._variables.get(key, None)
        ##if previous_value != value:
            ##self._variables[key] = value
            ##self._change_callback(key, value, previous_value)
            ##self.save()

    ##def __delitem__(self, key):
        ##value = self._variables.pop(key)
        ##_delete_callback(key, value)
        ##with contextlib.suppress(KeyError):
            ##del self._callbacks[key]
        ##with contextlib.suppress(KeyError):
            ##del self._delete_callbacks[key]

    ##def __contains__(self, key):
        ##return key in self._variables

    ##def __iter__(self):
        ##return iter(self._variables)

    ##def __len__(self):
        ##return len(self._variables)

    ##def keys(self):
        ##return self._variables.keys()

    ##def values(self):
        ##return self._variables.values()

    ##def items(self):
        ##return self._variables.items()

    ##def get(self, key, default=None):
        ##return self._variables.get(key, default)

    ##def setdefault(self, key, default):
        ##if key not in self._variables:
            ##self[key] = default
        ##return self._variables[key]











##class EnvironmentException(Exception):
    ##pass

##class ConfigurationNotFoundError(EnvironmentException):
    ##def __init__(self):
        ##self.__init__('environment root directory not found - '
                      ##'missing {} file'.format(GlobalConfiguration.CONFIG_FILENAME))

##class ConfigurationExistsError(EnvironmentException):
    ##def __init__(self):
        ##self.__init__('environment already exists - '
                      ##'found {} file'.format(GlobalConfiguration.CONFIG_FILENAME))

##class GlobalConfiguration(Configuration):
    ##CONFIG_FILENAME = '.mle'
    ##CONFIG_SUFFIX = '.mle'

    ###   cache of environment objects, maps name -> Environment object
    ##_global_configurations_cache = dict()
    ###   used to synchronize access to _environments_cache during
    ###   __new__, __init__ & __del__
    ##_creation_lock = threading.Lock()

    ##def __new__(cls, root=None):
        ##cls._creation_lock.acquire()

        ##with cls._creation_lock:
            ##if root is None:
                ##root = pathlib.Path.cwd()
                ##while not (root / GlobalConfiguration.CONFIG_FILENAME).exists():
                    ##root = root.parent
                    ###   i.e. if root == '/'
                    ##if root == root.parent:
                        ##raise ConfigurationNotFoundError()
            ##else:
                ##root = pathlib.Path(_expand(str(root)))

            ##root.resolve()

            ##try:
                ##global_config = cls._global_configurations_cache[root]
            ##except KeyError:
                ##global_config = super().__new__(cls)
                ##global_config._root = root
                ##cls._global_configurations_cache[root] = global_config


        ##return global_config


    ##def __init__(self, root=None):
        ##with type(self)._creation_lock:
            ##if hasattr(self, '_current_environment'):
                ##return

            ##super().__init__(self.root / GlobalConfiguration.CONFIG_FILENAME)
            ##try:
                ##self._current_environment = None

                ##self.load()

            ##except Exception:
                ##del type(self)._global_configurations_cache[self._root]
                ##raise


    ##def __del__(self):
        ##with type(self)._creation_lock:
            ##with contextlib.suppress(KeyError):
                ##del type(self)._global_configurations_cache[self._root]


    ###def __init__(self, root=None):
        ###self._variables = dict()
        ###self._current_environment = None

        ###if root is None:
            ###self._root = pathlib.Path.cwd()

            ###while self._root != self._root.parent and not (self._root / GlobalConfiguration.CONFIG_FILENAME).exists():
                ###self._root = self._root.parent

            ####   i.e. if root == '/'
            ###if self._root == self._root.parent:
                ###raise ConfigurationNotFoundError()
        ###else:
            ###self._root = pathlib.Path(_expand(root))
            ###self._root.resolve()

        ###self.load()


    ###@classmethod
    ###def create(cls, root='.'):
        ###"""
        ###Creates a global configuration file

        ###If a global configuration file already exists, this function returns the
        ###corresponding metadata object

        ###Args:
            ###root: the root directory where environments will be created

        ###Returns:
            ###A GlobalConfiguration object corresponding to the created file

        ###Raises:
            ###ConfigurationExistsError if a global configuration file already
                ###exists in the given root directory
        ###"""
        ###root = pathlib.Path(_expand(root))
        ###root.resolve()

        ###if (root / GlobalConfiguration.CONFIG_FILENAME).exists():
            ###raise ConfigurationExistsError()

        ###global_config = cls.__new__(cls)

        ###global_config._variables = dict()
        ###global_config._variables['current'] = None
        ###global_config._root = root

        ###global_config.save()

        ###return global_config

    ##@classmethod
    ##def create(cls, root='.'):
        ##"""
        ##Creates a global configuration file

        ##If a global configuration file already exists, this function returns the
        ##corresponding metadata object

        ##Args:
            ##root: the root directory where environments will be created

        ##Returns:
            ##A GlobalConfiguration object corresponding to the created file

        ##Raises:
            ##ConfigurationExistsError if a global configuration file already
                ##exists in the given root directory
        ##"""
        ##root = pathlib.Path(_expand(root))
        ##root.resolve()

        ##if (root / GlobalConfiguration.CONFIG_FILENAME).exists():
            ##raise ConfigurationExistsError()

        ##with (root / GlobalConfiguration.CONFIG_FILENAME).open('w') as file:
            ##json.dump({'current_environment': None}, file, indent=4)

        ##return cls(root)


    ###@property
    ###def current(self):
        ###if self._current_environment is None:
            ###raise EnvironmentNotActiveError()

        ###return self._current_environment


    ###@current.setter
    ###def current(self, current):
        ###if current is not None and not self.exists(current):
            ###raise EnvironmentNotFoundError(current)

        ###self._set_current_environment(current, save=True)


    ###def _set_current_environment(self, name, save):
        ###if name != self._current:
            ###old_name = self._current
            ###self._current = name
            ###if save:
                ###self.save()

            ###for listener in self._current_change_listeners:
                ###listener(self._current, old_name)

    ##@property
    ##def current(self):
        ##current_environment = self.get('current_environment', None)
        ##if current_environment is None:
            ##raise EnvironmentNotActiveError()

        ##return current_environment


    ##@current.setter
    ##def current(self, current):
        ##if current is not None and not self.exists(current):
            ##raise EnvironmentNotFoundError(current_name)
        ##self['current_environment'] = current


    ##def _on_current_environment_changed(self, current_name, previous_name):
        ###   guard against modifications to the config file from outside the program
        ##if current_name is not None and not self.exists(current_name):
            ##self['current_environment'] = None



    ##@property
    ##def root(self):
        ##return self._root


    ##@property
    ##def existing_environment_names(self):
        ##return [path.stem for path in self.root.glob('*/*' + GlobalConfiguration.CONFIG_SUFFIX)]


    ##def exists(self, name):
        ##return self.build_config_path(name).exists()


    ##def path_to_name(self, path):
        ##if path is None:
            ##raise ValueError('path is None')

        ##return str(pathlib.Path(_expand(path)).relative_to(self.root))
        ###return pathlib.Path(_expand(path)).name


    ##def name_to_path(self, name):
        ##if name is None:
            ##raise ValueError('name is None')

        ##return self.root / _expand(name)


    ##def build_config_path(self, name):
        ##config_filename = _expand(name) + GlobalConfiguration.CONFIG_SUFFIX
        ##return self.name_to_path(name) / config_filename


    ##def load(self):
        ##super(Configuration, self).load()
        ##self.setdefault('current_environment', None)

        ###   if the current environment loaded from the config file does
        ###   not have a corresponding directory, e.g. maybe the user removed it
        ##with contextlib.suppress(EnvironmentNotActiveError):
            ##if not self.name_to_path(self.current).exists():
                ##self.current_environment = None
















##class EnvironmentNotFoundError(EnvironmentException):
    ##def __init__(self, name):
        ##super().__init__('environment {} does not exist'.format(name))

##class EnvironmentExistsError(EnvironmentException):
    ##def __init__(self, name):
        ##super().__init__('environment {} already exists'.format(name))

##class EnvironmentNotActiveError(EnvironmentException):
    ##def __init__(self):
        ##self.__init__('no active environment')

##class NoCurrentModelError(EnvironmentException):
    ##def __init__(self, environ):
        ##super().__init__('environment {} does not have '
                         ##'a current model'.format(environ.name))
        ##self.environ = environ

##class ModelNotFoundError(EnvironmentException):
    ##def __init__(self, environ, model):
        ##super().__init__('environment {} does not have '
                         ##'model {}'.format(environ.name, model))
        ##self.environ = environ
        ##self.model = model




##class Environment(Configuration):
    ##"""
    ##Attributes:
        ##name(str): part of the path relative to the global root
        ##path(pathlib.Path): the path to the environment's directory
        ##current_model(int): the id of the currently active model
            ##i.e. the active model directory is <path>/model<current_model>/
        ##models: an ordered set of existing model ids

    ##TODO: handle rename environment directory -> invalidates cache key
    ##"""
    ###   cache of environment objects, maps name -> Environment object
    ##_environments_cache = dict()
    ###   used to synchronize access to _environments_cache during
    ###   __new__, __init__ & __del__
    ##_creation_lock = threading.Lock()

    ##def __new__(cls, name=None):
        ##with cls._creation_lock:
            ###   could occur if user needs to access the environment
            ###   from outside the global root directory
            ##if pathlib.Path(name).is_absolute():
                ##do_something()

            ##global_config = GlobalConfiguration()

            ##if name is None:
                ##name = global_config.current
                ###if name is None:
                    ###raise EnvironmentNotActiveError()

            ##if not global_config.exists(name):
                ##raise EnvironmentNotFoundError(name)

            ##try:
                ##environment = cls._environments_cache[name]
            ##except KeyError:
                ##environment = super().__new__(cls)
                ##cls._environments_cache[name] = environment

        ##return environment


    ##def __init__(self, name=None):
        ###   skip initialization if self has already been initialized
        ##with type(self)._creation_lock:
            ##if hasattr(self, '_name'):
                ##return

            ##global_config = GlobalConfiguration()

            ##self._name = name
            ##self._path = global_config.name_to_path(self._name)

            ##super().__init__(global_config.build_config_path(self._name))

            ###self._config_path = global_config.build_config_path(self._name)
            ###self._variables = dict()
            ###self._current_model = None
            ###self._model_change_listeners = CallbackSet()

            ####   watch for changes to the environment's directory
            ####   and watch for modifications to the config file
            ###class ConfigAutoloader(watchdog.events.FileSystemEventHandler):
                ###def __init__(self, environment):
                    ###self.environment = environment
                    ###self.ignore_change = False

                ###def on_modified(self, event):
                    ###if event.src_path == self.environment._config_path:
                        ###if not self.ignore_change:
                            ###self.environment.load()
                        ###self.ignore_change = False

            ###self._autoloader = ConfigAutoloader(self)

            ###self._file_watcher = watchdog.observers.Observer()
            ##self._file_watcher.schedule(ModelEventHandler(self), str(self.path))
            ###self._file_watcher.schedule(self._autoloader, str(self.path))
            ###self._file_watcher.start()

            ###self.load()

            ##self.path.mkdir(parents=True, exist_ok=True)
            ##self._models = self._build_models()

            ##self.add_change_callback('current_model', self._on_current_model_changed)

        ##except Exception:
            ##del type(self)._environments_cache[self._name]
            ##raise


    ##def __del__(self):
        ##with type(self)._creation_lock:
            ##with contextlib.suppress(KeyError):
                ##del type(self)._environments_cache[self._name]


    ##def _build_models(self):
        ###   build list of model indices from directory names
        ##models = ModelIndexSet()
        ##for model_path in self.path.glob('model*'):
            ##if model_path.is_dir():
                ##model = ModelEventHandler.parse_model_identifier(model_path)
                ##models._add(model)

        ##return models


    ##@classmethod
    ##def create(cls, name):
        ##"""
        ##Create a new environment with the given name

        ##Args:
            ##name (str): the name of the environment

        ##Returns:
            ##A Environment object

        ##Raises:
            ##EnvironmentExistsError if the environment already exists
        ##"""
        ##global_config = GlobalConfiguration()

        ##if global_config.exists(name):
            ##raise EnvironmentExistsError()

        ##return Environment(name)


    ###def save(self):
        ####   ignore the next modification event because it is being
        ####   triggered by this method and doesn't require a load
        ###self._autoloader.ignore_change = True

        ###config = dict(self._variables, current_model=self.current_model)
        ###with self._config_path.open('w') as file:
            ###json.dump(config, file, indent=4)


    ###def load(self):
        ###try:
            ###with self._config_path.open('r') as file:
                ###self._variables = json.load(file)

            ###self._set_current_model(self._variables['current_model'], save=False)
            ###del self._variables['current_model']

        ###except (FileNotFoundError, KeyError):
            ###self._set_current_model(None, save=True)

        ####   if the current model load from the config does not have
        ####   a corresponding directory, e.g. maybe the user removed it
        ###with contextlib.suppress(NoCurrentModelError):
            ###if not self.model_path().exists():
                ###self._set_current_model(None, save=True)




    ##def load(self):
        ##super(Configuration, self).load()
        ##self.setdefault('current_model', None)

        ###   if the current model load from the config does not have
        ###   a corresponding directory, e.g. maybe the user removed it
        ##with contextlib.suppress(NoCurrentModelError):
            ##if not self.model_path().exists():
                ##self.current_model = None


    ##def destroy(self):
        ##shutil.rmtree(self.path)

        ##global_config = GlobalConfiguration()
        ##if global_config.current == self.name:
            ##global_config.current = None

        ##del self


    ##def activate(self):
        ##global_config = GlobalConfiguration()
        ##global_config.current = self.name


    ##def model_path(self, file_path=None, model=None):
        ##model = self.current_model if model is None else model

        ##model_path = self.path / 'model{}'.format(model)
        ##if file_path is not None:
            ##model_path = model_path / file_path

        ##return model_path


    ##def log_path(self, file_path=None, model=None):
        ##model_path = self.model_path(model=model)

        ##log_path = model_path / 'logs'
        ##if file_path is not None:
            ##log_path = log_path / file_path

        ##return log_path


    ##@property
    ##def path(self):
        ##return self._path


    ##@property
    ##def name(self):
        ##return self._name


    ##@property
    ##def models(self):
        ##return self._models


    ###@property
    ###def current_model(self):
        ###if self._current_model is None:
            ###raise NoCurrentModelError(self)
        ###return self._current_model

    ###@current_model.setter
    ###def current_model(self, current_model):
        ###if current_model is not None and current_model not in self.models:
            ###raise ModelNotFoundError(self, current_model)
        ###self._set_current_model(current_model, save=True)

    ##@property
    ##def current_model(self):
        ##current_model = self.get('current_model', None)
        ##if current_model is None:
            ##raise NoCurrentModelError(self)

        ##return current_model

    ##@current_model.setter
    ##def current_model(self, current_model):
        ##if current_model is not None and current_model not in self.models:
            ##raise ModelNotFoundError(self, current_model)
        ##self['current_model'] = current_model


    ##def _on_current_model_changed(self, current_model, previous_model):
        ###   guard against modifications to the config file from outside the program
        ##if current_model is not None and current_model not in self.models:
            ##self['current_model'] = None




    ##def has_current_model(self):
        ##"""Returns True if a current model has been assigned"""
        ##return self.get('current_model') is not None


    ###def add_model_change_listener(self, callback):
        ###"""
        ###Add a callback to listen for model changes

        ###Args:
            ###callback: callable taking 2 arguments, the new and old models
                ###e.g. def listener(new_model, old_model): ...
        ###"""
        ###self._model_change_listeners.add(callback)


    ###def remove_model_change_listener(self, callback):
        ###"""Remove a model change callback"""
        ###self._model_change_listeners.remove(callback)


    ##def create_model(self):
        ##try:
            ##model = 1 + self.models[-1]
        ##except IndexError:
            ##model = 0

        ##self.model_path(model=model).mkdir(exist_ok=False)
        ##self.log_path(model=model).mkdir(exist_ok=False)
        ##self.models._add(model)

        ##return model


    ##def discard_model(self, model):
        ##with tensorboard.suspender(purge=True):
            ##self._discard_model(model)


    ##def discard_models(self, models):
        ##if models:
            ##with tensorboard.suspender(purge=True):
                ##for model in models:
                    ##self._discard_model(model)


    ##def discard_all_models(self):
        ##self.discard_models(self.models.copy())


    ##def discard_other_models(self, model):
        ##"""Remove all models except the current model"""
        ##others = self.models.copy()
        ##others._remove(model)
        ##self.discard_models(others)


    ##def reorder_models(self):
        ##"""Reassigns model id numbers so they make a continguous range"""
        ##with tensorboard.suspender(purge=True):
            ##for i, model in enumerate(self.models.copy()):
                ##if i != model:
                    ##target = self.model_path(i)
                    ##self.model_path(model=model).rename(target)


    ##def _discard_model(self, model):
        ##shutil.rmtree(str(self.model_path(model=model)))


    ##def clear_logs(self, model=None):
        ##with contextlib.suppress(NoCurrentModelError):
            ##for item in self.log_path(model=model).iterdir():
                ##if item.is_dir():
                    ##shutil.rmtree(str(item))
                ##else:
                    ##item.unlink()




    ####   ------------------------------------------------------------------------
    ####                           Map Interface
    ####   ------------------------------------------------------------------------
    ###def __getitem__(self, key):
        ###return self._variables[key]

    ###def __setitem__(self, key, value):
        ###self._variables[key] = value
        ###self.save()

    ###def __delitem__(self, key):
        ###del self._variables[key]

    ###def __contains__(self, key):
        ###return key in self._variables

    ###def __iter__(self):
        ###return iter(self._variables)

    ###def __len__(self):
        ###return len(self._variables)

    ###def keys(self):
        ###return self._variables.keys()

    ###def values(self):
        ###return self._variables.values()

    ###def items(self):
        ###return self._variables.items()

    ###def get(self, key, default=None):
        ###return self._variables.get(key, default)

    ###def setdefault(self, key, default):
        ###return self._variables.setdefault(key, default)




##class ModelEventHandler(watchdog.events.FileSystemEventHandler):
    ##MODEL_DIRECTORY_PATTERN = re.compile(r'model(\d+)')

    ##def __init__(self, environment):
        ##self.environment = environment


    ##@staticmethod
    ##def parse_model_identifier(path):
        ##path = pathlib.Path(path)
        ##match = ModelEventHandler.MODEL_DIRECTORY_PATTERN.match(path.name)

        ##return int(match.groups(1)[0]) if match is not None else None


    ##def on_created(self, event):
        ##if event.is_directory:
            ##model_identifier = self.parse_model_identifier(event.src_path)
            ##self.add(model_identifier)


    ##def on_deleted(self, event):
        ##if event.is_directory:
            ##model_identifier = self.parse_model_identifier(event.src_path)
            ##self.remove(model_identifier, None)


    ##def on_moved(self, event):
        ##if event.is_directory:
            ##source_model_identifier = self.parse_model_identifier(event.src_path)
            ##dest_model_identifier = self.parse_model_identifier(event.dest_path)

            ##self.add(dest_model_identifier)
            ##self.remove(source_model_identifier, dest_model_identifier)


    ##def remove(self, model_identifier, new_current_model):
        ##if self.environment.current_model == model_identifier:
            ##self.environment.current_model = new_current_model

        ##self.environment._models._remove(model_identifier)


    ##def add(self, model_identifier):
        ##self.environment._models._add(model_identifier)




##class ModelIndexSet:
    ##"""Ordered set of model identifiers"""
    ##def __init__(self, items=()):
        ##self._items = list(sorted(items))

    ##def clear(self):
        ##self.__init__([])

    ##def copy(self):
        ##return self.__class__(self)

    ##def __len__(self):
        ##return len(self._items)

    ##def __getitem__(self, i):
        ##return self._items[i]

    ##def __iter__(self):
        ##return iter(self._items)

    ##def __reversed__(self):
        ##return reversed(self._items)

    ##def __repr__(self):
        ##return '%s(%r)' % (self.__class__.__name__, self._items)

    ##def __str__(self):
        ##return str(self._items)

    ##def __contains__(self, item):
        ##i = bisect.bisect_left(self._items, item)
        ##j = bisect.bisect_right(self._items, item)
        ##return item in self._items[i:j]

    ##def index(self, item):
        ##i = bisect.bisect_left(self._items, item)
        ##j = bisect.bisect_right(self._items, item)
        ##return self._items[i:j].index(item) + i

    ##def _add(self, item):
        ##if item is not None and item not in self:
            ##i = bisect.bisect_left(self._items, item)
            ##self._items.insert(i, item)

    ##def _remove(self, item):
        ##i = self.index(item)
        ##del self._items[i]




##def _expand(path):
    ##return os.path.expanduser(os.path.expandvars(path))



##class CallbackSet:
    ##"""
    ##Set of weak references to callbacks

    ##weakref.WeakSet does not work with bound methods.
    ##This class gets around that limitation.
    ##"""
    ##def __init__(self):
        ##self._listeners = set()


    ##def add(self, listener):
        ##if inspect.ismethod(listener):
            ##owner = listener.__self__
            ##listener = weakref.WeakMethod(listener)
            ##if listener not in self._listeners:
                ##weakref.finalize(owner, self._discard, listener)
        ##else:
            ##listener = weakref.ref(listener, self._discard)

        ##self._listeners.add(listener)


    ##def remove(self, listener):
        ##if inspect.ismethod(listener):
            ##listener = weakref.WeakMethod(listener)
        ##else:
            ##listener = weakref.ref(listener)

        ##self._listeners.remove(listener)


    ##def __iter__(self):
        ##return (listener() for listener in self._listeners
                ##if listener() is not None)


    ##def __len__(self):
        ##return len(self._listeners)


    ##def _discard(self, listener):
        ##try:
            ##self._listeners.remove(listener)
        ##except KeyError:
            ##pass







##class environment:
    ##"""
    ##Context manager that directs file operations to a model id of a Environment

    ##In some cases the environment's current model should be be the same
    ##when the context exits as it was when the context was entered.  In
    ##other situations, a change to the evironment's current model should be
    ##maintained after the context has exited.  Evaluating multiple models
    ##serves as an example of the former behavior, and training is an example
    ##of the latter.

    ###   Evaluating previously trained models:
    ###   We just want to evaluate the model, the environment's
    ###   state should be completely restored once we are done
    ##start_model = Environment('foo').current_model
    ##for model_id in range(10):
        ##with environment('foo', model_id):
            ##model = load_model('bar.h5')
            ##metrics[model_id] = calculate_some_metric(model)

    ##assert start_model == Environment('foo').current_model

    ###   Training a new model:
    ###   We want train a model in using a new model id and examine the
    ###   training log externally when the training is complete.  We need
    ###   the environment's current model to remain set to the newly created
    ###   id so that external tools (e.g. log reader) know which model was
    ###   just trained (i.e. the current one).
    ##with environment('foo', restore_model_id=False) as environ:
        ##new_model = environ.create_model()
        ##environ.current_model = new_model
        ##train_the_model_with_logging(model)
        ##save_model(model, 'bar.h5')

    ##assert new_model == Environment('foo').current_model

    ##By default the original current model id is restored when the context
    ##exits.  Setting the restore_model_id argument to False will
    ##maintain any changes to the environment's current model.

    ##Args:
        ##environ: Environment object or name,
            ##if None, the currently active environment is used
        ##model_id(int): the id of the current model
            ##if None, the environment's current model is not changed
        ##restore_model_id(bool): if True, change the current model back to
            ##the current model before entering the context, otherwise keep
            ##the environment's current model set to the value given to
            ##model_id.
    ##"""
    ##_stack = list()

    ##@classmethod
    ##def top(cls):
        ##"""
        ##The current context's environment object

        ##This is used by functions defined outside of this class to
        ##access the context's environment.  For example, a save_model
        ##function might consider its file path argument as being relative
        ##to the context's current model path (i.e. environment.top().model_path()).

        ##Returns:
            ##The Environment object used in the most recent instance
            ##of the context manager.
        ##"""
        ##try:
            ##return cls._stack[-1]
        ##except IndexError:
            ##return None


    ##def __init__(self, environ=None, model_id=None, restore_model_id=True):
        ##if environ is None or isinstance(environ, str):
            ##environ = Environment(environ)
        ##self._environ = environ
        ##self._model_id = model_id
        ##self._previous_model_id = None
        ##self._restore_model_id_on_exit = restore_model_id
        ##self._model_file_handlers = dict()


    ##@property
    ##def environ(self):
        ##return self._environ

    ##@property
    ##def model_id(self):
        ##return self._model_id


    ##def _update_model_file_logging_handlers(self):
        ###   redirect logging to the environment
        ##from . import logging as kt_logging
        ##for logger in logging.Logger.manager.loggerDict.values():
            ###   logger PlaceHolder objects don't have 'handler', ignore them
            ##with contextlib.suppress(AttributeError):
                ##for handler in logger.handlers:
                    ##if isinstance(handler, kt_logging.ModelFileHandler):
                        ##self._model_file_handlers[handler] = handler.environ
                        ##handler.environ = self.environ


    ##def _restore_model_file_logging_handlers(self):
        ##for handler, environ in self._model_file_handlers.items():
            ##handler.environ = environ


    ##def __enter__(self):
        ###   switch to the given model
        ##self._previous_model_id = self.environ.current_model
        ##if self.model_id is not None:
            ##environ.current_model = self.model_id

        ##self._update_model_file_logging_handlers()

        ##environment._stack.append(self.environ)

        ##return self.environ


    ##def __exit__(self, exception_type, exception_value, traceback):
        ##self._restore_model_file_logging_handlers()

        ##if self._restore_model_id_on_exit:
            ##self.environ.current_model = self._previous_model_id

        ##environment._stack.pop()









