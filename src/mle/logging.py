
import logging
from logging import DEBUG, INFO, WARNING, ERROR, CRITICAL
import datetime
import re
import importlib
import csv
import io
import contextlib

from . import environment
from . import colored
from .synchronized import synchronized

__all__ = ['create_config', 'get_config', 'set_config',
           'create_handler', 'create_filter', 'create_formatter',
           'ColoredFormatter', 'ModelFileHandler', 'BlockTrainingMetrics']


#   logging configuration give to set_config
_logging_configuration = None

DEFAULT_LOGGING_LEVEL = logging.INFO

def create_config(level=DEFAULT_LOGGING_LEVEL, filename=None, *,
                  console_level=None, file_level=None,
                  field_colors=None, level_colors=None):
    """
    Construct a logging configuration for use with the MLE library

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
            'csv': {
                '()': 'mle.logging.CsvFormatter',
                'format': '%(levelname)s %(asctime)s %(name)s %(message)s',
                'dialect': 'unix'
            },
        },
        'filters': {
            'block_data': {'()': 'mle.logging.BlockData'},
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'colored-short',
                'filters': ['block_data']
            },
            'training-file': {
                'class': 'mle.logging.ModelFileHandler',
                'filename': 'train.log',
                'level': logging.INFO,
                'formatter': 'csv',
            },
            'evaluation-file': {
                'class': 'mle.logging.ModelFileHandler',
                'filename': 'eval.log',
                'level': logging.INFO,
                'formatter': 'csv',
            },
        },
        'loggers': {
            'mle': {},
            'training': {
                'handlers': ['training-file']
            },
            'training.data': {},
            'evaluation': {
                'handlers': ['evaluation-file']
            },
            'evaluation.data': {},
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


def configure(config=None, **kwds):
    """
    Configure the the logging system

    Args:
        config(dict): a logging configuration that can be
            passed to logging.config.dictConfig()
            if None, use create_config(**kwds)
        kwds: keyword arguments passed to create_config()
    """
    import logging.config
    if config is None:
        config = create_config(**kwds)

    logging.config.dictConfig(config)
    set_config(config)


def model_environment_file_handlers():
    for logger in logging.Logger.manager.loggerDict.values():
        #   logger PlaceHolder objects don't have 'handlers', ignore them
        if hasattr(logger, 'handlers'):
            continue

        for handler in logger.handlers:
            if isinstance(handler, ModelFileHandler):
                yield handler


def use_environment(environment):
    ModelFileHandler.initial_environment = environment

    for handler in model_environment_file_handlers():
        handler.environment = environment


def create_handler(handler, configuration):
    """Create a Handler object from a configuration dict"""
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
    """Create a Filter object from a configuration dict"""
    filter_config = configuration['formatters'][formatter]

    type_name = filter_config.pop('()', 'logging.Filter')

    module_name, class_name = type_name.rsplit('.', 1)

    module = importlib.import_module(module_name)
    filter_class = getattr(module, class_name)

    return filter_class(**filter_config)


def create_formatter(formatter, configuration):
    """Create a Formatter object from a configuration dict"""
    formatter_config = configuration['formatters'][formatter]

    type_name = formatter_config.pop('()', 'logging.Formatter')

    module_name, class_name = type_name.rsplit('.', 1)

    module = importlib.import_module(module_name)
    formatter_class = getattr(module, class_name)

    if type_name == 'logging.Formatter':
        formatter_config['fmt'] = formatter_config.pop('format', None)

    return formatter_class(**formatter_config)




class BlockData(logging.Filter):
    def filter(self, record):
        return not record.name.endswith('.data')




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


    def __init__(self, fmt=None, datefmt=None, field_colors=None, level_colors=None):
        self.uncolored_format = fmt or '%(message)s'
        self.field_colors = dict(ColoredFormatter.FIELD_COLORS.items(),
                                 **(field_colors or {}))
        self.level_colors = dict(ColoredFormatter.LEVEL_COLORS.items(),
                                 **(level_colors or {}))
        self._uncolored_formatter = None

        if colored.COLOR_TEXT_SUPPORTED:
            def color_field(match):
                field = match.group(0)
                name = ColoredFormatter.NAME_REGEX.match(field).group(1)
                field = colored.colored(field, color=self.field_colors.get(name))
                #   special handling of level fields so they can be
                #   colored depending on the actual log level in self.format()
                if name == 'levelname' or name == 'levelno':
                    self._format_has_level_fields = True
                    field = ''.join([ColoredFormatter.LEVEL_START_TAG,
                                     field,
                                     ColoredFormatter.LEVEL_END_TAG])
                return field

            message_format = ColoredFormatter.FIELD_REGEX.sub(color_field,
                                                              self.uncolored_format)
        else:
            self._format_has_level_fields = False
            message_format = self.uncolored_format

        super().__init__(message_format, datefmt)


    def format(self, record):
        if colored.printing.is_enabled():
            message = super().format(record)
            if self._format_has_level_fields:
                #   this is a bit hacky, there has to be a better way
                color = self.level_colors.get(record.levelno).lower()
                color_code, reset_code = colored.colored(' ', color=color).split(maxsplit=1)
                message = message.replace('!LS!', color_code)
                message = message.replace('!LE!', reset_code)

            return message
        else:
            if self._uncolored_formatter is None:
                self._uncolored_formatter = super().__init__(self.uncolored_format,
                                                             self.datefmt)
            return self._uncolored_formatter.format(record)





class CsvFormatter(logging.Formatter):
    FIELDNAME_REGEX = re.compile(r'%\(([a-zA-Z0-9_]+)\)(?:-\d+)?[sd]')

    def __init__(self, fmt, datefmt=None, dialect='unix'):
        super().__init__(fmt, datefmt)
        self._dialect = dialect

        self._fieldnames = CsvFormatter.FIELDNAME_REGEX.findall(fmt)
        if not self._fieldnames:
            raise ValueError('No fields found in format: {}'.format(fmt))


    @property
    def dialect(self):
        return self._dialect


    @property
    def fieldnames(self):
        return self._fieldnames


    def header(self):
        row_buffer = io.StringIO()
        with contextlib.closing(row_buffer):
            writer = csv.DictWriter(row_buffer, fieldnames=self.fieldnames)
            writer.writeheader()

            return row_buffer.getvalue()


    def format(self, record):
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)

        fields = dict()
        for fieldname in self.fieldnames:
            if fieldname == 'message':
                field = record.getMessage()
            else:
                field = getattr(record, fieldname)

            fields[fieldname] = field

        row_buffer = io.StringIO()
        with contextlib.closing(row_buffer):
            writer = csv.DictWriter(row_buffer,
                                    fieldnames=self.fieldnames,
                                    dialect=self.dialect)
            writer.writerow(fields)
            result = row_buffer.getvalue()

        return result.rstrip()




class ModelFileHandler(logging.StreamHandler):
    initial_environment = None

    def __init__(self, filename, mode='a'):
        super().__init__()
        self._set_stream(None)
        self.mode = mode
        self._filename = str(filename)
        self._header = None

        self._environment = None

        if isinstance(ModelFileHandler.initial_environment, environment.Environment):
            self._environment = ModelFileHandler.initial_environment
        else:
            with contextlib.suppress(environment.EnvironmentNotFoundError):
                self._environment = environment.Environment(ModelFileHandler.initial_environment)

        if self._environment is not None:
            self._environment.add_active_model_change_callback(self._on_model_change)

        self._update_directory()


    @property
    def environment(self):
        return self._environment


    @environment.setter
    def environment(self, environment):
        if environment is not self._environment:
            if self._environment is not None:
                try:
                    self._environment.remove_current_model_change_callback(self._on_model_change)
                except AttributeError:
                    self._environment.remove_active_model_change_callback(self._on_model_change)

            self._environment = environment
            self._update_directory()

            if self._environment is not None:
                try:
                    self._environment.add_current_model_change_callback(self._on_model_change)
                except AttributeError:
                    self._environment.add_active_model_change_callback(self._on_model_change)


    def _on_model_change(self, current_model, previous_model):
        self._update_directory()


    @synchronized
    def _update_directory(self):
        if self._environment is None:
            directory = None
        else:
            try:
                directory = self._environment.model().log_directory
            except environment.ModelNotFoundError:
                directory = None

        if directory is None:
            previous_stream = self._set_stream(None)
        else:
            filepath = directory / self._filename
            write_header = not filepath.exists() or filepath.stat().st_size == 0

            previous_stream = self._set_stream(filepath.open(self.mode))

            if write_header and self.stream and self._header:
                self.stream.write(self._header)

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
        if self.environment is None:
            if isinstance(ModelFileHandler.initial_environment, environment.Environment):
                self.environment = ModelFileHandler.initial_environment
            else:
                self.environment = environment.Environment(ModelFileHandler.initial_environment)

        if self.stream is not None:
            super().emit(record)


    def setFormatter(self, formatter):
        if isinstance(formatter, CsvFormatter):
            self._header = '\n'.join(['#! csv', formatter.header()])
        super().setFormatter(formatter)




class LogPrinter:
    """
    Prints log file

    The file will be treated as a CSV file if it has a .csv extension or
    the first line is:
    #! csv
    """
    def print(self, filepath):
        if filepath.suffix == '.csv':
            with filepath.open('r') as file:
                self.print_csv(file)
        else:
            with filepath.open('r') as file:
                try:
                    line = next(file)
                except StopIteration:
                    pass
                else:
                    import re
                    shebang = re.compile(r'^\s*\#\!')
                    if shebang.match(line):
                        file_format = line.strip()[2:].strip()
                    else:
                        file_format = None

                    if file_format == 'csv':
                        self.print_csv(file)
                    else:
                        file.seek(0)
                        for line in file:
                            print(line)


    def print_csv(self, file):
        import csv
        #   get a sample to sniff for dialect
        file.seek(0)
        _ = next(file)
        sample = file.read(1024)

        #   reset cursor on the header line
        file.seek(0)
        _ = next(file)

        #   construct reader
        sniffer = csv.Sniffer()

        dialect = sniffer.sniff(sample)
        if sniffer.has_header(sample):
            fieldnames = next(file).strip().split(',')
        else:
            fieldnames = list()

        reader = csv.DictReader(file,
                                dialect=dialect,
                                fieldnames=fieldnames)
        if fieldnames:
            self.print_csv_with_fieldnames(reader, fieldnames)
        else:
            self.print_csv_without_fieldnames(reader)


    def print_csv_with_fieldnames(self, reader, fieldnames):
        import mle.logging
        import mle.colored
        import logging

        #   eat column names
        _ = next(reader)

        records = list()
        widths = dict()
        for record in reader:
            for name, value in record.items():
                if mle.colored.printing.is_enabled():
                    if name == 'levelname':
                        log_level = getattr(logging, value.upper(), None)
                        color = mle.logging.ColoredFormatter.LEVEL_COLORS.get(log_level)
                    elif name == 'levelno':
                        color = mle.logging.ColoredFormatter.LEVEL_COLORS.get(int(value))
                    else:
                        color = mle.logging.ColoredFormatter.FIELD_COLORS.get(name)

                    value = mle.colored.colored(value, color=color)

                record[name] = value
                widths[name] = max(len(value), widths.get(name, 0))

            records.append(record)

        #   build record template
        record_format = ''
        for fieldname in fieldnames:
            record_format += '{{{name}:{width}}}  '.format(name=fieldname,
                                                           width=widths[fieldname])
        #   print records
        for record in records:
            print(record_format.format(**record))


    def print_csv_without_fieldnames(self, reader):
        #   since there are not fieldnames, all fields are stored
        #   in a list assigned to None
        records = list()
        widths = list()
        for record in reader:
            values = record[None]
            for index, value in enumerate(values):
                try:
                    widths[index] = max(len(value), widths[index])
                except IndexError:
                    while len(widths) <= index:
                        widths.append(0)
                    widths[index] = len(value)

            records.append(values)

        #   build record template
        record_format = ''
        for index, width in enumerate(widths):
            record_format += '{{{index}:{width}}}  '.format(index=index,
                                                            width=width)
        #   print records
        for record in records:
            print(record_format.format(*record))


    def print_default(lines):
        for line in lines:
            print(line)







