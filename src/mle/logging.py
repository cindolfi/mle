
import logging
import logging.config
import datetime
import re
import importlib
import os.path
import sys

from . import environment
from . import utils


__all__ = ['create_config', 'get_config', 'set_config',
           'create_handler', 'create_filter', 'create_formatter',
           'ColoredFormatter', 'ModelFileHandler', 'BlockTrainingMetrics']


#   logging configuration give to set_config
_logging_configuration = None


def create_config(level=logging.INFO, filename=None, *,
                  console_level=None, file_level=None,
                  field_colors=None, level_colors=None):
    """
    Construct a logging configuration for use with mle

    Args:
        level(int): root logging level
        console_level(int): logging level sent to the console
            if None it is set to the root logging level
        file_level(int): logging level sent to the file
            if None it is set to the root logging level
        filename(path-like): path to a log file
        field_colors(dict): a mapping from log record fields to colors (str)
            used to construct instances of ColoredFormatter
        level_colors(dict): a mapping from log levels to colors (str)
            used to construct instances of ColoredFormatter

    Returns:
        A dict() that can be passed to logging.config.dictConfig()
    """
    if console_level is None:
        console_level = level

    if file_level is None:
        file_level = level

    configuration = {
        'version': 1,
        'formatters': {
            'short': {
                'format': '%(levelname)s %(name)s: %(message)s'
            },
            'long': {
                'format': '%(levelname)-8s %(asctime)s %(name)-16s %(message)s'
            },
            'colored-short': {
                '()': 'mle.logging.ColoredFormatter',
                'format': '%(levelname)s %(name)s: %(message)s',
                'field_colors': field_colors,
                'level_colors': level_colors
            },
            'colored-long': {
                '()': 'mle.logging.ColoredFormatter',
                'format': '%(levelname)-8s %(asctime)s %(name)-16s %(message)s',
                'field_colors': field_colors,
                'level_colors': level_colors
            },
        },
        'filters': {
            'block_metrics': {'()': 'mle.logging.BlockTrainingMetrics'},
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'colored-short',
                'filters': ['block_metrics']
            },
            'training-file': {
                'class': 'mle.logging.ModelFileHandler',
                'filename': 'train.log',
                'level': logging.INFO,
                'formatter': 'colored-long',
            },
        },
        'loggers': {
            'mle': {},
            'training': {
                'handlers': ['training-file']
            },
            'training.metrics': {},
        },
        'root': {
            'level': level,
            'handlers': ['console']
        },
    }

    if filename is not None:
        configuration['handlers']['file'] = {'class': 'logging.FileHandler',
                                             'filename': filename,
                                             'level': file_level,
                                             'formatter': 'colored-long'}
        configuration['handlers']['root']['handlers'].append('file')


    return configuration


def set_config(configuration):
    """
    This function doesn't actually configure the logging system.
    It is the user's responsibility to call logging.config.dictConfig().

    Instead, this function provides a copy of the dict() used to configure
    the logging system.  This is used internally to dynamically construct
    logging objects that are consistent with the configuration.

    e.g.
    #   create a default mle configuration
    mle_config = mle.logging.create_config()

    #   modify the mle.configuration
    mle_config['formatters']['short']['format'] = '%(message)s'
    mle_config['handlers']['console']['formatter'] = 'short'

    #   merge with the another library's configuration
    some_other_config = create_some_other_config_dict()

    config = dict(mle_config.items(),
                  some_other_config.items())

    #   do some application level configuration
    config['root']['level'] = logging.INFO

    #   actually configure the logging system
    import logging.config
    logging.config.dictConfig(config)

    #   give mle the final configuration dict()
    mle.logging.set_config(config)

    Args:
        configuration(dict): conforms to the logging.config dictionary schema
    """
    _logging_configuration = configuration


def get_config():
    """
    Returns a copy of the configuration dict() given to set_config()

    If the configuration has not been set using set_config(),
    a default configuration is created using create_config().
    """
    if _logging_configuration is None:
        return create_config()

    return _logging_configuration.copy()




def create_handler(handler, configuration):
    """Create a Handler object from a configuration dict()"""
    handler_config = configuration['handlers'][handler]

    formatter = handler_config.pop('formatter', None)
    filters = handler_config.pop('filters', None)
    level = handler_config.pop('level', None)

    type_name = handler_config.pop('class')
    module_name, class_name = type_name.rsplit('.', 1)

    module = importlib.import_module(module_name)

    handler_class = getattr(module, class_name)
    handler = handler_class(**handler_config)

    if formatter is not None:
        formatter = create_formatter(formatter, configuration)
        handler.setFormatter(formatter)

    if level is not None:
        handler.setLevel(level)

    if filters is not None:
        for filter in filters:
            filter = create_filter(filter, configuration)
            handler.addFilter(filter)

    return handler


def create_filter(filter, configuration):
    """Create a Filter object from a configuration dict()"""
    filter_config = configuration['formatters'][formatter]

    type_name = filter_config.pop('()', 'logging.Filter')

    module_name, class_name = type_name.rsplit('.', 1)

    module = importlib.import_module(module_name)
    filter_class = getattr(module, class_name)

    return filter_class(**filter_config)


def create_formatter(formatter, configuration):
    """Create a Formatter object from a configuration dict()"""
    formatter_config = configuration['formatters'][formatter]

    type_name = formatter_config.pop('()', 'logging.Formatter')

    module_name, class_name = type_name.rsplit('.', 1)

    module = importlib.import_module(module_name)
    formatter_class = getattr(module, class_name)

    if type_name == 'logging.Formatter':
        formatter_config['fmt'] = formatter_config.pop('format', None)

    return formatter_class(**formatter_config)




class BlockTrainingMetrics(logging.Filter):
    def filter(self, record):
        return record.name != 'training.metrics'




class ColoredFormatter(logging.Formatter):
    LEVEL_COLORS = {logging.CRITICAL: 'red',
                    logging.ERROR: 'red',
                    logging.WARNING: 'yellow',
                    logging.INFO: 'green',
                    logging.DEBUG: 'magenta',
                    logging.NOTSET: None}

    FIELD_COLORS = {'asctime': 'cyan',
                    'created': None,
                    'exc_info': None,
                    'filename': None,
                    'funcName': None,
                    'levelname': None,
                    'levelno': None,
                    'lineno': None,
                    'module': None,
                    'msecs': None,
                    'message': 'yellow',
                    'name': 'green',
                    'pathname': None,
                    'process': None,
                    'processName': None,
                    'relativeCreated': None,
                    'thread': None,
                    'threadName': None}

    FIELD_REGEX = re.compile(r'(%\([a-zA-Z0-9_]+\)(?:-\d+)?[sd])')
    NAME_REGEX = re.compile(r'%\(([a-zA-Z0-9_]+)\)')

    LEVEL_START_TAG = '!LS!'
    LEVEL_END_TAG = '!LE!'


    def __init__(self, format=None, datefmt=None, field_colors=None, level_colors=None):
        message_format = format or '%(message)s'
        date_format = datefmt or datetime.datetime.now().isoformat()
        field_colors = field_colors or {}
        level_colors = level_colors or {}

        self.field_colors = dict(ColoredFormatter.FIELD_COLORS.items(), **field_colors)
        self.level_colors = dict(ColoredFormatter.LEVEL_COLORS.items(), **level_colors)
        self._format_has_level_fields = False

        if utils.COLOR_TEXT_SUPPORTED:
            def color_field(match):
                field = match.group(0)
                name = ColoredFormatter.NAME_REGEX.match(field).group(1)
                field = utils.colored(field, self.field_colors.get(name))
                #   special handling of level fields so they can be
                #   colored depending on the actual log level in self.format()
                if name == 'levelname' or name == 'levelno':
                    self._format_has_level_fields = True
                    field = ''.join([ColoredFormatter.LEVEL_START_TAG,
                                     field,
                                     ColoredFormatter.LEVEL_END_TAG])
                return field

            message_format = ColoredFormatter.FIELD_REGEX.sub(color_field,
                                                              message_format)
        super().__init__(message_format, date_format)


    def format(self, record):
        message = super().format(record)
        if self._format_has_level_fields:
            color = self.level_colors.get(record.levelno).lower()
            color_code, reset_code = utils.colored(' ', color).split(maxsplit=1)
            message = message.replace('!LS!', color_code)
            message = message.replace('!LE!', reset_code)

        return message







class ModelFileHandler(logging.StreamHandler):
    def __init__(self, filename, mode='a'):
        super().__init__()
        self._set_stream(None)
        self.mode = mode
        self._filename = os.path.basename(str(filename))
        self._environ = environment.Environment()

        self._update_directory()


    @property
    def environ(self):
        return self._environ

    @environ.setter
    def environ(self, environ):
        if isinstance(environ, str):
            environ = environment.Environment(environ)

        if environ is not self._environ:
            if self._environ is not None:
                self._environ.remove_model_change_listener(self._on_model_change)

            self._environ = environ
            self._update_directory()

            if self._environ is not None:
                self._environ.add_model_change_listener(self._on_model_change)


    def _on_model_change(self, current_model, previous_model):
        self._update_directory()


    def _update_directory(self):
        if self._environ is None:
            directory = None
        else:
            try:
                directory = self._environ.log_path()
            except environment.NoCurrentModelError:
                directory = None

        if directory is None:
            previous_stream = self._set_stream(None)
        else:
            filepath = directory / self._filename
            previous_stream = self._set_stream(filepath.open(self.mode))

        if previous_stream is not None:
            previous_stream.close()


    def _set_stream(self, stream):
        if stream is self.stream:
            result = None
        else:
            result = self.stream
            self.acquire()
            try:
                self.flush()
                self.stream = stream
            finally:
                self.release()
        return result


    def close(self):
        self.acquire()
        try:
            try:
                if self.stream:
                    try:
                        self.flush()
                    finally:
                        stream = self.stream
                        self.stream = None
                        if stream:
                            stream.close()
            finally:
                super().close()
        finally:
            self.release()


    def emit(self, record):
        if self.stream is None:
            return
        super().emit(record)












