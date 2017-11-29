import pathlib
import json
import contextlib
import collections
import types
import time
import weakref
import inspect
import warnings
import sys

import watchdog.events
import watchdog.observers

from .synchronized import synchronized
from . import callbacks


__all__ = ['Configuration',
           'NOT_SET',
           'AutoloaderError']


class NotSet:
    _singleton = None
    def __new__(cls):
        if NotSet._singleton is None:
            NotSet._singleton = object.__new__(cls)
        return NotSet._singleton

    def __str__(self):
        return 'NOT SET'

NOT_SET = NotSet()


class DeferredCallbacks:
    """
    An ordered dict of callbacks that are run as a single group
    """
    def __init__(self):
        self.values = dict()
        self.callbacks = collections.OrderedDict()


    def add(self, key, callback, current, previous):
        self.callbacks.setdefault(key, CallbackSet()).add(callback)
        self.callbacks.move_to_end(key)

        _, original_previous = self.values.get(key, (None, previous))
        self.values[key] = (current, original_previous)


    def clear(self):
        self.callbacks.clear()
        self.values.clear()


    def run(self):
        for key, callbacks in self.callbacks.items():
            current, previous = self.values[key]
            callbacks(current, previous)




class Configuration(collections.Mapping):
    """
    A collection of variables saved as a JSON object

    A Configuration maps strings to values that can be serialized as
    JSON objects.  Each key/value pair is referred to as a configuration
    variable and is stored in a variables dict.  In addition, every
    Configuration object has a defaults mapping that provides values to
    keys not set in the variables dict.



    # Creatation
    When a file name is given to the Configuration constructor, the
    variables dict is loaded using the standard library's json package.
    If the file name is not given, the configuration object will
    work as normal with the exception of the saving and loading operations.

    Example:

    Create a configuration file with two items.

        variables = {'yo': 420, 'bro': 240}
        with open('some/file') as file:
            json.dump(variables, file)

    Create a configuration object from that file with two default items,
    on of which has a key in common with the variables saved to the
    configuration file.

        config = Configuration('some/file')
        config.defaults = {'foo': 'bar', 'yo': 840}}

    The variables property is a read-only dict of items loaded from
    the configuration file.
        assert config.variables['yo'] == 420
        assert config.variables['bro'] == 240

        assert config.defaults['yo'] == 840
        assert config.defaults['foo'] == 'bar'


    #   Mapping Interface

    The mapping interface operates over the logical merge of
    the configuration's variables and its defaults.

        assert config == {**config.defaults, **config.variables}


    ## Getting values

    The configuration object has three items.  The variables loaded from
    the file take precedence over the defaults.

        assert config['yo'] == 420
        assert config['foo'] == 'bar'
        assert config['bro'] == 240


    ##  Setting values

    Setting a configuration item always modifies the configuration variables
    and never modifies the defaults.

        config['yo'] = 120

        assert config['yo'] == 120
        assert config.variables['yo'] == 120
        assert config.defaults['yo'] == 840


    ##  Deleting items

    Items are always removed from the variables and never from the defaults.
    This makes for a couple of semantic differences between Configuration
    objects and dict objects.  Firstly, just because a key is contained
    in a configuration does not mean that it can be deleted.  This occurs
    when the key is in the defaults but not in the variables.

        assert 'foo' in config

        #   raises a KeyError since 'foo' is not in config.variables
        del config['foo']

    Secondly, if a key exists in both the variables and the defaults,
    the configuration will still contain the key even after deleting it.

        del config['yo']

        assert 'yo' in config
        assert config['yo'] == 840


    To completely remove 'yo' from the configuration it needs to be
    removed from the defaults as well.

        del config.defaults['yo']

        assert 'yo' not in config


    # Callbacks

    Configuration objects provide a mechanism to notify an application
    when the configuration has been modified.  A set of callbacks
    is kept for each key.  Whenever an item is added, changed, deleted
    all callbacks registered with the item's key are called.  The
    callback takes two arguments, the first is the item's value after
    the modification and the second argument is the item's value before
    the modification.  When an item is added, the previous value is
    set to the special constant NOT_SET.  Likewise, when an item is
    deleted its current value is set to NOT_SET.

    Callbacks are always triggered whenever a change occurs, this includes
    when the configuration is loaded, when a new defaults mapping is
    assigned, when update() is called, and when clear() is called.  In
    each of these cases multiple changes are likely to occur and executing
    the callbacks is deferred until all changes are made.

    Callbacks can be globally disabled using the disable_callbacks() method
    and enabled with the enable_callbacks() method.  The callbacks_disabled()
    context manager provides a context where callbacks are disabled and then
    re-enabled if appropriate when the context manager exits.One situation
    where this is useful is when modifying a configuration from a callback
    would lead to infinite recursion.

    Example:

        config = Configuration()

        def on_bro_changed(current, previous):
            #   stop infinite recursion
            with config.callbacks_disabled():
                config['bro'] = max(current, 100)

        config.add_callback('bro', on_bro_changed)

        config['bro'] = 104

        assert config['bro'] == 100


    #   Saving & Loading

    ## Saving

    Calling the save() method writes the variables dict to the configuration
    file as a JSON formatted object.  The defaults are not saved to the file.

    If the autosave property is set to True, the configuration will be
    saved every time an item is modified or deleted.  This can be useful
    if it is important to maintain consistency between the configuration
    object and configuration file.  However, it can impose performance
    issues, particularly if the configuration is changed inside an inner
    loop.  The saved() context manager can be used to mitigate
    situations where performance is an issue.

        config = Configuration('some/file')
        config.autosave = True

        #   this gets saved immediately
        config['yo'] = 420

        #   temporarily disable autosave and save when context manager exits
        with saved(config, policy='exit'):
            for i in range(1000):
                config['yo'] = i


    ##  Loading

    Configurations are updated from the configuration file with the load()
    method.  The load() method will overwrite the contents of the variables
    dict.  It does not alter the defaults.

    If the autoload property is set to True, the configuration object
    will monitor the configuration file and automatically load the file
    when it detects changes made from outside of the configuration object.
    That is, calling save(), either explicitly or implicitlly via autosave,
    will not trigger an automatic load.  As with autosave, autoload is
    useful when consistency between the configuration object and file
    must be maintained.  Care must be taken because triggering an autoload
    is nondeterministic and loading will overwrite the configuration.


    # Configuration Chaining

    A configuration's defaults can be any type of mapping object.  But
    when defaults is a Configuration the Configuration semantics are applied
    recursively and a chain of configuration objects behaves like cascaded
    style sheets.  Moreover, when defaults is a general mapping type,
    modifications can not be detected and callbacks can not be run.  On the
    other hand, when defaults is a Configuration, changes are detected and
    appropriate callbacks are run.

    When the defaults is not a Configuration, changes to the defaults
    can not trigger callbacks.

        config = Configuration('some/file')

        def on_bro_changed(current, previous):
            print('bro changed: ', current, previous)

        config.defaults = {'yo': 840, 'bro', 240}
        config['yo'] = 420
        config.add_callback('bro', on_bro_changed)

        #   callback is not run
        config.defaults['bro'] = 640


    However, when defaults is a Configuration, changes to defaults
    are propagated and the callback is run.

        config.defaults = Configuration()

        #   now the callback is run
        config.defaults['bro'] = 640

    Output:
        bro changed: 640 NOT_SET


    Attributes:
        is_loaded(bool): True if the configuration was loaded from file
        filepath(pathlib.Path): the path to the configuration file
        variables(types.MappingProxyType): read-only view of configuration variables
        defaults(mapping): default values for unset variables
        autosave(bool): True if auto-saving is enabled
        autoload(bool): True if auto-loading is enabled

    Args:
        filepath(path-like): path to a configuration file
        autosave(bool): if True, enable auto-saving
        autoload(bool): if True, enable auto-loading
    """
    @synchronized
    def __init__(self, filepath=None, autosave=False, autoload=False):
        self._filepath = filepath
        self._variables = dict()
        self._defaults = dict()
        self._child_configs = list()

        self._change_callbacks = dict()
        self._change_callbacks_enabled = True
        self._deferred_callbacks = callbacks.DeferredCallbacks()
        self._defer_callbacks = False
        self._is_loaded = False

        self._autosave = autosave
        self._autoload = autoload
        if self._autoload:
            self._create_autoloader()
        else:
            self._autoloader = None

        if self._filepath is not None:
            self._filepath = pathlib.Path(filepath)
            self.load()


    @synchronized
    def __del__(self):
        if isinstance(self._defaults, Configuration):
            self._defaults._child_configs.remove(self)

        self._destroy_autoloader()


    @synchronized
    def __str__(self):
        return 'variables:\n    {}\ndefaults:\n    {}'.format(self._variables,
                                                              self._defaults)


    @property
    @synchronized
    def filepath(self):
        return self._filepath

    @filepath.setter
    @synchronized
    def filepath(self, filepath):
        filepath = pathlib.Path(str(filepath))
        if filepath != self.filepath:
            self._filepath = filepath

            if self.autoload:
                self._destroy_autoloader()

            if self._filepath is not None:
                if self.autoload:
                    self._create_autoloader()
                self.load()


    @property
    @synchronized
    def variables(self):
        return types.MappingProxyType(self._variables)

    @variables.setter
    @synchronized
    def variables(self, variables):
        if variables is self._variables:
            return

        with self.callbacks_deferred():
            removed_keys = set(self._variables) - set(variables)
            for key in removed_keys:
                self._delete_key(key)

            for key, value in variables.items():
                self._set_value(key, value)


    @property
    @synchronized
    def defaults(self):
        return self._defaults

    @defaults.setter
    @synchronized
    def defaults(self, defaults):
        if defaults is self._defaults:
            return

        old_keys = set(self._defaults)
        new_keys = set(defaults)

        old_defaults = self._defaults
        self._defaults = defaults

        with self.callbacks_deferred():
            #   removed keys
            for key in old_keys - new_keys:
                if key not in self._variables:
                    self._run_callbacks(key, NOT_SET, old_defaults[key])

            #   added keys
            for key in new_keys - old_keys:
                if key not in self._variables:
                    self._run_callbacks(key, self._defaults[key], NOT_SET)

            #   existing keys
            for key in old_keys & new_keys:
                if key not in self._variables:
                    previous = old_defaults[key]
                    current = self._defaults[key]
                    if current != previous:
                        self._run_callbacks(key, current, previous)


        if isinstance(self._defaults, Configuration):
            self._defaults._child_configs.append(self)


    #   ------------------------------------------------------------------------
    #       Saving & Loading
    #   ------------------------------------------------------------------------
    @synchronized
    def save(self):
        """Save to the configuration file"""
        #   ignore the next modification event because it is being
        #   triggered by this method and doesn't require a load
        if self._autoloader is not None:
            self._autoloader.ignore_change()

        with self.filepath.open('w') as file:
            json.dump(self._variables, file, indent=4, sort_keys=True)

        ##   give the file watcher thread a chance
        ##   to pick up the file system event
        #if self.autoload:
            #time.sleep(0.005)


    @synchronized
    def load(self):
        """Load from the configuration file"""
        self.variables = self._load_configuration_file()


    def _load_configuration_file(self):
        #   this function is called from load() and Autoloader.load()
        #   it allows Autoloader to handle errors occuring during
        #   loading & parsing to be handled separatley from
        #   errors occuring in the callbacks when the variables
        #   are copied to self.variables
        try:
            with self.filepath.open('r') as file:
                variables = json.load(file)
        except:
            self._is_loaded = False
            raise
        else:
            self._is_loaded = True

        return variables


    @synchronized
    def is_loaded(self):
        """Returns True if the configuration was successfully loaded from file"""
        return self._is_loaded

    @property
    @synchronized
    def autosave(self):
        return self._autosave

    @autosave.setter
    @synchronized
    def autosave(self, autosave):
        if self._autosave != autosave:
            self._autosave = autosave

            if self._autosave:
                self.save()


    @property
    def autoload(self):
        return self._autoload

    @autoload.setter
    def autoload(self, autoload):
        if self._autoload != autoload:
            self._autoload = autoload

            if self._autoload:
                self._create_autoloader()
            else:
                self._destroy_autoloader()


    def _create_autoloader(self):
        assert self.autoload
        assert self._autoloader is None

        self._autoloader = Autoloader(self)
        self._autoloader.start()


    def _destroy_autoloader(self):
        with contextlib.suppress(AttributeError):
            self._autoloader.stop()
        self._autoloader = None


    @synchronized
    @contextlib.contextmanager
    def autosave_disabled(self):
        """
        Context manager that temporarily disables autosaving

            with config.autosave_disabled():
                do_something_with_config()

        Is equivalent to

            autosave = config.autosave
            config.autoload = False
            do_something_with_config()
            config.autosave = autosave
        """
        was_autosave = self.autosave
        self.autosave = False

        yield

        self.autosave = was_autosave


    @synchronized
    @contextlib.contextmanager
    def autoload_disabled(self):
        """
        Context manager that temporarily disables autoloading

            with config.autoload_disabled():
                do_something_with_config()

        Is equivalent to

            autoload = config.autoload
            config.autoload = False
            do_something_with_config()
            config.autoload = autoload
        """
        was_autoload = self.autoload
        if self.autoload:
            self._autoload = False
            self._autoloader.disable()

        yield

        if was_autoload:
            #   give time for the file system events to occur before
            #   enabling autoloader
            time.sleep(0.005)

            self._autoload = True
            self._autoloader.enable()


    #   ------------------------------------------------------------------------
    #       Callbacks
    #   ------------------------------------------------------------------------
    @synchronized
    def add_callback(self, key, callback):
        """
        Add a callback to be run when an item is modified

        If the same callback is added more than once for a key,
        it is only called once when the item changes.  The order
        that callbacks are called is undefined.

        Args:
            key(str): the item's key
            callback(callable): a function taking two arguments
                the first argument is the item's value after being changed,
                the second argument is the item's value before being changed
        """
        self._change_callbacks.setdefault(key, callbacks.CallbackSet()).add(callback)


    @synchronized
    def remove_callback(self, key, callback):
        """
        Remove a callback that is run when changes are made to a specific item

        Args:
            key(str): the item's key
            callback(callable): the callback function

        Raises:
            KeyError
        """
        self._change_callbacks[key].remove(callback)


    @synchronized
    def remove_callbacks(self, key):
        """
        Remove all callbacks that are run when changes are made to a specific item

        Args:
            key(str): the item's key

        Raises:
            KeyError
        """
        del self._change_callbacks[key]


    @synchronized
    def clear_callbacks(self):
        """Remove all callbacks"""
        self._change_callbacks.clear()


    @synchronized
    def enable_callbacks(self):
        """Enable running callbacks when items are modified"""
        self._change_callbacks_enabled = True


    @synchronized
    def disable_callbacks(self):
        """Disable running callbacks when items are modified"""
        self._change_callbacks_enabled = False


    @synchronized
    def are_callbacks_enabled(self):
        """Returns True if callbacks are run when items are modified"""
        return self._change_callbacks_enabled


    def _run_callbacks(self, key, current_value, previous_value, defer=False):
        assert current_value != previous_value

        #   the defer argument is used to propagate self._defer_callbacks
        #   down through children configurations
        defer = defer or self._defer_callbacks

        if self._change_callbacks_enabled:
            for callback in self._change_callbacks.get(key, set()):
                if defer:
                    self._deferred_callbacks.add(key, callback,
                                                 current_value, previous_value)
                else:
                    callback(current_value, previous_value)

        for child_config in self._child_configs:
            if key not in child_config._variables:
                child_config._run_callbacks(key, current_value, previous_value, defer)


    @contextlib.contextmanager
    @synchronized
    def callbacks_disabled(self):
        """
        Context manager that disables callbacks

            with config.callbacks_disabled():
                some_code_that_changes_config()

        Is equivalent to

            config.disable_callbacks()
            some_code_that_changes_config()
            config.enable_callbacks()


        Callbacks will be enabled if enable_callbacks() is called
        within the context.
        """
        was_enabled = self.are_callbacks_enabled()
        self.disable_callbacks()

        yield

        if was_enabled:
            self.enable_callbacks()


    @contextlib.contextmanager
    @synchronized
    def callbacks_deferred(self):
        """
        Context manager that defers running callbacks until exiting

        Callbacks are not run within the context.  Instead, callbacks
        that would normally be run are collected and run when the
        context manager exits.  If an item is modified multiple times
        its associated callbacks are only run once.  The current value
        passed to the callback is the value when the context exits.
        The previous value passed to the callback is the value before
        entering the context manager.  In effect, a series of changes made
        within the context are seen as a single change by code listening
        for changes to the configuration.

        Example:

            config = Configuration()

            def print_change(current, previous):
                print('callback:', 'current =', current, 'previous =', previous)

            config.add_callback('foor', print_change)
            config['foo'] = 1

            print('before context')
            with config.callbacks_deferred():
                config['foo'] = 2
                print('changed foo to 2')
                config['foo'] = 3
                print('changed foo to 3')

            print('after context')

        Output:

            callback: current = 1, previous = NOT_SET
            before context
            changed foo to 2
            changed foo to 3
            callback: current = 3, previous = 1
            after context
        """
        already_deferring = self._defer_callbacks
        if not already_deferring:
            self._defer_callbacks = True

        yield

        if not already_deferring:
            self._defer_callbacks = False
            try:
                self._run_deferred_callbacks()
            finally:
                self._clear_deferred_callbacks()


    def _run_deferred_callbacks(self):
        self._deferred_callbacks.run()

        for child_config in self._child_configs:
            child_config._run_deferred_callbacks()


    def _clear_deferred_callbacks(self):
        self._deferred_callbacks.clear()

        for child_config in self._child_configs:
            child_config._clear_deferred_callbacks()


    #   ------------------------------------------------------------------------
    #                           Map Interface
    #   ------------------------------------------------------------------------
    @synchronized
    def __getitem__(self, key):
        try:
            return self._variables.get(key, self._defaults[key])
        except KeyError:
            try:
                return self._variables[key]
            except KeyError as error:
                raise error from None


    @synchronized
    def __setitem__(self, key, value):
        requires_save = self._set_value(key, value)
        if requires_save and self.autosave:
            self.save()


    @synchronized
    def __delitem__(self, key):
        self._delete_key(key)
        if self.autosave:
            self.save()


    @synchronized
    def __contains__(self, key):
        if self._defaults:
            return key in self._variables or key in self._defaults
        return key in self._variables


    @synchronized
    def __iter__(self):
        if self._defaults:
            return iter({**self._defaults, **self._variables})
        return iter(self._variables)


    @synchronized
    def __len__(self):
        if self._defaults:
            return len({**self._defaults, **self._variables})
        return len(self._variables)


    @synchronized
    def __eq__(self, other):
        if self._defaults:
            merged = {**self._defaults, **self._variables}
        else:
            merged = self._variables

        return other == merged


    @synchronized
    def __ne__(self, other):
        return not self.__eq__(other)


    @synchronized
    def keys(self):
        if self._defaults:
            return {**self._defaults, **self._variables}.keys()
        return self._variables.keys()


    @synchronized
    def values(self):
        if self._defaults:
            return {**self._defaults, **self._variables}.values()
        return self._variables.values()


    @synchronized
    def items(self):
        if self._defaults:
            return {**self._defaults, **self._variables}.items()
        return self._variables.items()


    @synchronized
    def get(self, key, default=None, volatile=False):
        try:
            value = self[key]
        except KeyError:
            value = default

        return value


    @synchronized
    def setdefault(self, key, default):
        try:
            value = self[key]
        except KeyError:
            self[key] = default
            value = default

        return value


    @synchronized
    def update(self, other, **kwds):
        other = {**other, **kwds}
        requires_save = False
        with self.callbacks_deferred():
            for key, value in other.items():
                requires_save = self._set_value(key, value) or requires_save

        if requires_save and self.autosave:
            self.save()


    @synchronized
    def clear(self):
        if self._variables:
            with self.callbacks_deferred():
                for key in list(self._variables.keys()):
                    self._delete_key(key)

            if self.autosave:
                self.save()


    def _set_value(self, key, value):
        #   returns True if the configuration file needs to be updated
        try:
            previous_value = self._variables[key]
            requires_save = (previous_value != value)
            run_callback = requires_save

        except KeyError:
            try:
                previous_value = self._defaults[key]
                requires_save = True
                run_callback = (previous_value != value)

            except KeyError:
                previous_value = NOT_SET
                requires_save = True
                run_callback = True

        self._variables[key] = value
        if run_callback:
            self._run_callbacks(key, value, previous_value)

        return requires_save



    def _delete_key(self, key):
        try:
            value = self._variables.pop(key)
            try:
                new_value = self._defaults[key]
            except KeyError:
                self._run_callbacks(key, NOT_SET, value)
                self._change_callbacks.pop(key, None)
            else:
                self._run_callbacks(key, new_value, value)

        except KeyError:
            if key not in self._defaults:
                self._change_callbacks.pop(key, None)
            raise





class saved:
    """
    Context manager that controls when a configuration is saved

    A save policy is provided that determines when the configuration's
    save() method is called.  The choices are:
        1.  'immediate' - the configuration is saved immediately after
            any change is made (this is equivalent to enabling autosave).
        2.  'exit' - the configuration is always saved when the context
            manager exits.
        3.  'exit_no_errors' - the configuration is saved when the context
            manager exits without an exception.
        4.  'manual' - the configuration is only saved by an explicit
            call to the configuration's save() method.  Autosave is disabled
            within the context.

    Args:
        configuration(Configuration): the configuration object
        policy(str): the policy used to save the configuration
    """
    POLICIES = {'immediate', 'exit', 'exit_no_errors', 'manual'}

    def __init__(self, configuration, policy='exit'):
        if policy not in saved.POLICIES:
            raise ValueError('unknown save policy: {}, '
                             'must be one of {}'.format(policy, saved.POLICIES))
        self.configuration = configuration
        self.save_policy = policy


    def should_save_on_exit(self, exception):
        return (self.save_policy == 'exit'
                or (self.save_policy == 'exit_no_errors' and exception is None))


    def __enter__(self):
        self._was_autosave = self.configuration.autosave
        self.configuration.autosave = (self.save_policy == 'immediate')


    def __exit__(self, exception_type, exception_value, traceback):
        self.configuration.autosave = self._was_autosave
        if self.should_save_on_exit(exception_type):
            self.configuration.save()





class AutoloaderError(RuntimeError):
    """An error occuring when starting or stopping an Autoloader"""


class Autoloader(watchdog.events.FileSystemEventHandler):
    def __init__(self, config):
        self.config = config
        self.clear_on_error = True
        self.backup_on_error = False
        self._ignore_count = 0
        self.ignore_exceptions = False

        self._file_watcher = watchdog.observers.Observer()
        self._config_watch = None


    def start(self):
        if self.is_running():
            raise AutoloaderError('autoloader is already running')
        else:
            self._file_watcher.start()
            self.enable()


    def stop(self):
        if self.is_running() and not sys.is_finalizing():
            self._file_watcher.stop()
            self._file_watcher.join()
            self._config_watch = None
        else:
            raise AutoloaderError('autoloader is not running')


    def is_running(self):
        return self._file_watcher.is_alive()


    def is_enabled(self):
        return self._config_watch is not None


    def enable(self):
        if not self.is_enabled():
            self._config_watch = self._file_watcher.schedule(self,
                                                             str(self.config.filepath.parent))

    def disable(self):
        if self.is_enabled():
            self._file_watcher.unschedule(self._config_watch)
            self._config_watch = None


    def ignore_change(self):
        with synchronized(self.config):
            self._ignore_count += 1


    def on_modified(self, event):
        #   synchronize access to self._ignore_count
        with synchronized(self.config):
            if event.src_path == str(self.config.filepath):
                if self._ignore_count == 0:
                    self.load()
                else:
                    self._ignore_count -= 1


    def on_moved(self, event):
        if event.src_path == self.config.filepath:
            self.config.filepath = event.dest_path


    def on_created(self, event):
        if event.src_path == self.config.filepath:
            self.load()


    def on_deleted(self, event):
        if event.src_path == self.config.filepath:
            self.load()


    def load(self):
        with synchronized(self.config):
            try:
                variables = self.config._load_configuration_file()

            except (FileNotFoundError, json.JSONDecodeError):
                if self.backup_on_error:
                    try:
                        self._backup()
                    except Exception:
                        warnings.warn('failed to backup configuration: '
                                        '\'{}\''.format(self.config.filepath))
                if self.clear_on_error:
                    self.config.clear()

            else:
                self.config.variables = variables


    def _backup(self):
        i = 0
        name = self.config.filepath.name + '.backup{}'.format(i)
        backup_path = self.config.filepath.with_name(name)
        while backup_path.exists():
            i += 1
            name = self.config.filepath.name + '.backup{}'.format(i)
            backup_path = self.config.filepath.with_name(name)

        with backup_path.open('w') as file:
            json.dump(self.config.variables, file, indent=4, sort_keys=True)


