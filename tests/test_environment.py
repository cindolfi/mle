
import json
import time

import pytest

import mle


def generate_key_not_in(mapping, *, initial='a'):
    key = initial
    while key in mapping:
        key += initial
    return key


@pytest.fixture(params=[dict(callbacks_enabled=True),
                        dict(callbacks_enabled=False)])
def configuration(tmpdir, request):
    data1 = {'a': 1,
             'b': 'b',
             'c': {'c.1': 1, 'c.2': 2},
             'd': [1, 2, 3, 4],
             'e': ['1', 2, '3', 4]}
    data2 = {'a': 2,
             'b': '1',
             'c': {'c.1': 2, 'c.2': 1},
             'd': list(),
             'f': 4}

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















#def test_create_environment(tmpdir):
    #root = tmpdir.mkdir('root')
    #GlobalConfiguration.create(str(root))

    #project_dir = tmpdir.mkdir('project')

    #with project_dir.as_cwd()
        #environment = Environment.create()
        #assert project_dir.ensure('.mle')


#def test_create_model(self):
    #pass


#def test_activate_model(self):
    #pass















