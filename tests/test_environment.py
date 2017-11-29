
import pathlib
import random
import inspect
import types
import time
import itertools
import shutil
import collections

import pytest

import mle


WAIT_FOR_CALLBACK_DURATION = 1

#   ----------------------------------------------------------------------------
#                           Global Configuration
#   ----------------------------------------------------------------------------
def test_missing_global_configuration(tmpdir):
    root = tmpdir.mkdir('root')

    with pytest.raises(mle.ConfigurationNotFoundError):
        config = mle.global_configuration(str(root))


def test_empty_global_configuration(tmpdir):
    root = tmpdir.mkdir('root')

    config_file = root.join(mle.GLOBAL_CONFIG_FILENAME)
    with open(str(config_file), 'w') as file:
        file.write('{}')

    config = mle.global_configuration(str(root))
    assert config == mle.DEFAULT_CONFIGURATION


#   ----------------------------------------------------------------------------
#                           Environment Creation
#   ----------------------------------------------------------------------------
@pytest.fixture
def root_directory(tmpdir):
    root = tmpdir.mkdir('root')

    config_file = root.join(mle.GLOBAL_CONFIG_FILENAME)
    with open(str(config_file), 'w') as file:
        file.write('{}')

    yield root

    import gc
    gc.collect()




def test_create_environment(root_directory):
    #   create environment in existing directory
    environ_path = root_directory.join('project1')
    environ_path.mkdir()

    environ = mle.Environment.create(environ_path)

    assert environ.directory == environ_path
    assert environ.directory.exists()

    assert environ.filepath == environ_path.join(mle.LOCAL_CONFIG_FILENAME)
    assert environ.filepath.exists()

    assert {**environ} == mle.global_configuration(str(root_directory))

    assert len(environ.models) == 0


    #   create environment in non-existent directory
    environ_path = root_directory.join('project2')

    environ = mle.Environment.create(environ_path)

    assert environ.directory == environ_path
    assert environ.directory.exists()

    assert environ.filepath == environ_path.join(mle.LOCAL_CONFIG_FILENAME)
    assert environ.filepath.exists()

    assert {**environ} == mle.global_configuration(str(root_directory))

    assert len(environ.models) == 0



#   ----------------------------------------------------------------------------
#                           Environment Models
#   ----------------------------------------------------------------------------
@pytest.fixture
def empty_environ(root_directory):
    environ_path = root_directory.join('project')
    environ_path.mkdir()

    return mle.Environment.create(environ_path)


@pytest.fixture(params=list(itertools.product(['', 'some/models'], ['model', 'mymodel'])))
def environ(empty_environ, request):
    number_models = 10
    empty_environ['model.prefix'] = request.param[0]
    empty_environ['model.directory_name'] = request.param[1]

    for identifier in range(number_models):
        empty_environ.create_model()

    return empty_environ







#class TestOrderedSet:
    #@pytest.fixture(params=[(0, True, True),
                            #(10, True, True),
                            #(10, False, True),
                            #(10, True, False),
                            #(10, False, False)])
    #def items(self, request):
        #length, unique, sort = request.param

        #items = list(range(0, 2 * length, 2))
        #if not unique:
            #while list(set(items)) == items:
                #items = (items + items)
                #random.shuffle(items)
                #items = items[:length]
        #else:
            #random.shuffle(items)

        #if sort:
            #items = sorted(items)

        #return items


    #@pytest.fixture
    #def ordered_set(self, items):
        #return mle.OrderedSet(items)


    #def test_length(self, ordered_set, items):
        #items = sorted(set(items))
        #assert len(ordered_set) == len(items)
        #if items:
            #assert ordered_set
        #else:
            #assert not ordered_set


    #def test_equals(self, ordered_set, items):
        #items = sorted(set(items))
        #assert ordered_set == ordered_set
        #assert ordered_set == items


    #def test_not_equals(self, ordered_set, items):
        #if items:
            #items = sorted(set(items))
            #assert ordered_set != items[:-1]
            #items[0] = max(items) + 1
            #assert ordered_set != items


    #def test_iteration(self, ordered_set, items):
        #assert sorted(set(items)) == list(iter(ordered_set))


    #def test_reversed(self, ordered_set, items):
        #assert list(reversed(ordered_set)) == list(reversed(sorted(set(items))))
        #assert list(reversed(ordered_set)) == list(reversed(list(ordered_set)))


    #def test_contains(self, ordered_set, items):
        #for item in ordered_set:
            #assert item in ordered_set

        #for item in items:
            #assert item in ordered_set

        #assert self.new_back_item(items) not in ordered_set
        #assert self.new_front_item(items) not in ordered_set


    #def test_getitem(self, ordered_set, items):
        #items = sorted(set(items))
        #for index, item in enumerate(items):
            #assert ordered_set[index] == item


    #def test_index(self, ordered_set, items):
        #items = sorted(set(items))
        #for index, item in enumerate(items):
            #assert ordered_set.index(item) == index


    #def test_clear(self, ordered_set, items):
        #ordered_set.clear()
        #assert len(ordered_set) == 0
        #self.verify_constraints(ordered_set)


    #def test_copy(self, ordered_set, items):
        #copied = ordered_set.copy()
        #assert ordered_set == copied
        #assert ordered_set is not copied

        #self.verify_constraints(copied)


    #def test_add_to_front(self, ordered_set, items):
        #length = len(ordered_set)
        #item = self.new_front_item(items)
        #assert item not in ordered_set
        #if ordered_set:
            #assert item < ordered_set[0]

        #ordered_set.add(item)
        #self.verify_add(ordered_set, item, length + 1)
        #self.verify_constraints(ordered_set)


    #def test_add_to_back(self, ordered_set, items):
        #length = len(ordered_set)
        #item = self.new_back_item(items)
        #assert item not in ordered_set
        #if ordered_set:
            #assert item > ordered_set[-1]

        #ordered_set.add(item)
        #self.verify_add(ordered_set, item, length + 1)
        #self.verify_constraints(ordered_set)


    #def test_add_to_middle(self, ordered_set, items):
        #length = len(ordered_set)
        #item = self.new_middle_item(items)
        #assert item not in ordered_set
        #if ordered_set:
            #assert ordered_set[0] < item < ordered_set[-1]

        #ordered_set.add(item)
        #self.verify_add(ordered_set, item, length + 1)
        #self.verify_constraints(ordered_set)


    #def test_add_existing(self, ordered_set, items):
        #if items:
            #length = len(ordered_set)

            #item = items[0]
            #ordered_set.add(item)
            #self.verify_add(ordered_set, item, length)
            #self.verify_constraints(ordered_set)

            #item = items[len(items) // 2]
            #ordered_set.add(item)
            #self.verify_add(ordered_set, item, length)
            #self.verify_constraints(ordered_set)

            #item = items[-1]
            #ordered_set.add(item)
            #self.verify_add(ordered_set, item, length)
            #self.verify_constraints(ordered_set)


    #def test_remove_from_front(self, ordered_set, items):
        #if items:
            #length = len(ordered_set)
            #item = items[0]
            #ordered_set.discard(item)
            #self.verify_remove(ordered_set, item, length - 1)
            #self.verify_constraints(ordered_set)


    #def test_remove_from_back(self, ordered_set, items):
        #if items:
            #length = len(ordered_set)
            #item = items[-1]
            #ordered_set.discard(item)
            #self.verify_remove(ordered_set, item, length - 1)
            #self.verify_constraints(ordered_set)


    #def test_remove_from_middle(self, ordered_set, items):
        #if items:
            #length = len(ordered_set)
            #item = items[len(items) // 2]
            #ordered_set.discard(item)
            #self.verify_remove(ordered_set, item, length - 1)
            #self.verify_constraints(ordered_set)


    #def test_remove_non_existing(self, ordered_set, items):
        #length = len(ordered_set)
        #item = min(items) - 1 if items else 0
        #assert item not in ordered_set
        #with pytest.raises(ValueError):
            #ordered_set.discard(item)

        #self.verify_remove(ordered_set, item, length)
        #self.verify_constraints(ordered_set)


    #def verify_add(self, ordered_set, item, length):
        #assert item in ordered_set
        #assert len(ordered_set) == length


    #def verify_remove(self, ordered_set, item, length):
        #assert item not in ordered_set
        #assert len(ordered_set) == length

    #def new_front_item(self, items):
        #return min(items) - 1 if items else 0

    #def new_back_item(self, items):
        #return max(items) + 1 if items else 0

    #def new_middle_item(self, items):
        #if items:
            #item = items[len(items) // 4]

            #item = random.randrange(min(items) + 1, max(items))
            #while item in items:
                #item = random.randrange(min(items), max(items))

            #assert min(items) < item < max(items)
        #else:
            #item = 0

        #assert item not in items
        #return item


    #@staticmethod
    #def verify_constraints(ordered_set):
        #assert ordered_set == sorted(set(ordered_set))





class TestModelSet:
    @pytest.fixture
    def models(self, environ):
        return environ.models


    @pytest.fixture
    def identifiers(self, models):
        identifiers = list(models._identifiers)
        assert identifiers == sorted(set(identifiers))
        return identifiers


    def test_equals(self, models, identifiers):
        assert models == models
        assert models == identifiers
        assert models == self.create_models(models, identifiers)


    def test_iteration(self, models, identifiers):
        assert models == list(iter(models))


    def test_reversed(self, models, identifiers):
        assert list(reversed(models)) == list(reversed(list(models)))
        assert list(reversed(models)) == list(reversed(self.create_models(models, identifiers)))


    def test_contains(self, models, identifiers):
        for model in models:
            assert model in models

        for identifier in identifiers:
            assert self.create_model(models, identifier) in models
            assert identifier in models

        #new_front_identifier = min(identifiers) - 1
        #assert new_front_identifier not in models
        #assert self.create_model(models, new_front_identifier) not in models

        new_back_identifier = max(identifiers) + 1
        assert new_back_identifier not in models
        assert self.create_model(models, new_back_identifier) not in models


    def test_getitem(self, models, identifiers):
        for index, (model, identifier) in enumerate(zip(models, identifiers)):
            assert models[index] == self.create_model(models, identifier)


    def test_index(self, models, identifiers):
        for index, (model, identifier) in enumerate(zip(models, identifiers)):
            model = self.create_model(models, identifier)
            assert models.index(model) == index


    def test_copy(self, models):
        copied = models.copy()
        assert models == copied
        assert models is not copied

        for a, b in zip(models, copied):
            assert a is not b
            assert a == b


    def create_model(self, models, identifier):
        return mle.ModelEnvironment(models._environment, identifier)

    def create_models(self, models, identifiers):
        return [self.create_model(models, identifier) for identifier in identifiers]











#   ----------------------------------------------------------------------------
#                           Model Lifecycle
#   ----------------------------------------------------------------------------
class ModelLifecycleCallback:
    def __init__(self, expected_count, identifier):
        self.expected_count = expected_count
        self.identifier = identifier
        self.actual_count = 0

    def __call__(self, model):
        try:
            identifier = model.identifier
        except AttributeError:
            identifier = model
        if identifier == self.identifier:
            self.actual_count += 1

    @property
    def succeeded(self):
        return self.expected_count == self.actual_count

    @property
    def message(self):
        return ('identifier {}, expected count != actual count: '
               '{} = {}'.format(self.identifier, self.expected_count, self.actual_count))

    @classmethod
    def assert_called(cls, environ, models):
        if not isinstance(models, (mle.ModelSet, mle.OrderedSet, list, tuple)):
            models = [models]

        try:
            models = [model.identifier for model in models]
        except AttributeError:
            pass

        callbacks = ModelLifecycleCallbackList(cls.get_add_callback_method(environ))

        for model in models:
            callbacks.assert_called(model)

        for model in environ.models:
            if model.identifier not in models:
                callbacks.assert_not_called(model)

        return callbacks


class CreateCallback(ModelLifecycleCallback):
    @classmethod
    def get_add_callback_method(cls, environment):
        return environment.add_create_model_callback


class DiscardCallback(ModelLifecycleCallback):
    @classmethod
    def get_add_callback_method(cls, environment):
        return environment.add_discard_model_callback




class ModelLifecycleCallbackList:
    def __init__(self, add_callback_to_environment_method):
        self.callbacks = list()
        self.add_callback_to_environment = add_callback_to_environment_method


    def assert_called(self, model):
        try:
            identifier = model.identifier
        except AttributeError:
            identifier = model

        callback = ModelLifecycleCallback(1, identifier)
        self.add_callback_to_environment(callback)
        self.callbacks.append(callback)


    def assert_not_called(self, model):
        try:
            identifier = model.identifier
        except AttributeError:
            identifier = model

        callback = ModelLifecycleCallback(0, identifier)
        self.add_callback_to_environment(callback)
        self.callbacks.append(callback)


    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        time.sleep(WAIT_FOR_CALLBACK_DURATION)
        if exc_type is None:
            for callback in self.callbacks:
                try:
                    assert callback.succeeded
                except AssertionError:
                    raise AssertionError(callback.message) from None

    @classmethod
    def get_add_callback_method(cls, environment):
        raise NotImplementedError()




class ActiveChangeCallback:
    def __init__(self, count, current, previous):
        self.current = current
        self.previous = previous
        self.count = count
        self.actual_count = 0
        self.actual_current = -1
        self.actual_previous = -1


    def __call__(self, current, previous):
        self.actual_count += 1
        self.actual_current = current
        self.actual_previous = previous


    @property
    def called(self):
        if self.count == 0:
            return self.actual_count == self.count
        else:
            return (self.actual_count == self.count
                    and self.actual_current == self.current
                    and self.actual_previous == self.previous)


    @property
    def message(self):
        messages = list()
        if self.count != self.actual_count:
            messages.append('wrong count, expected != actual: '
                            '{} = {}'.format(self.count, self.actual_count))
        if self.count > 0:
            if self.current != self.actual_current:
                messages.append('wrong current, expected != actual: '
                                '{} != {}'.format(self.current, self.actual_current))
            if self.previous != self.actual_previous:
                messages.append('wrong previous, expected != actual: '
                                '{} != {}'.format(self.previous, self.actual_previous))

        return '\n'.join(messages)


    @classmethod
    def assert_called(cls, environ, current, previous):
        if current is not None:
            current = mle.ModelEnvironment(environ, current)

        if previous is not None:
            previous = mle.ModelEnvironment(environ, previous)

        callback = ActiveChangeCallback(1, current, previous)
        environ.add_active_model_change_callback(callback)

        return callback

    @classmethod
    def assert_not_called(cls, environ):
        callback = ActiveChangeCallback(0, None, None)
        environ.add_active_model_change_callback(callback)

        return callback


    def __enter__(self):
        pass


    def __exit__(self, exc_type, exc_value, traceback):
        time.sleep(WAIT_FOR_CALLBACK_DURATION)
        if exc_type is None:
            try:
                assert self.called
            except AssertionError:
                raise AssertionError(self.message) from None


#   ----------------------------------------------------------------------------
#                           Create Models
#   ----------------------------------------------------------------------------
def test_create_model(empty_environ):
    environ = empty_environ

    number_models = 10
    for identifier in range(number_models):
        with CreateCallback.assert_called(environ, identifier):
            model = environ.create_model()

        #   identifier
        assert model.identifier == identifier

        #   directory
        assert model.directory == (environ.directory
                                   / environ['model.prefix']
                                   / (environ['model.directory_name'] + str(identifier)))
        assert model.directory.exists()

        #   log_directory
        assert model.log_directory == model.directory / environ['model.log.directory']
        assert model.log_directory.exists()

        #   path
        assert model.path('some/file') == model.directory / 'some/file'
        assert model.path(pathlib.Path('some/file')) == model.directory / 'some/file'
        assert model.path(model.directory / 'some/file') == model.directory / 'some/file'

        with pytest.raises(ValueError):
            model.path('/some/file')

        with pytest.raises(ValueError):
            model.path('')

        with pytest.raises(ValueError):
            model.path(None)

        #   log_path
        assert model.log_path('some/file.log') == model.log_directory / 'some/file.log'
        assert model.log_path(pathlib.Path('some/file.log')) == model.log_directory / 'some/file.log'
        assert model.log_path(None) == model.log_directory / environ['model.log.default']

        with pytest.raises(ValueError):
            model.log_path('/some/file.log')

        with pytest.raises(ValueError):
            model.log_path('')

        #   summary_path
        assert model.summary_path == model.directory / environ['model.summary']
        assert not model.summary_path.exists()

        #   __str__
        assert str(model) == str(model.directory.relative_to(environ.directory))

        #   __eq__
        assert environ.model(model.identifier) == model
        assert environ.model(model.identifier) is not model

        #   __ne__
        if identifier > 0:
            assert environ.model(0) != model

    TestOrderedSet.verify_constraints(environ.models)
    assert environ.models == list(range(len(environ.models)))


#   ----------------------------------------------------------------------------
#                           Discard Models
#   ----------------------------------------------------------------------------
def test_discard_model(environ):
    identifiers = [model.identifier for model in environ.models]
    size = len(environ.models)

    #   discard via model environment object
    identifier = identifiers.pop()

    model = environ.model(identifier)

    with DiscardCallback.assert_called(environ, model):
        environ.discard_model(model)

    assert not model.directory.exists()
    assert not model.log_directory.exists()
    assert not model.summary_path.exists()

    TestOrderedSet.verify_constraints(environ.models)
    assert len(environ.models) == (size - 1)
    assert environ.models == identifiers

    #   discard via identifier
    identifier = identifiers.pop()

    with DiscardCallback.assert_called(environ, identifier):
        environ.discard_model(identifier)

    model = mle.ModelEnvironment(environ, identifier)

    assert not model.directory.exists()
    assert not model.log_directory.exists()
    assert not model.summary_path.exists()

    TestOrderedSet.verify_constraints(environ.models)
    assert len(environ.models) == (size - 2)
    assert environ.models == identifiers



def test_discard_all_models(environ):
    identifiers = [model.identifier for model in environ.models]

    for identifier in identifiers:
        model = mle.ModelEnvironment(environ, identifier)
        assert model.directory.exists()
        assert model.log_directory.exists()

    with DiscardCallback.assert_called(environ, environ.models):
        environ.discard_models(environ.models)

    for identifier in identifiers:
        model = mle.ModelEnvironment(environ, identifier)

        assert not model.directory.exists()
        assert not model.log_directory.exists()
        assert not model.summary_path.exists()

    assert len(environ.models) == 0
    TestOrderedSet.verify_constraints(environ.models)


def test_discard_models(environ):
    identifiers = [model.identifier for model in environ.models]

    for identifier in identifiers:
        model = mle.ModelEnvironment(environ, identifier)
        assert model.directory.exists()
        assert model.log_directory.exists()

    removed = identifiers.copy()
    random.shuffle(removed)
    removed = removed[:len(removed) // 2]

    with DiscardCallback.assert_called(environ, removed):
        environ.discard_models(removed)

    for identifier in identifiers:
        model = mle.ModelEnvironment(environ, identifier)

        if identifier in removed:
            assert not model.directory.exists()
            assert not model.log_directory.exists()
            assert not model.summary_path.exists()
        else:
            assert model.directory.exists()
            assert model.log_directory.exists()

    assert len(environ.models) == (len(identifiers) - len(removed))
    TestOrderedSet.verify_constraints(environ.models)


#   ----------------------------------------------------------------------------
#                           Activate Models
#   ----------------------------------------------------------------------------
def test_active_model(environ):
    active_path = (environ.directory
                   / environ['model.prefix']
                   / environ['model.active_name'])

    with pytest.raises(mle.ModelNotFoundError):
        _ = environ.active_model

    #   set active to existing model identifier
    with ActiveChangeCallback.assert_called(environ, current=0, previous=None):
        environ.active_model = 0

        assert environ.active_model.identifier == 0
        assert environ.active_model == environ.model(0)
        assert environ.active_model.directory == environ.model(0).directory

        assert active_path.is_symlink()
        assert active_path.exists()
        assert environ.model(0).directory.exists()
        assert active_path.samefile(environ.model(0).directory)

    #   set active to non-existent
    with ActiveChangeCallback.assert_not_called(environ):
        with pytest.raises(mle.ModelNotFoundError):
            environ.active_model = environ.models[-1].identifier + 1

        assert environ.active_model.identifier == 0
        assert environ.active_model == environ.model(0)
        assert environ.active_model.directory == environ.model(0).directory

        assert active_path.is_symlink()
        assert active_path.exists()
        assert environ.model(0).directory.exists()
        assert active_path.samefile(environ.model(0).directory)

    #   set active to existing model environment
    with ActiveChangeCallback.assert_called(environ, current=1, previous=0):
        environ.active_model = environ.model(1)

        assert environ.active_model.identifier == 1
        assert environ.active_model == environ.model(1)
        assert environ.active_model.directory == environ.model(1).directory

        assert active_path.is_symlink()
        assert active_path.exists()
        assert environ.model(1).directory.exists()
        assert active_path.samefile(environ.model(1).directory)

    #   set active to None
    with ActiveChangeCallback.assert_called(environ, current=None, previous=1):
        environ.active_model = None

        with pytest.raises(mle.ModelNotFoundError):
            _ = environ.active_model

        with pytest.raises(mle.ModelNotFoundError):
            _ = environ.model()

        assert not active_path.is_symlink()
        assert not active_path.exists()
        assert environ.model(1).directory.exists()

    #   discard active model
    environ.active_model = 0

    with ActiveChangeCallback.assert_called(environ, current=None, previous=0):
        environ.discard_model(0)

        with pytest.raises(mle.ModelNotFoundError):
            _ = environ.active_model

        with pytest.raises(mle.ModelNotFoundError):
            _ = environ.model()

        #assert not active_path.is_symlink()
        assert not active_path.exists()
        assert not mle.ModelEnvironment(environ, 0).directory.exists()

    #   discard mode with no active model
    with ActiveChangeCallback.assert_not_called(environ):
        environ.discard_model(1)

        with pytest.raises(mle.ModelNotFoundError):
            _ = environ.active_model

        with pytest.raises(mle.ModelNotFoundError):
            _ = environ.model()

        #assert not active_path.is_symlink()
        assert not active_path.exists()

    #   discard multiple models including the active model
    environ.active_model = 4

    with ActiveChangeCallback.assert_called(environ, current=None, previous=4):
        environ.discard_models([3, 4, 5])

        with pytest.raises(mle.ModelNotFoundError):
            _ = environ.active_model

        with pytest.raises(mle.ModelNotFoundError):
            _ = environ.model()

        #assert not active_path.is_symlink()
        assert not active_path.exists()
        assert not mle.ModelEnvironment(environ, 0).directory.exists()







#   ----------------------------------------------------------------------------
#                       File System Monitoring
#   ----------------------------------------------------------------------------
class TestFileSystemMonitoring:
    def pick_models(self, environ, count):
        identifiers = [model.identifier for model in environ.models]

        random.shuffle(identifiers)
        models, remaining = identifiers[:count], identifiers[count:]

        models = [environ.model(identifier) for identifier in models]
        remaining = [environ.model(identifier) for identifier in remaining]

        assert all(model.directory.exists() for model in models)

        return models, sorted(remaining)


    def pick_model(self, environ):
        models, remaining = self.pick_models(environ, 1)
        return models[0], remaining


    def nonexistant_model(self, environ):
        model = mle.ModelEnvironment(environ, 1 + environ.models[-1].identifier)
        assert not model.directory.exists()
        return model


    def test_rename_model_in_environ_path(self, environ):
        src_model, remaining = self.pick_model(environ)
        dest_path = environ.directory / 'new_model_directory'

        with DiscardCallback.assert_called(environ, src_model):
            src_model.directory.rename(dest_path)

        assert environ.models == remaining


    def test_rename_model_in_models_prefix(self, environ):
        src_model, remaining = self.pick_model(environ)
        dest_path = src_model.directory.parent / 'new_model_directory'

        with DiscardCallback.assert_called(environ, src_model):
            src_model.directory.rename(dest_path)

        assert environ.models == remaining


    def test_move_model(self, environ):
        src_model, remaining = self.pick_model(environ)
        dest_model = self.nonexistant_model(environ)

        with CreateCallback.assert_called(environ, dest_model), \
             DiscardCallback.assert_called(environ, src_model):
            src_model.directory.rename(dest_model.directory)

        assert environ.models == remaining + [dest_model.identifier]


    def test_create_model(self, environ):
        #   let initial creation callbacks run
        time.sleep(WAIT_FOR_CALLBACK_DURATION)
        model = self.nonexistant_model(environ)

        with CreateCallback.assert_called(environ, model):
            with mle.synchronized(environ._models_manager):
                model.directory.mkdir(parents=True, exist_ok=True)
                mle.create_configuration(model.filepath)

        assert model in environ.models


    def test_discard_model(self, environ):
        model, remaining = self.pick_model(environ)
        with DiscardCallback.assert_called(environ, model):
            with mle.synchronized(environ._models_manager):
                shutil.rmtree(str(model.directory))

        assert environ.models == remaining


    def test_discard_all_models(self, environ):
        with DiscardCallback.assert_called(environ, environ.models):
            with mle.synchronized(environ._models_manager):
                for model in environ.models:
                    shutil.rmtree(str(model.directory))

        assert len(environ.models) == 0


    def test_discard_models(self, environ):
        models, remaining = self.pick_models(environ, len(environ.models) // 2)

        with DiscardCallback.assert_called(environ, models):
            with mle.synchronized(environ._models_manager):
                for model in models:
                    shutil.rmtree(str(model.directory))

        assert environ.models == remaining





















