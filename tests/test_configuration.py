



import json
import time
import itertools
import string
import random
import contextlib

import pytest

import mle



class Callback:
    def __init__(self):
        self.called = False
        self.frameinfo = None

    def __call__(self, *args, **kwds):
        self.called = True
        try:
            self.call(*args, **kwds)
        except AssertionError as error:
            raise AssertionError(self._message(self.frameinfo)) from error

    def call(self):
        raise NotImplementedError()

    def _message(self, frameinfo):
        frameinfo = frameinfo._asdict()
        frameinfo['code_context'] = '\n'.join(frameinfo['code_context'])
        message = 'incorrect callback argument \norigin: {filename}:{lineno}\n{code_context}'
        return message.format(**frameinfo)




class ChangeCallback(Callback):
    def __init__(self, current, previous):
        super().__init__()
        self.current = current
        self.previous = previous

    def call(self, current, previous):
        assert current == self.current
        assert previous == self.previous


class DeleteCallback(Callback):
    def __init__(self, value):
        super().__init__()
        self.value = value

    def call(self, value):
        assert value == self.value





import inspect
class CallbackChecker:
    def __init__(self):
        self.callbacks = list()
        self.expected = list()
        self.unexpected = list()


    def assert_called(self, config, event, key, **kwds):
        previous_frame = inspect.currentframe().f_back
        frameinfo = inspect.getframeinfo(previous_frame)

        self.callbacks.append((config, event, key, kwds, frameinfo, True))


    def assert_not_called(self, config, event, key, **kwds):
        previous_frame = inspect.currentframe().f_back
        frameinfo = inspect.getframeinfo(previous_frame)

        self.callbacks.append((config, event, key, kwds, frameinfo, False))


    def __enter__(self):
        for config, event, key, kwds, frameinfo, expected in self.callbacks:
            if event == 'change':
                kwds.setdefault('current', None)
                kwds.setdefault('previous', config.get(key))
                callback = ChangeCallback(**kwds)
            elif event == 'delete':
                kwds.setdefault('value', config.get(key))
                callback = DeleteCallback(**kwds)
            else:
                raise ValueError('unknown event: {}'.format(event))

            callback.frameinfo = frameinfo
            config.add_callback(event, key, callback)
            expected = expected and config.are_callbacks_enabled(event)
            if expected:
                self.expected.append((callback, frameinfo))
            else:
                self.unexpected.append((callback, frameinfo))


    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            for callback, frameinfo in self.expected:
                try:
                    assert callback.called
                except AssertionError:
                    raise AssertionError(self._message(frameinfo, True)) from None

            for callback, frameinfo in self.unexpected:
                try:
                    assert not callback.called
                except AssertionError:
                    raise AssertionError(self._message(frameinfo, False)) from None


    def _message(self, frameinfo, expected):
        frameinfo = frameinfo._asdict()
        frameinfo['code_context'] = '\n'.join(frameinfo['code_context'])
        message = 'callback was {} called \norigin: {filename}:{lineno}\n{code_context}'
        return message.format('not' if expected else 'incorrectly', **frameinfo)




def get_keys(is_in=(), not_in=(), count=1):
    if not isinstance(is_in, (list, tuple)):
        is_in = [is_in]
    if not isinstance(not_in, (list, tuple)):
        not_in = [not_in]

    if is_in:
        is_in_keys = set.intersection(*[set(mapping) for mapping in is_in])
    else:
        is_in_keys = set()
    not_in_keys = set().union(*[set(mapping) for mapping in not_in])

    keys = set()
    if is_in_keys:
        while len(keys) < count:
            key = is_in_keys.pop()
            while key in not_in_keys:
                key = is_in_keys.pop()
            keys.add(key)
    else:
        key = 'a'
        while len(keys) < count:
            key = generate_key_not_in(not_in_keys | keys, initial=key)
            keys.add(key)

    for mapping in is_in:
        assert key in mapping
    for mapping in not_in:
        assert key not in mapping

    return keys



def get_key(is_in=(), not_in=()):
    return get_keys(is_in, not_in).pop()


def compare_keys(mapping1, mapping2):
    assert list(sorted(mapping1.keys())) == list(sorted(mapping2.keys()))

def compare_values(mapping1, mapping2):
    values1 = list(mapping1.values())
    values2 = list(mapping2.values())

    assert len(values1) == len(values2)

    values1 = set(values1)
    values2 = set(values2)

    for item in values1:
        assert item in values2

    for item in values2:
        assert item in values1

def compare_items(mapping1, mapping2):
    items1 = list(mapping1.items())
    items2 = list(mapping2.items())

    assert len(items1) == len(items2)

    for item1, item2 in zip(items1, items2):
        assert item1 in items2
        assert item2 in items1


def verify_iteration(mapping):
    assert sorted(list(iter(mapping))) == list(sorted(mapping.keys()))





def generate_key_not_in(mapping, *, initial='a'):
    key = initial
    while key in mapping:
        key += initial
    return key


@pytest.fixture(params=[dict(callbacks_enabled=True),
                        dict(callbacks_enabled=False)])
def configuration(tmpdir, request):
    data1 = {'a': 1,
             'b': 2,
             'c': 3,
             'd': 4,
             'e': 5}

    data2 = {'a': 6,
             'b': 7,
             'c': 8,
             'f': 9,
             'g': 10}

    path = tmpdir.mkdir('path')

    config_file = path.join('config')
    with open(str(config_file), 'w') as file:
        json.dump(data1, file)

    config = mle.Configuration(str(config_file))

    if request.param['callbacks_enabled']:
        config.enable_callbacks()
    else:
        config.disable_callbacks()

    return config, data1, data2







@pytest.fixture
def configuration_with_defaults(tmpdir):
    data1 = {'a': 1,
             'b': 2,
             'c': 3,
             'd': 4,
             'e': 5}

    data2 = {'a': 6,
             'b': 7,
             'c': 8,
             'd': 9,
             'f': 10}

    defaults = {'x': 1,
                'y': 2,
                'z': 3}

    path = tmpdir.mkdir('path')

    config_file = path.join('config')
    with open(str(config_file), 'w') as file:
        json.dump(data1, file)

    config = mle.Configuration(str(config_file))

    config.defaults = defaults

    return config, data1, data2, defaults



def get_test_keys(data1, data2):
    keys1 = set(data1)
    keys2 = set(data2)

    #   make sure that existing key maps to unequal values
    existing_keys = keys1 & keys2
    existing_key = existing_keys.pop()
    while data1[existing_key] == data2[existing_key]:
        existing_key = existing_keys.pop()

    added_key = (keys2 - keys1).pop()
    removed_key = (keys1 - keys2).pop()

    return existing_key, added_key, removed_key


class TestConfiguration:
    def test_empty_configuration(self, tmpdir):
        path = tmpdir.mkdir('path')

        config_file = str(path.join('config'))
        with open(config_file, 'w') as file:
            file.write('{}\n')

        config = mle.Configuration(config_file)

        assert not config
        assert len(config) == 0
        assert len(list(config.keys())) == 0
        assert len(list(config.values())) == 0
        assert len(list(config.items())) == 0
        assert config == dict()
        assert config != {'a': 1}


    def test_blank_configuration(self, tmpdir):
        path = tmpdir.mkdir('path')

        config_file = str(path.join('config'))
        with open(config_file, 'w') as file:
            file.write('')

        with pytest.raises(json.JSONDecodeError):
            config = mle.Configuration(config_file)


    def test_missing_configuration(self, tmpdir):
        path = tmpdir.mkdir('path')
        config_file = str(path.join('config'))

        with pytest.raises(FileNotFoundError):
            config = mle.Configuration(config_file)


    def test_callbacks_enabled(self, configuration):
        config, data1, data2 = configuration

        config.enable_callbacks()
        assert config.are_callbacks_enabled('change')
        assert config.are_callbacks_enabled('delete')
        assert config.are_callbacks_enabled()

        config.disable_callbacks()
        assert not config.are_callbacks_enabled('change')
        assert not config.are_callbacks_enabled('delete')
        assert not config.are_callbacks_enabled()

        config.enable_callbacks('change', 'delete')
        assert config.are_callbacks_enabled('delete')
        assert config.are_callbacks_enabled('change')
        assert config.are_callbacks_enabled()

        config.disable_callbacks('change', 'delete')
        assert not config.are_callbacks_enabled('change')
        assert not config.are_callbacks_enabled('delete')
        assert not config.are_callbacks_enabled()

        config.enable_callbacks(['change', 'delete'])
        assert config.are_callbacks_enabled('delete')
        assert config.are_callbacks_enabled('change')
        assert config.are_callbacks_enabled()

        config.disable_callbacks(['change', 'delete'])
        assert not config.are_callbacks_enabled('change')
        assert not config.are_callbacks_enabled('delete')
        assert not config.are_callbacks_enabled()

        config.enable_callbacks('change')
        config.enable_callbacks('delete')
        assert config.are_callbacks_enabled('delete')
        assert config.are_callbacks_enabled('change')
        assert config.are_callbacks_enabled()

        config.disable_callbacks('change')
        config.disable_callbacks('delete')
        assert not config.are_callbacks_enabled('change')
        assert not config.are_callbacks_enabled('delete')
        assert not config.are_callbacks_enabled()

        config.enable_callbacks('change')
        assert config.are_callbacks_enabled('change')
        assert not config.are_callbacks_enabled()
        config.disable_callbacks('change')
        assert not config.are_callbacks_enabled('change')
        assert not config.are_callbacks_enabled()

        config.enable_callbacks('delete')
        assert config.are_callbacks_enabled('delete')
        assert not config.are_callbacks_enabled()
        config.disable_callbacks('delete')
        assert not config.are_callbacks_enabled('delete')
        assert not config.are_callbacks_enabled()


    def test_contains(self, configuration):
        config, data1, data2 = configuration
        for key in data1.keys():
            assert key in config

        for key in set(data2) - set(data1):
            assert key not in config


    def test_length(self, configuration):
        config, data1, data2 = configuration
        len(config) == len(data1)


    def test_equality(self, configuration):
        config, data1, data2 = configuration
        assert data1 == config
        assert data2 != config


    def test_keys(self, configuration):
        config, data1, data2 = configuration
        compare_keys(config, data1)


    def test_values(self, configuration):
        config, data1, data2 = configuration
        compare_values(config, data1)


    def test_items(self, configuration):
        config, data1, data2 = configuration
        compare_items(config, data1)


    def test_iteration(self, configuration):
        config, data1, data2 = configuration
        verify_iteration(config)



    def test_get(self, configuration):
        config, data1, data2 = configuration
        for key in data1.keys():
            assert config[key] == data1[key]
            assert config.get(key) == data1[key]

        key = generate_key_not_in(data1)

        with pytest.raises(KeyError):
            value = config[key]

        assert config.get(key) is None
        assert config.get(key, 4) == 4



    def test_set(self, configuration):
        config, data1, data2 = configuration
        existing_key, new_key, removed_key = get_test_keys(data1, data2)

        callbacks = CallbackChecker()
        callbacks.assert_called(config, 'change', existing_key, current=data2[existing_key])
        callbacks.assert_called(config, 'change', new_key, current=data2[new_key])

        with callbacks:
            for key, value in data2.items():
                config[key] = value
                assert config[key] == value



    def test_setdefault(self, configuration):
        config, data1, data2 = configuration
        existing_key, new_key, removed_key = get_test_keys(data1, data2)

        value = config.setdefault(existing_key, 8)
        assert value == config[existing_key]

        value = config.setdefault(new_key, 4)
        assert value == 4
        assert config[new_key] == 4


    def test_update(self, configuration):
        config, data1, data2 = configuration
        existing_key, new_key, removed_key = get_test_keys(data1, data2)

        callbacks = CallbackChecker()
        callbacks.assert_called(config, 'change', existing_key, current=data2[existing_key])
        callbacks.assert_called(config, 'change', new_key, current=data2[new_key])

        #   simple update
        with callbacks:
            config.update(data2)

        assert config == {**config, **data2}

        #   update with new keyword argument
        callbacks = CallbackChecker()
        callbacks.assert_not_called(config, 'change', existing_key, current=data2[existing_key])
        callbacks.assert_not_called(config, 'change', new_key, current=data2[new_key])

        with callbacks:
            config.update(data2, extra_key=4)

        assert config == {**config, **data2, **{'extra_key': 4}}

        #   update with existing keyword argument
        callbacks = CallbackChecker()
        callbacks.assert_called(config, 'change', existing_key, current='new_existing_value')
        callbacks.assert_not_called(config, 'change', new_key, current=data2[new_key])

        with callbacks:
            config.update(data2, **{existing_key: 'new_existing_value'})

        assert config[existing_key] == 'new_existing_value'



    def test_delete(self, configuration):
        config, data1, data2 = configuration
        existing_key, new_key, removed_key = get_test_keys(data1, data2)

        #   delete an existing key
        assert existing_key in config

        callbacks = CallbackChecker()
        callbacks.assert_called(config, 'delete', existing_key, value=data1[existing_key])
        callbacks.assert_not_called(config, 'change', existing_key)

        with callbacks:
            del config[existing_key]

        assert existing_key not in config

        #   delete item not in config
        assert new_key not in config

        callbacks = CallbackChecker()
        callbacks.assert_not_called(config, 'delete', existing_key, value=data1[existing_key])
        callbacks.assert_not_called(config, 'change', existing_key)

        with callbacks:
            with pytest.raises(KeyError):
                del config[new_key]




    def test_clear(self, configuration):
        config, data1, data2 = configuration
        existing_key, new_key, removed_key = get_test_keys(data1, data2)

        callbacks = CallbackChecker()
        callbacks.assert_called(config, 'delete', existing_key, value=data1[existing_key])
        callbacks.assert_not_called(config, 'change', existing_key)

        with callbacks:
            config.clear()

        assert len(config) == 0
        assert not config._delete_callbacks
        assert not config._change_callbacks



    def test_load(self, configuration):
        config, data1, data2 = configuration
        existing_key, new_key, removed_key = get_test_keys(data1, data2)

        config.autosave = False

        config.clear()
        config.update(data2)
        assert config == data2

        config.save()
        config.clear()
        assert config != data2

        callbacks = CallbackChecker()
        callbacks.assert_called(config, 'change', existing_key, current=data2[existing_key])

        with callbacks:
            config.load()

        assert config == data2


    def test_autoload(self, configuration):
        config, data1, data2 = configuration
        existing_key, new_key, deleted_key = get_test_keys(data1, data2)

        config.autoload = True
        config.autosave = False

        config.clear()
        config.update(data2)
        assert config == data2

        config.save()
        config.clear()
        config.update(data1)
        assert config != data2
        assert config == data1

        callbacks = CallbackChecker()
        callbacks.assert_called(config, 'change', existing_key, current=data2[existing_key])
        callbacks.assert_called(config, 'change', new_key, current=data2[new_key])
        callbacks.assert_called(config, 'delete', deleted_key, value=data1[deleted_key])

        with callbacks:
            with open(str(config.config_filepath), 'w') as file:
                json.dump(data2, file)

            time.sleep(1)

        assert config == data2









@pytest.fixture
def hierarchical_configuration(tmpdir):
    data1 = {'a': 1,
             'b': 2,
             'c': 3,
             'p': 4,
             'q': 5,
             'r': 6}

    data2 = {'p': 7,
             'q': 8,
             'r': 9,
             'x': 10,
             'y': 11,
             'z': 12}

    path = tmpdir.mkdir('path')

    config_file = path.join('config1')
    with open(str(config_file), 'w') as file:
        json.dump(data1, file)

    config1 = mle.Configuration(str(config_file))


    config_file = path.join('config2')
    with open(str(config_file), 'w') as file:
        json.dump(data2, file)

    config2 = mle.Configuration(str(config_file))

    config2.defaults = config1

    return config1, config2


@pytest.fixture
def config1(hierarchical_configuration):
    parent, child = hierarchical_configuration
    return parent

@pytest.fixture
def config2(hierarchical_configuration):
    parent, child = hierarchical_configuration
    return child

@pytest.fixture
def unique_value(config1, config2):
    return 1 + max(set(config1.values()) | set(config2.values()))


@pytest.fixture
def unique_values(config1, config2):
    max_value = max(set(config1.values()) | set(config2.values()))
    return [1 + max_value, 2 + max_value, 3 + max_value]










class TestConfigurationHierarchy:
    def test_contains(self, config1, config2):
        for key in config1:
            assert key in config2


    def test_length(self, config1, config2):
        assert len(config2) == len({**config1, **config2.variables})


    def test_equality(self, config1, config2):
        assert config2 == {**config1, **config2.variables}
        assert config2 != config2.variables


    def test_keys(self, config1, config2):
        compare_keys(config2, {**config1, **config2.variables})


    def test_values(self, config1, config2):
        compare_values(config2, {**config1, **config2.variables})


    def test_items(self, config1, config2):
        compare_items(config2, {**config1, **config2.variables})


    def test_iteration(self, config1, config2):
        verify_iteration(config2)


    def test_get(self, config1, config2):
        for key in config2:
            if key in config2.variables:
                assert config2[key] == config2.variables[key]
            else:
                assert config2[key] == config1[key]
                assert config2.get(key) == config1[key]

        key = generate_key_not_in(config2)

        with pytest.raises(KeyError):
            value = config2[key]

        assert config2.get(key) is None
        assert config2.get(key, 4) == 4


    #   ------------------------------------------------------------------------
    #                           Child Set
    #   ------------------------------------------------------------------------
    def test_child_set1(self, config1, config2, unique_value):
        #   key in config2 and key in config1
        key = get_key(is_in=[config1.variables, config2.variables])
        self.verify_child_set(config1, config2, key, unique_value)


    def test_child_set2(self, config1, config2, unique_value):
        #   key in config2 and key not in config1
        key = get_key(is_in=config2.variables, not_in=config1.variables)
        self.verify_child_set(config1, config2, key, unique_value)


    def test_child_set3(self, config1, config2, unique_value):
        #   key not in config2 and key in config1
        key = get_key(is_in=config1.variables, not_in=config2.variables)
        self.verify_child_set(config1, config2, key, unique_value)


    def test_child_set4(self, config1, config2, unique_value):
        #   key not in config2 and key not in config1
        key = get_key(not_in=[config1.variables, config2.variables])
        self.verify_child_set(config1, config2, key, unique_value)


    def verify_child_set(self, config1, config2, key, value):
        key_in_config1 = key in config1.variables

        callbacks = CallbackChecker()
        callbacks.assert_called(config2, 'change', key, current=value)
        callbacks.assert_not_called(config1, 'change', key)

        with callbacks:
            config2[key] = value

        assert config2[key] == value
        assert config2.variables[key] == value
        if key_in_config1:
            assert config1[key] != value
        else:
            assert key not in config1


    #   ------------------------------------------------------------------------
    #                           Parent Set
    #   ------------------------------------------------------------------------
    def test_parent_set1(self, config1, config2, unique_value):
        #   key in config2 and key in config1
        key = get_key(is_in=[config1.variables, config2.variables])
        self.verify_parent_set(config1, config2, key, unique_value)


    def test_parent_set2(self, config1, config2, unique_value):
        #   key in config2 and key not in config1
        key = get_key(is_in=config2.variables, not_in=config1.variables)
        self.verify_parent_set(config1, config2, key, unique_value)


    def test_parent_set3(self, config1, config2, unique_value):
        #   key not in config2 and key in config1
        key = get_key(is_in=config1.variables, not_in=config2.variables)
        self.verify_parent_set(config1, config2, key, unique_value)


    def test_parent_set4(self, config1, config2, unique_value):
        #   key not in config2 and key not in config1
        key = get_key(not_in=[config1.variables, config2.variables])
        self.verify_parent_set(config1, config2, key, unique_value)


    def verify_parent_set(self, config1, config2, key, value):
        #   key not in config2 and key not in config1
        key_in_config2 = key in config2.variables

        callbacks = CallbackChecker()
        callbacks.assert_called(config1, 'change', key, current=value)
        if key_in_config2:
            callbacks.assert_not_called(config2, 'change', key)
        else:
            callbacks.assert_called(config2, 'change', key, current=value)

        with callbacks:
            config1[key] = value

        assert config1[key] == value
        if key_in_config2:
            assert config2[key] != value
        else:
            assert config2[key] == value


    #   ------------------------------------------------------------------------
    #                       Child Set Default
    #   ------------------------------------------------------------------------
    #def test_setdefault(self, configuration):

        #existing_key, new_key, removed_key = get_test_keys(data1, data2)

        #value = config.setdefault(existing_key, 8)
        #assert value == config[existing_key]

        #value = config.setdefault(new_key, 4)
        #assert value == 4
        #assert config[new_key] == 4


    #   ------------------------------------------------------------------------
    #                       Parent Set Default
    #   ------------------------------------------------------------------------
    #def test_setdefault(self, configuration):

        #existing_key, new_key, removed_key = get_test_keys(data1, data2)

        #value = config.setdefault(existing_key, 8)
        #assert value == config[existing_key]

        #value = config.setdefault(new_key, 4)
        #assert value == 4
        #assert config[new_key] == 4


    #   ------------------------------------------------------------------------
    #                           Child Update
    #   ------------------------------------------------------------------------
    def test_child_update1(self, config1, config2, unique_values):
        #   all keys in config2 and all keys not in config1
        keys = get_keys(is_in=[config1.variables, config2.variables],
                        count=len(unique_values))

        self.verify_child_update(config1, config2, keys, unique_values)


    def test_child_update2(self, config1, config2, unique_values):
        #   all keys in config2 and no keys not in config1
        keys = get_keys(is_in=config2.variables, not_in=config1.variables,
                        count=len(unique_values))

        self.verify_child_update(config1, config2, keys, unique_values)


    def test_child_update3(self, config1, config2, unique_values):
        #   no keys in config2 and all keys not in config1
        keys = get_keys(is_in=config1.variables, not_in=config2.variables,
                        count=len(unique_values))

        self.verify_child_update(config1, config2, keys, unique_values)


    def test_child_update4(self, config1, config2, unique_values):
        #   no keys in config2 and no keys not in config1
        keys = get_keys(not_in=[config1.variables, config1.variables],
                        count=len(unique_values))

        self.verify_child_update(config1, config2, keys, unique_values)


    def test_child_update12(self, config1, config2, unique_values):
        #   all keys1 in config2 and all keys1 not in config1
        #   all keys2 in config2 and no keys2 not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=[config1.variables, config2.variables],
                         count=count1)

        keys2 = get_keys(is_in=config2.variables, not_in=[config1.variables, keys1],
                         count=count2)

        self.verify_child_update(config1, config2, keys1 | keys2, unique_values)


    def test_child_update13(self, config1, config2, unique_values):
        #   all keys1 in config2 and all keys1 not in config1
        #   no keys in config2 and all keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=[config1.variables, config2.variables],
                         count=count1)

        keys2 = get_keys(is_in=config1.variables, not_in=[config2.variables, keys1],
                         count=count2)

        self.verify_child_update(config1, config2, keys1 | keys2, unique_values)


    def test_child_update14(self, config1, config2, unique_values):
        #   all keys1 in config2 and all keys1 not in config1
        #   no keys in config2 and no keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=[config1.variables, config2.variables],
                         count=count1)

        keys2 = get_keys(not_in=[config1.variables, config1.variables, keys1],
                         count=count2)

        self.verify_child_update(config1, config2, keys1 | keys2, unique_values)


    def test_child_update23(self, config1, config2, unique_values):
        #   all keys in config2 and no keys not in config1
        #   no keys in config2 and all keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=config2.variables, not_in=config1.variables,
                         count=count1)

        keys2 = get_keys(is_in=config1.variables, not_in=[config2.variables, keys1],
                         count=count2)

        self.verify_child_update(config1, config2, keys1 | keys2, unique_values)


    def test_child_update24(self, config1, config2, unique_values):
        #   all keys in config2 and no keys not in config1
        #   no keys in config2 and no keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=config2.variables, not_in=config1.variables,
                         count=count1)

        keys2 = get_keys(not_in=[config1.variables, config1.variables, keys1],
                         count=count2)

        self.verify_child_update(config1, config2, keys1 | keys2, unique_values)


    def test_child_update34(self, config1, config2, unique_values):
        #   no keys in config2 and all keys not in config1
        #   no keys in config2 and no keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=config1.variables, not_in=config2.variables,
                         count=count1)

        keys2 = get_keys(not_in=[config1.variables, config1.variables, keys1],
                         count=count2)

        self.verify_child_update(config1, config2, keys1 | keys2, unique_values)


    def verify_child_update(self, config1, config2, keys, values):
        variables = dict.fromkeys(keys, values)
        config1_keys = set()

        callbacks = CallbackChecker()
        for key, value in variables.items():
            callbacks.assert_called(config2, 'change', key, current=value)
            callbacks.assert_not_called(config1, 'change', key)
            if key in config1.variables:
                config1_keys.add(key)

        with callbacks:
            config2.update(variables)

        for key, value in variables.items():
            assert config2[key] == value
            assert config2.variables[key] == value

            if key in config1_keys:
                assert config1[key] != value
            else:
                assert key not in config1


    #   ------------------------------------------------------------------------
    #                           Parent Update
    #   ------------------------------------------------------------------------
    def test_parent_update1(self, config1, config2, unique_values):
        #   all keys in config2 and all keys not in config1
        keys = get_keys(is_in=[config1.variables, config2.variables],
                        count=len(unique_values))

        self.verify_parent_update(config1, config2, keys, unique_values)


    def test_parent_update2(self, config1, config2, unique_values):
        #   all keys in config2 and no keys not in config1
        keys = get_keys(is_in=config2.variables, not_in=config1.variables,
                        count=len(unique_values))

        self.verify_parent_update(config1, config2, keys, unique_values)


    def test_parent_update3(self, config1, config2, unique_values):
        #   no keys in config2 and all keys not in config1
        keys = get_keys(is_in=config1.variables, not_in=config2.variables,
                        count=len(unique_values))

        self.verify_parent_update(config1, config2, keys, unique_values)


    def test_parent_update4(self, config1, config2, unique_values):
        #   no keys in config2 and no keys not in config1
        keys = get_keys(not_in=[config1.variables, config1.variables],
                        count=len(unique_values))

        self.verify_parent_update(config1, config2, keys, unique_values)


    def test_parent_update12(self, config1, config2, unique_values):
        #   all keys1 in config2 and all keys1 not in config1
        #   all keys2 in config2 and no keys2 not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=[config1.variables, config2.variables],
                         count=count1)

        keys2 = get_keys(is_in=config2.variables, not_in=[config1.variables, keys1],
                         count=count2)

        self.verify_parent_update(config1, config2, keys1 | keys2, unique_values)


    def test_parent_update13(self, config1, config2, unique_values):
        #   all keys1 in config2 and all keys1 not in config1
        #   no keys in config2 and all keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=[config1.variables, config2.variables],
                         count=count1)

        keys2 = get_keys(is_in=config1.variables, not_in=[config2.variables, keys1],
                         count=count2)

        self.verify_parent_update(config1, config2, keys1 | keys2, unique_values)


    def test_parent_update14(self, config1, config2, unique_values):
        #   all keys1 in config2 and all keys1 not in config1
        #   no keys in config2 and no keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=[config1.variables, config2.variables],
                         count=count1)

        keys2 = get_keys(not_in=[config1.variables, config1.variables, keys1],
                         count=count2)

        self.verify_parent_update(config1, config2, keys1 | keys2, unique_values)


    def test_parent_update23(self, config1, config2, unique_values):
        #   all keys in config2 and no keys not in config1
        #   no keys in config2 and all keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=config2.variables, not_in=config1.variables,
                         count=count1)

        keys2 = get_keys(is_in=config1.variables, not_in=[config2.variables, keys1],
                         count=count2)

        self.verify_parent_update(config1, config2, keys1 | keys2, unique_values)


    def test_parent_update24(self, config1, config2, unique_values):
        #   all keys in config2 and no keys not in config1
        #   no keys in config2 and no keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=config2.variables, not_in=config1.variables,
                         count=count1)

        keys2 = get_keys(not_in=[config1.variables, config1.variables, keys1],
                         count=count2)

        self.verify_parent_update(config1, config2, keys1 | keys2, unique_values)


    def test_parent_update34(self, config1, config2, unique_values):
        #   no keys in config2 and all keys not in config1
        #   no keys in config2 and no keys not in config1
        count1 = len(unique_values) // 2
        count2 = len(unique_values) - count1

        keys1 = get_keys(is_in=config1.variables, not_in=config2.variables,
                         count=count1)

        keys2 = get_keys(not_in=[config1.variables, config1.variables, keys1],
                         count=count2)

        self.verify_parent_update(config1, config2, keys1 | keys2, unique_values)


    def verify_parent_update(self, config1, config2, keys, values):
        variables = dict.fromkeys(keys, values)

        callbacks = CallbackChecker()
        for key, value in variables.items():
            callbacks.assert_called(config1, 'change', key, current=value)
            if key in config2.variables:
                callbacks.assert_not_called(config2, 'change', key)
            else:
                callbacks.assert_called(config2, 'change', key, current=value)

        with callbacks:
            config1.update(variables)

        for key, value in variables.items():
            assert config1[key] == value
            assert config1.variables[key] == value

            if key in config2.variables:
                assert config2[key] != value
            else:
                assert config2[key] == value


    #   ------------------------------------------------------------------------
    #                           Child Delete
    #   ------------------------------------------------------------------------
    def test_child_delete1(self, config1, config2):
        #   key in config2 and key in config1
        key = get_key(is_in=[config1.variables, config2.variables])
        self.verify_child_delete(config1, config2, key)


    def test_child_delete2(self, config1, config2):
        #   key in config2 and key not in config1
        key = get_key(is_in=config2.variables, not_in=config1.variables)
        self.verify_child_delete(config1, config2, key)


    def test_child_delete3(self, config1, config2):
        #   key not in config2 and key in config1
        key = get_key(is_in=config1.variables, not_in=config2.variables)
        self.verify_child_delete(config1, config2, key)


    def test_child_delete4(self, config1, config2):
        #   key not in config2 and key not in config1
        key = get_key(not_in=[config1.variables, config2.variables])
        self.verify_child_delete(config1, config2, key)


    def verify_child_delete(self, config1, config2, key):
        key_in_config1 = key in config1.variables

        callbacks = CallbackChecker()
        callbacks.assert_not_called(config1, 'delete', key)
        callbacks.assert_not_called(config1, 'change', key)
        if key in config2.variables:
            if key_in_config1:
                callbacks.assert_called(config2, 'change', key, current=config1.variables[key])
            else:
                callbacks.assert_called(config2, 'delete', key)
        else:
            callbacks.assert_not_called(config2, 'change', key)
            callbacks.assert_not_called(config2, 'delete', key)

        with callbacks:
            if key in config2.variables:
                del config2[key]
            else:
                with pytest.raises(KeyError):
                    del config2[key]

        assert key not in config2.variables

        if key_in_config1:
            assert key in config1
            assert key in config2
        else:
            assert key not in config1
            assert key not in config2


    #   ------------------------------------------------------------------------
    #                           Parent Delete
    #   ------------------------------------------------------------------------
    def test_parent_delete1(self, config1, config2):
        #   key in config2 and key in config1
        key = get_key(is_in=[config1.variables, config2.variables])
        self.verify_parent_delete(config1, config2, key)


    def test_parent_delete2(self, config1, config2):
        #   key in config2 and key not in config1
        key = get_key(is_in=config2.variables, not_in=config1.variables)
        self.verify_parent_delete(config1, config2, key)


    def test_parent_delete3(self, config1, config2):
        #   key not in config2 and key in config1
        key = get_key(is_in=config1.variables, not_in=config2.variables)
        self.verify_parent_delete(config1, config2, key)


    def test_parent_delete4(self, config1, config2):
        #   key not in config2 and key not in config1
        key = get_key(not_in=[config1.variables, config2.variables])
        self.verify_parent_delete(config1, config2, key)


    def verify_parent_delete(self, config1, config2, key):
        key_in_config1 = key in config1.variables
        key_in_config2 = key in config2.variables

        callbacks = CallbackChecker()
        if key_in_config1:
            callbacks.assert_called(config1, 'delete', key)
            callbacks.assert_not_called(config1, 'change', key)

            if key_in_config2:
                callbacks.assert_not_called(config2, 'change', key)
                callbacks.assert_not_called(config2, 'delete', key)
            else:
                callbacks.assert_not_called(config2, 'change', key)
                callbacks.assert_called(config2, 'delete', key)

        else:
            callbacks.assert_not_called(config1, 'delete', key)
            callbacks.assert_not_called(config1, 'change', key)

            callbacks.assert_not_called(config2, 'change', key)
            callbacks.assert_not_called(config2, 'delete', key)


        with callbacks:
            if key in config1.variables:
                del config1[key]
            else:
                with pytest.raises(KeyError):
                    del config1[key]


        assert key not in config1.variables
        assert key not in config1

        if key_in_config2:
            assert key in config2
        else:
            assert key not in config2


    #   ------------------------------------------------------------------------
    #                           Child Clear
    #   ------------------------------------------------------------------------
    def test_child_clear(self, config1, config2):
        callbacks = CallbackChecker()

        for key in config1.variables:
            callbacks.assert_not_called(config1, 'delete', key)
            callbacks.assert_not_called(config1, 'change', key)

        for key in config2.variables:
            if key in config1.variables:
                callbacks.assert_called(config2, 'change', key, current=config1.variables[key])
            else:
                callbacks.assert_called(config2, 'delete', key)

        with callbacks:
            config2.clear()

        assert config2 == config1
        assert len(config2.variables) == 0


    #   ------------------------------------------------------------------------
    #                           Parent Clear
    #   ------------------------------------------------------------------------
    def test_parent_clear(self, config1, config2):
        callbacks = CallbackChecker()

        for key in config1.variables:
            callbacks.assert_called(config1, 'delete', key)
            callbacks.assert_not_called(config1, 'change', key)

            if key in config2.variables:
                callbacks.assert_not_called(config2, 'delete', key)
                callbacks.assert_not_called(config2, 'change', key)
            else:
                callbacks.assert_called(config2, 'delete', key)
                callbacks.assert_not_called(config2, 'change', key)

        for key in config2.variables:
            if key not in config1.variables:
                callbacks.assert_not_called(config2, 'delete', key)
                callbacks.assert_not_called(config2, 'change', key)


        with callbacks:
            config1.clear()

        assert len(config1.variables) == 0
        assert len(config1) == 0
        assert config2 == config2.variables






    #def test_load(self, configuration):

        #existing_key, new_key, removed_key = get_test_keys(data1, data2)

        #config.autosave = False

        #config.clear()
        #config.update(data2)
        #assert config == data2

        #config.save()
        #config.clear()
        #assert config != data2

        #on_changed = ChangeCallback(current=data2[existing_key], previous=None)
        #config.add_callback('change', existing_key, on_changed)

        #config.load()

        #assert config == data2
        #if config.are_callbacks_enabled():
            #assert on_changed.called
        #else:
            #assert not on_changed.called

































def is_ancestor(ancestor, descendent):
    """Return True if ancestor is reachable by recursively following defaults from descendent"""
    config = descendent.defaults
    while config and config is not ancestor:
        config = config.defaults
    return config is ancestor


def is_change_propagated(key, from_config, to_config):
    """Return True if a change event in to_config occurs after from_config[key] = ..."""
    if from_config is to_config:
        return True
    elif is_ancestor(from_config, to_config):
        config = to_config
        while config is not from_config:
            if key in config.variables:
                return False
            config = config.defaults
        return True
    else:
        return False


def is_delete_propagated(key, from_config, to_config):
    """Return True if a delete event in to_config occurs after del from_config[key]"""
    if key in from_config:
        if from_config is to_config:
            #   if key is in defaults, a change event is generated
            #   instead of a delete event
            return key not in from_config.defaults

        elif is_ancestor(from_config, to_config):
            config = to_config
            while config is not from_config:
                if key in config.variables:
                    return False
                config = config.defaults

            return key not in from_config.defaults

    return False


def is_change_on_delete(key, from_config, to_config):
    """Return True if a change event in to_config occurs after del from_config[key]"""
    if key in from_config:
        if from_config is to_config:
            #   if key is in defaults, a change event is generated
            return key in from_config.defaults

        elif is_ancestor(from_config, to_config):
            config = to_config
            while config is not from_config:
                if key in config.variables:
                    return False
                config = config.defaults

            return key in from_config.defaults

    return False


def value_after_delete(key, config):
    """Return the expected value of config[key] after del config[key]"""
    for ancestor in ancestors(config):
        if key in ancestor.variables:
            return ancestor.variables[key]

    assert False



def unchain(config):
    """
    Create list of configurations including config by recursively following defaults

    i.e. unchained = [config, config.defaults, config.defaults.defaults, ...]
    """
    configs = list()
    while config:
        configs.append(config)
        config = config.defaults

    return configs


def ancestors(config):
    """
    Create list of configurations excluding config by recursively following defaults
    i.e. unchained = [config.defaults, config.defaults.defaults, ...]
    """
    return unchain(config)[1:]


def merge(chain):
    """
    Merge each configuration's variables into a single dict

    This returns the expected equivalent of dict(**chain)
    """
    merged = dict()
    for config in reversed(unchain(chain)):
        merged = {**merged, **config}
    return merged


def unique_values(chain):
    """Generate a sequence of values not in any configuration in the chain"""
    value = -1
    while chain:
        value = max(value, *chain.variables.values())
        chain = chain.defaults

    while True:
        value += 1
        yield value


def others(config, configs):
    """Generate the sequence of configs excluding config"""
    for other in configs:
        if other is config:
            continue
        yield other


def mix_keys(key_partition, mixture_size, number_mixtures):
    """Randomly mix keys into a number of sets"""
    parts = [list(part) for part in key_partition]
    random.shuffle(parts)
    parts = itertools.cycle(parts)

    mixtures = list()
    while len(mixtures) < number_mixtures:
        mixture = set()

        while len(mixture) < mixture_size:
            part = next(parts)
            mixture.add(part[random.randrange(len(part))])

        mixtures.append(frozenset(mixture))


    assert all(len(mix) == mixture_size for mix in mixtures)
    assert len(mixtures) == number_mixtures

    return mixtures








#@pytest.fixture(params=(11494, 23801, 4084, 31291, 26266, 7183))
@pytest.fixture(params=(11494,))
def chained_configuration(tmpdir, request):
    random.seed(request.param)

    number_configs = 3
    disjoint_subset_size = 3

    all_keys = [''.join(letters)
                for letters in itertools.product(string.ascii_lowercase, repeat=2)]

    config_keys = [set() for _ in range(number_configs)]
    key_partition = set()
    for level in range(number_configs):
        for indices in itertools.combinations(range(number_configs), 1 + level):
            subset = frozenset(all_keys[:disjoint_subset_size])
            key_partition.add(subset)
            del all_keys[:disjoint_subset_size]

            for index in indices:
                config_keys[index].update(subset)

    path = tmpdir.mkdir('path')

    configs = list()
    start = 0
    for i, keys in enumerate(config_keys):
        values = range(start, start + len(keys))
        start += len(keys)

        config_file = str(path.join('config{}'.format(i)))
        with open(config_file, 'w') as file:
            json.dump({k: v for k, v in zip(keys, values)}, file)

        config = mle.Configuration(config_file)
        config.autosave = False

        try:
            config.defaults = configs[-1]
        except IndexError:
            pass

        configs.append(config)

    #   all_keys, all_values contain unused keys, values
    unused_keys = all_keys[:len(config_keys[0])]
    unused_values = list(range(start, start + len(unused_keys)))

    return configs[-1], unused_keys, unused_values, key_partition



def print_chained_configuration(chained_configuration):
    chain, unused_keys, unused_values, key_partition = chained_configuration

    print()
    print('-' * 80)
    print('unchained configs:')
    for config in unchain(chain):
        pprint.pprint(config.variables)
        print()

    print('unused keys (len = {}):'.format(len(unused_keys)))
    pprint.pprint(unused_keys)
    print('unused values (len = {}):'.format(len(unused_values)))
    pprint.pprint(unused_values)
    print()

    print('key partition:')
    for keys in key_partition:
        pprint.pprint(keys)

    print('-' * 80)


@pytest.fixture
def chain(chained_configuration):
    chain, unused_keys, unused_values, key_partition = chained_configuration
    return chain


@pytest.fixture
def unused_keys(chained_configuration):
    chain, unused_keys, unused_values, key_partition = chained_configuration

    #   check that unused_keys was created correctly
    assert all(key not in chain.variables
               for key in unused_keys
               for config in unchain(chain))

    return unused_keys


@pytest.fixture
def unused_values(chained_configuration):
    chain, unused_keys, unused_values, key_partition = chained_configuration

    #   check that unused_values was created correctly
    assert all(value not in chain.variables.values()
               for value in unused_values
               for config in unchain(chain))

    return unused_values


@pytest.fixture
def key_partition(chained_configuration):
    """
    Partition the set of all keys in the chain into disjoint subsets

    This function is best explained by way of an example. Consider a
    chain of three configurations:
        config1.defaults = dict()
        config2.defaults = config1
        config3.defaults = config2

    Let:
        A = set(config1.variables.keys())
        B = set(config2.variables.keys())
        C = set(config3.variables.keys())

    This function returns a list of sets of keys corresponding to the
    regions of the Venn diagram of sets A, B, and C.

    That is, the set A | B | C is partitioned into:
        A & B & C
        A & B - C
        B & C - A
        C & A - B
        A - B | C
        B - C | A
        C - A | B

    This partition is used to sample keys for setting & getting values
    so that all possible cases of key inclusion/exclusion are covered.
    """
    chain, unused_keys, unused_values, key_partition = chained_configuration

    #   check that key_partition was created correctly
    partitioned_keys = set().union(*key_partition)
    variable_keys = set().union(*(config.keys() for config in unchain(chain)))

    assert partitioned_keys == variable_keys
    assert all(keys1.isdisjoint(keys2)
               for keys1, keys2 in itertools.product(key_partition, repeat=2)
               if keys1 is not keys2)

    return key_partition





@pytest.fixture(params=(None, 3))
def key_sets(chain, key_partition, unused_keys, request):
    key_partition.add(frozenset(unused_keys))

    if request.param is None:
        return key_partition
    else:
        return mix_keys(key_partition,
                        mixture_size=3,
                        number_mixtures=request.param)



@pytest.fixture
def unchained_and_shuffled(chain):
    configs = unchain(chain)
    random.shuffle(configs)
    return configs


class TestChain:
    """Test an arbitrarily long chain of configurations"""
    def test_contains(self, chain):
        for config in unchain(chain):
            for ancestor in ancestors(config):
                for key in ancestor:
                    assert key in config


    def test_length(self, chain):
        for config in unchain(chain):
            assert len(config) == len(merge(config))


    def test_equality(self, chain):
        for config in unchain(chain):
            assert config == merge(config)
            if config.defaults:
                assert config != config.variables
            else:
                assert config == config.variables


    def test_keys(self, chain):
        for config in unchain(chain):
            compare_keys(config, merge(config))


    def test_values(self, chain):
        for config in unchain(chain):
            compare_values(config, merge(config))


    def test_items(self, chain):
        for config in unchain(chain):
            compare_items(config, merge(config))


    def test_iteration(self, chain):
        for config in unchain(chain):
            verify_iteration(config)


    def test_get(self, chain, unused_keys, unused_values):
        for config in unchain(chain):
            for key in config:
                found = False
                if key in config.variables:
                    assert config[key] == config.variables[key]
                    assert config.get(key) == config.variables[key]
                    found = True
                else:
                    for ancestor in ancestors(config):
                        if key in ancestor.variables:
                            assert config[key] == ancestor.variables[key]
                            assert config.get(key) == ancestor.variables[key]
                            found = True
                            break
                #   found should already be guaranteed from test_contains,
                #   but just a sanity check
                assert found

        for config in unchain(chain):
            key = unused_keys[0]

            with pytest.raises(KeyError):
                value = config[key]

            assert config.get(key) is None
            assert config.get(key, unused_values[0]) == unused_values[0]


    #   ------------------------------------------------------------------------
    #                            Set
    #   ------------------------------------------------------------------------
    def test_set(self, chain, unchained_and_shuffled, key_sets, unused_keys):
        values = unique_values(chain)

        for keys in key_sets:
            for config in unchained_and_shuffled:
                for key in keys:
                    value = next(values)
                    callbacks = CallbackChecker()
                    propagated = set()

                    self._prepare_for_set(config, key, value,
                                          unchained_and_shuffled, callbacks, propagated)

                    with callbacks:
                        config[key] = value

                    self._verify_set(config, key, value,
                                     unchained_and_shuffled, propagated)

                    #   make sure key wasn't added/removed to/from
                    #   the variables of any other config
                    for other in others(config, unchained_and_shuffled):
                        assert other.had_key == (key in other.variables)
                        del other.had_key



    #   ------------------------------------------------------------------------
    #                           Update
    #   ------------------------------------------------------------------------
    def test_update(self, chain, unchained_and_shuffled, key_sets, unused_keys):
        values = unique_values(chain)

        for keys in key_sets:
            for config in unchained_and_shuffled:
                variables = dict()
                callbacks = CallbackChecker()
                propagated = set()

                for key in keys:
                    variables[key] = next(values)
                    self._prepare_for_set(config, key, variables[key],
                                          unchained_and_shuffled, callbacks, propagated)

                with callbacks:
                    config.update(variables)

                for key in keys:
                    self._verify_set(config, key, variables[key],
                                     unchained_and_shuffled, propagated)

                #   make sure key wasn't added/removed to/from
                #   the variables of any other config
                for other in others(config, unchained_and_shuffled):
                    assert other.had_key == (key in other.variables)
                    del other.had_key




    def _prepare_for_set(self, config, key, value, configs, callbacks, propagated):
        callbacks.assert_called(config, 'change', key, current=value)

        for other in others(config, configs):
            #   remember which configurations already
            #   had the key before setting
            other.had_key = key in other.variables

            if is_change_propagated(key, from_config=config, to_config=other):
                #   remember which change should be propagated down the chain
                propagated.add((key, id(config), id(other)))
                callbacks.assert_called(other, 'change', key, current=value)
            else:
                callbacks.assert_not_called(other, 'change', key)


    def _verify_set(self, config, key, value, configs, propagated):
        assert config[key] == value
        assert config.get(key) == value
        assert config.variables[key] == value

        for other in others(config, configs):
            if (key, id(config), id(other)) in propagated:
                assert other[key] == value
            else:
                assert other.get(key) != value




    #   ------------------------------------------------------------------------
    #                           Delete
    #   ------------------------------------------------------------------------
    def test_delete(self, unchained_and_shuffled, key_sets):
        for keys in key_sets:
            for config in unchained_and_shuffled:
                for key in keys:
                    callbacks = CallbackChecker()
                    propagated = set()
                    changed = dict()

                    self._prepare_for_delete(config, key, unchained_and_shuffled,
                                             callbacks, propagated, changed)

                    with callbacks:
                        if key in config.variables:
                            del config[key]
                        else:
                            with pytest.raises(KeyError):
                                del config[key]

                    self._verify_delete(config, key, unchained_and_shuffled,
                                        propagated, changed)

                    #   make sure key wasn't added/removed to/from
                    #   the variables of any other config
                    for other in others(config, unchained_and_shuffled):
                        assert other.had_key == (key in other.variables)
                        del other.had_key

                    del config.had_key
                    with contextlib.suppress(AttributeError):
                        del config.expected_value




    def _prepare_for_delete(self, config, key, configs, callbacks, propagated, changed):
        if key in config.variables:
            config.had_key = True

            if is_change_on_delete(key, from_config=config, to_config=config):
                value = value_after_delete(key, config)
                config.expected_value = value
                callbacks.assert_called(config, 'change', key, current=value)

            for other in others(config, configs):
                #   remember which configurations already
                #   had the key before deleting
                other.had_key = (key in other.variables)

                if is_delete_propagated(key, from_config=config, to_config=other):
                    #   remember which change should be propagated down the chain
                    propagated.add((key, id(config), id(other)))
                    callbacks.assert_called(other, 'delete', key)
                else:
                    callbacks.assert_not_called(other, 'delete', key)

                if is_change_on_delete(key, from_config=config, to_config=other):
                    #   remember which change should be propagated down the chain
                    value = value_after_delete(key, config)
                    changed[(key, id(config), id(other))] = value
                    callbacks.assert_called(other, 'change', key, current=value)
                else:
                    callbacks.assert_not_called(other, 'change', key)

        else:
            config.had_key = False
            for other in others(config, configs):
                other.had_key = (key in other.variables)
                callbacks.assert_not_called(other, 'delete', key)
                callbacks.assert_not_called(other, 'change', key)


    def _verify_delete(self, config, key, configs, propagated, changed):
        assert key not in config.variables

        for other in others(config, configs):
            assert other.had_key == (key in other.variables)

            #   if the delete event was propagated down the chain
            if (key, id(config), id(other)) in propagated:
                assert key not in other

            if (key, id(config), id(other)) in changed:
                assert key in other
                assert other[key] == changed[(key, id(config), id(other))]






    #   ------------------------------------------------------------------------
    #                           Clear
    #   ------------------------------------------------------------------------
    def test_clear(self, unchained_and_shuffled):
        for config in unchained_and_shuffled:
            keys = config.variables.keys()
            callbacks = CallbackChecker()
            propagated = set()
            changed = dict()

            for key in keys:
                callbacks = CallbackChecker()
                self._prepare_for_delete(config, key, unchained_and_shuffled,
                                         callbacks, propagated, changed)

            with callbacks:
                config.clear()

            for key in keys:
                self._verify_delete(config, key, unchained_and_shuffled,
                                    propagated, changed)

                #   make sure key wasn't added/removed to/from
                #   the variables of any other config
                for other in others(config, unchained_and_shuffled):
                    assert other.had_key == (key in other.variables)
                    del other.had_key

                del config.had_key
                with contextlib.suppress(AttributeError):
                    del config.expected_value



























