import pathlib
import json
import contextlib
import collections
import types
import time
import weakref
import inspect

import watchdog.events
import watchdog.observers

from .synchronized import synchronized


__all__ = ['Configuration']


class ConfigAutoloader(watchdog.events.FileSystemEventHandler):
    def __init__(self, config):
        self.config = config
        self._ignore_count = 0

    def ignore_change(self):
        self._ignore_count += 1

    def on_modified(self, event):
        if event.src_path == str(self.config.config_filepath):
            if self._ignore_count == 0:
                self.config.load()
            else:
                self._ignore_count -= 1

    def on_moved(self, event):
        if event.src_path == self.config.config_filepath:
            self.config.config_filepath = event.dest_path


class PendingCallbacks:
    def __init__(self):
        self.callbacks = dict()

    def add(self, event, key, callback, *args):
        self.callbacks[(event, key)] = (callback, args)

    def clear(self):
        self.callbacks.clear()

    def run(self):
        for (event, key), (callback, args) in self.callbacks.items():
            callback(*args)


class CallbackSet:
    """
    Set of weak references to callbacks

    weakref.WeakSet does not work with bound methods.
    This class gets around that limitation.
    """
    def __init__(self):
        self._listeners = set()


    def add(self, listener):
        if inspect.ismethod(listener):
            owner = listener.__self__
            listener = weakref.WeakMethod(listener)
            if listener not in self._listeners:
                weakref.finalize(owner, self._discard, listener)
        else:
            listener = weakref.ref(listener, self._discard)

        self._listeners.add(listener)


    def remove(self, listener):
        if inspect.ismethod(listener):
            listener = weakref.WeakMethod(listener)
        else:
            listener = weakref.ref(listener)

        self._listeners.remove(listener)


    def __iter__(self):
        return (listener() for listener in self._listeners
                if listener() is not None)


    def __len__(self):
        return len(self._listeners)


    def _discard(self, listener):
        try:
            self._listeners.remove(listener)
        except KeyError:
            pass


class Configuration(collections.Mapping):
    """

    Set defaults:
        Do new/removed keys trigger callbacks


    def on_change(current, previous):
        print('current =', current, 'previous =', previous)

    def on_delete(value):
        print('value =', value)

    Case 1:
    config.defaults = {'abc': 123}
    config.add_callback('change', 'abc', on_change)

    #   prints: current = 246, previous = 123
    config['abc'] = 246

    Case 2:
    config.add_callback('change', 'abc', on_change)

    #   prints: current = 123, previous = None
    config.defaults = {'abc': 123}

    #   prints: current = 246, previous = 123
    config['abc'] = 246


    Case 2:
    config.add_callback('change', 'abc', on_change)

    #   prints: current = 246, previous = 123
    config['abc'] = 246

    config.defaults = {'abc': 123}

    #   prints: current = 123, previous = 246
    del config['abc']


    Case 3:
    config.defaults = {'abc': 123}
    config.add_callback('delete', 'abc', on_delete)
    config.add_callback('change', 'abc', on_change)

    #   prints: current = 246, previous = 123
    config['abc'] = 246

    #   prints: current = 123, previous = 246
    del config['abc']


    Case 4:
    config.defaults = {'abc': 123}
    config.add_callback('delete', 'abc', on_delete)
    config.add_callback('change', 'abc', on_change)

    #   raises KeyError - can't delete from defaults
    del config['abc']

    #   ?, could use proxy to run callback
    del config.defaults['abc']

    Case 3:
    config.add_callback('delete', 'abc', on_delete)
    config.add_callback('change', 'abc', on_change)

    #   prints: current = 246, previous = None
    config['abc'] = 246

    #   prints: value = 246
    del config['abc']


    Case 4:
    #   defaults == {'abc': 123}
    defaults = Configuration('defaults')

    config.defaults = defaults
    config.add_callback('delete', 'abc', on_delete)
    config.add_callback('change', 'abc', on_change)

    #   raises KeyError - can't delete from defaults
    del config['abc']

    #   prints: value = 123
    del defaults['abc']


    Case 4:
    #   defaults == {'abc': 123}
    defaults = Configuration('defaults')

    config.defaults = defaults
    config.add_callback('delete', 'abc', on_delete)
    config.add_callback('change', 'abc', on_change)

    #   prints: current = 246, previous = 123
    config['abc'] = 246

    #   nothing
    del defaults['abc']



    Case 4:
    #   defaults == {'abc': 123}
    defaults = Configuration('defaults')

    config.defaults = defaults
    config.add_callback('delete', 'abc', on_delete)
    config.add_callback('change', 'abc', on_change)

    #   prints: current = 246, previous = 123
    defaults['abc'] = 246


    """
    @synchronized
    def __init__(self, config_filepath, autosave=True, autoload=False):
        self._config_filepath = pathlib.Path(config_filepath)
        self._variables = dict()
        self._defaults = dict()
        self._children = list()

        self._change_callbacks = dict()
        self._change_callbacks_enabled = True
        self._delete_callbacks = dict()
        self._delete_callbacks_enabled = True
        self._pending_callbacks = PendingCallbacks()
        self._defer_callbacks = False

        self._autosave = autosave
        self._autoload = autoload
        if self._autoload:
            self._build_autoloader()
        else:
            self._file_watcher = None
            self._autoloader = None
            self._config_watch = None

        self.load()


    def __del__(self):
        if isinstance(self.defaults, Configuration):
            self.defaults._children.remove(self)


    def __str__(self):
        return 'variables:\n    {}\ndefaults:\n    {}'.format(self._variables,
                                                              self.defaults)

    @property
    def config_filepath(self):
        return self._config_filepath

    @property
    def variables(self):
        return types.MappingProxyType(self._variables)

    @property
    def defaults(self):
        return self._defaults

    @defaults.setter
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
                    self._delete_callback(key, old_defaults[key])

            #   added keys
            for key in new_keys - old_keys:
                if key not in self._variables:
                    self._change_callback(key, self._defaults[key], None)

            #   existing keys
            for key in old_keys & new_keys:
                if key not in self._variables:
                    previous = old_defaults[key]
                    current = self._defaults[key]
                    if current != previous:
                        self._change_callback(key, current, previous)


        if isinstance(self._defaults, Configuration):
            self._defaults._children.append(self)


    #   ------------------------------------------------------------------------
    #       Saving & Loading
    #   ------------------------------------------------------------------------
    @synchronized
    def save(self):
        #   ignore the next modification event because it is being
        #   triggered by this method and doesn't require a load
        if self.autoload:
            self._autoloader.ignore_change()

        with self.config_filepath.open('w') as file:
            json.dump(self._variables, file, indent=4)

        if self.autoload:
            time.sleep(0.005)

    @synchronized
    def load(self):
        try:
            with self.config_filepath.open('r') as file:
                new_variables = json.load(file)
        except json.JSONDecodeError:
            if self._variables:
                with self.config_filepath.with_suffix('.backup').open('w') as file:
                    json.dump(self._variables, file, indent=4)
            raise

        with self.callbacks_deferred():
            removed_keys = set(self._variables) - set(new_variables)
            for key in removed_keys:
                self._delete_key(key)

            for key, value in new_variables.items():
                self._set_value(key, value)


    @synchronized
    @property
    def autosave(self):
        return self._autosave

    @synchronized
    @autosave.setter
    def autosave(self, autosave):
        self._autosave = autosave


    @property
    def autoload(self):
        return self._autoload

    @autoload.setter
    def autoload(self, autoload):
        if self._autoload == autoload:
            return

        self._autoload = autoload

        if self._autoload:
            self._build_autoloader()
        else:
            self._file_watcher.stop()
            self._file_watcher.join()
            self._file_watcher = None
            self._autoloader = None
            self._config_watch = None


    def _build_autoloader(self):
        self._autoloader = ConfigAutoloader(self)

        self._file_watcher = watchdog.observers.Observer()
        self._config_watch = self._file_watcher.schedule(self._autoloader,
                                                         str(self.config_filepath.parent))
        self._file_watcher.start()




    @synchronized
    @contextlib.contextmanager
    def autosave_disabled(self):
        was_autosave = self.autosave
        self.autosave = False

        yield

        self.autosave = was_autosave


    @synchronized
    @contextlib.contextmanager
    def autoload_disabled(self):
        was_autoload = self.autoload
        if self.autoload:
            self._autoload = False
            self._file_watcher.remove_handler_for_watch(self._autoloader,
                                                        self._config_watch)
        yield

        if was_autoload:
            self._autoload = True
            self._file_watcher.add_handler_for_watch(self._autoloader,
                                                        self._config_watch)




    #   ------------------------------------------------------------------------
    #       Callbacks
    #   ------------------------------------------------------------------------
    @synchronized
    def add_callback(self, event, key, callback):
        if event == 'change':
            self._change_callbacks.setdefault(key, CallbackSet()).add(callback)
        elif event == 'delete':
            self._delete_callbacks.setdefault(key, CallbackSet()).add(callback)
        else:
            raise ValueError('unknown callback event: {}'.format(event))


    @synchronized
    def remove_callback(self, event, key, callback):
        if event == 'change':
            self._change_callbacks[key].remove(callback)
        elif event == 'delete':
            self._delete_callbacks[key].remove(callback)
        else:
            raise ValueError('unknown callback event: {}'.format(event))


    @synchronized
    def remove_all_callbacks(self, key, *events):
        events = self._normalize_callback_events(events)
        if 'change' in events:
            with contextlib.suppress(KeyError):
                del self._change_callbacks[key]
        if 'delete' in events:
            with contextlib.suppress(KeyError):
                del self._delete_callbacks[key]


    @synchronized
    def clear_callbacks(self, *events):
        events = self._normalize_callback_events(events)
        if 'change' in events:
            with contextlib.suppress(KeyError):
                self._change_callbacks.clear()
        if 'delete' in events:
            with contextlib.suppress(KeyError):
                self._delete_callbacks.clear()


    @synchronized
    def enable_callbacks(self, *events):
        events = self._normalize_callback_events(events)
        if 'change' in events:
            self._change_callbacks_enabled = True
        if 'delete' in events:
            self._delete_callbacks_enabled = True


    @synchronized
    def disable_callbacks(self, *events):
        events = self._normalize_callback_events(events)
        if 'change' in events:
            self._change_callbacks_enabled = False
        if 'delete' in events:
            self._delete_callbacks_enabled = False


    @synchronized
    def are_callbacks_enabled(self, *events):
        events = self._normalize_callback_events(events)
        enabled = True
        if 'change' in events:
            enabled = enabled and self._change_callbacks_enabled
        if 'delete' in events:
            enabled = enabled and self._delete_callbacks_enabled

        return enabled

    def _normalize_callback_events(self, events):
        if len(events) == 1 and not isinstance(events[0], str):
            events = events[0]
        if not events:
            events = ['change', 'delete']

        return events


    def _change_callback(self, key, current_value, previous_value, defer=False):
        assert current_value != previous_value
        if self._change_callbacks_enabled:
            for callback in self._change_callbacks.get(key, set()):
                if defer or self._defer_callbacks:
                    self._pending_callbacks.add('change', key, callback,
                                                current_value, previous_value)
                else:
                    callback(current_value, previous_value)

        for child_config in self._children:
            if key not in child_config._variables:
                child_config._change_callback(key, current_value, previous_value,
                                              self._defer_callbacks)


    def _delete_callback(self, key, value, defer=False):
        if self._delete_callbacks_enabled:
            for callback in self._delete_callbacks.get(key, set()):
                if defer or self._defer_callbacks:
                    self._pending_callbacks.add('delete', key, callback, value)
                else:
                    callback(value)

        for child_config in self._children:
            if key not in child_config._variables:
                child_config._delete_callback(key, value, self._defer_callbacks)




    @synchronized
    @contextlib.contextmanager
    def callbacks_disabled(self, *events):
        events = self._normalize_callback_events(events)

        enabled_callback_events = list()
        if self.are_callbacks_enabled('change'):
            enabled_callback_events.append('changed')
        if self.are_callbacks_enabled('delete'):
            enabled_callback_events.append('delete')

        self.disable_callbacks(events)

        yield

        self.enable_callbacks(enabled_callback_events)


    @synchronized
    @contextlib.contextmanager
    def callbacks_deferred(self):
        already_deferring = self._defer_callbacks
        if not already_deferring:
            self._defer_callbacks = True

        yield

        if not already_deferring:
            self._defer_callbacks = False
            try:
                self._run_pending_callbacks()
            finally:
                self._clear_pending_callbacks()


    def _run_pending_callbacks(self):
        self._pending_callbacks.run()

        for child_config in self._children:
            child_config._run_pending_callbacks()


    def _clear_pending_callbacks(self):
        self._pending_callbacks.clear()

        for child_config in self._children:
            child_config._clear_pending_callbacks()


    #   ------------------------------------------------------------------------
    #                           Map Interface
    #   ------------------------------------------------------------------------
    @synchronized
    def __getitem__(self, key):
        try:
            return self._variables.get(key, self.defaults[key])
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
        if self.defaults:
            return key in self._variables or key in self.defaults
        return key in self._variables

    @synchronized
    def __iter__(self):
        if self.defaults:
            return iter({**self.defaults, **self._variables})
        return iter(self._variables)

    @synchronized
    def __len__(self):
        if self.defaults:
            return len({**self.defaults, **self._variables})
        return len(self._variables)

    @synchronized
    def __eq__(self, other):
        if self.defaults:
            merged = {**self.defaults, **self._variables}
        else:
            merged = self._variables
        try:
            return other._variables == merged
        except AttributeError:
            return other == merged

    @synchronized
    def __ne__(self, other):
        return not self.__eq__(other)

    @synchronized
    def keys(self):
        if self.defaults:
            return {**self.defaults, **self._variables}.keys()
        return self._variables.keys()

    @synchronized
    def values(self):
        if self.defaults:
            return {**self.defaults, **self._variables}.values()
        return self._variables.values()

    @synchronized
    def items(self):
        if self.defaults:
            return {**self.defaults, **self._variables}.items()
        return self._variables.items()

    @synchronized
    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

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
        with self.callbacks_deferred():
            for key in list(self._variables.keys()):
                self._delete_key(key)

        self._change_callbacks.clear()
        self._delete_callbacks.clear()

        if self.autosave:
            self.save()


    #def _set_value(self, key, value):
        ##   returns True if the value has changed
        #previous_value = self._variables.get(key, None)
        #if previous_value == value:
            #return False
        #self._variables[key] = value
        #self._change_callback(key, value, previous_value)
        #return True


    def _set_value(self, key, value):
        #   returns True if the configuration file needs to be updated
        try:
            previous_value = self._variables[key]
            requires_save = (previous_value != value)
            run_callback = requires_save

        except KeyError:
            try:
                previous_value = self.defaults[key]
                requires_save = True
                run_callback = (previous_value != value)

            except KeyError:
                previous_value = None
                requires_save = True
                run_callback = True

        self._variables[key] = value
        if run_callback:
            self._change_callback(key, value, previous_value)

        return requires_save




    #def _delete_key(self, key):
        #value = self._variables.pop(key)
        #self._delete_callback(key, value)
        #self.remove_all_callbacks(key)

    def _delete_key(self, key):
        try:
            value = self._variables.pop(key)
            try:
                new_value = self.defaults[key]
            except KeyError:
                self._delete_callback(key, value)
                self._change_callbacks.pop(key, None)
            else:
                self._change_callback(key, new_value, value)

        except KeyError:
            if key not in self.defaults:
                self._change_callbacks.pop(key, None)
            raise

        finally:
            self._delete_callbacks.pop(key, None)


