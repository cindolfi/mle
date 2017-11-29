"""
Utilities and helpers for writing handling command line arguments

All of the argument parsers provided by this module are meant to
be used as a parent to a script's argument parser.  As such, they
are all created with argparse.ArgumentParser(add_help=False).
"""
import argparse


def environment_parser():
    """
    A parser with arguments common to most mle scripts

    The --environ argument takes a path and adds a pathlib.Path
    environ attribute to the result of parse_args().

    Returns:
        An argparse.ArgumentParser object
    """
    import pathlib
    from .environment import Environment

    class EnvironmentAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            directory = values
            setattr(namespace, self.dest, pathlib.Path(directory))
            Environment.default_directory = directory

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-n', '--environ',
                        action=EnvironmentAction,
                        default=None,
                        help='path to the environment')
    return parser


def no_colored_text_parser():
    """
    A parser with options controlling colored text printing

    If the user provides the --no-color option colored printing
    is globally disabled.  The parser addes two attributes to the
    result of parse_args(): print and colored.  The print attribute
    is a print function.  If --no-color is given, it is set to
    builtin.print, otherwise it is mle.colored.print.  The colored
    attribute is a boolean indicating whether colored text should be used.

    Returns:
        An argparse.ArgumentParser object
    """
    from . import colored

    class NoColorAction(argparse.Action):
        def __init__(self, *args, **kwds):
            super().__init__(*args, **kwds)
            self.nargs = 0

        def __call__(self, parser, namespace, values, option_string=None):
            namespace.print = print
            namespace.colored = False
            colored.printing.disable()

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--no-color',
                        dest='colored',
                        action=NoColorAction,
                        default=True,
                        help='do not use colored text')
    parser.set_defaults(print=colored.print)
    return parser


def config_file_parser(purpose='use'):
    """
    Parser with arguments used to choose the configuration file

    The parser has a mutually exclusive group that includes:
    --local, --global, --system, --model, and --file.  These options
    determine the configuration file name.  The --model option takes a
    single model identifier (integer) argument. It is made available via
    the parser_args().config_model attribute.  The --file argument takes
    a single path argument from which a pathlib.Path argument is constructed
    and provided as parser_args().config_file.  The other three options
    do not take any arguments.  If none of these is given, the
    parser assume --local by default.

    A config attribute is added to the result of parse_args().
    It is set to the option string with the '--' removed.
    e.g.
        parser = config_file_parser()
        args = parser.parse_args(['--model', '10'])
        assert args.config == 'model'

    The create_config attribute is a function that takes the parsed
    arguments and creates a mle.Configuration object based on the config
    and arguments.  If an Environment was created in the process it
    is returned as well.

    e.g.
        parser = config_file_parser()
        args = parser.parse_args(['--local', '--search-path', 'foo/bar']))
        assert args.search_path == pathlib.Path('./foo/bar')
        #   create a Configuration for the local file in ./foo/bar
        config, environment = args.create_config(args)

    Args:
        purpose(str): a verb used to start help messages
        add_search_path(bool): if True add a '--search-path' argument
            and a create_config function to the result of parse_args().

    Returns:
        An argparse.ArgumentParser object
    """
    import pathlib
    from . import environment
    from . import configuration

    class ConfigFileOption(argparse.Action):
        def __call__(self, parser, args, values, option_string=None):
            if option_string == '--local':
                args.config = 'local'
                def create_config(args):
                    try:
                        environ = environment.Environment()
                        path = environ.directory
                    except environment.EnvironmentNotFoundError:
                        environ = None
                        path = '.'
                    return environment.local_configuration(path), environ

            elif option_string == '--global':
                args.config = 'global'
                def create_config(args):
                    try:
                        environ = environment.Environment()
                        path = environ.directory
                    except environment.EnvironmentNotFoundError:
                        environ = None
                        path = '.'
                    return environment.global_configuration(path), environ

            elif option_string == '--system':
                args.config = 'system'
                def create_config(args):
                    return environment.system_configuration(), None

            elif option_string == '--model':
                args.config = 'model'
                args.config_model = values[0]
                def create_config(args):
                    environ = environment.Environment()
                    return environ.model(args.config_model), environ

            elif option_string == '--file':
                args.config = 'file'
                args.config_file = values[0]
                def create_config(args):
                    return configuration.Configuration(args.config_file), None
            else:
                raise ValueError('{} is not a valid configuration file option'.format(option_string))

            args.create_config = create_config


    parser = argparse.ArgumentParser(add_help=False)

    file_options = parser.add_argument_group('File')

    config_file_option = file_options.add_mutually_exclusive_group()

    config_file_option.add_argument('--local',
                                    action=ConfigFileOption,
                                    nargs=0,
                                    help='{} the local configuration file '
                                         '(path/to/environment/'
                                         '{})'.format(purpose, environment.LOCAL_CONFIG_FILENAME))

    config_file_option.add_argument('--global',
                                    action=ConfigFileOption,
                                    nargs=0,
                                    help='{} the global configuration file '
                                         '({})'.format(purpose, environment.GLOBAL_CONFIG_FILENAME))

    config_file_option.add_argument('--system',
                                    action=ConfigFileOption,
                                    nargs=0,
                                    help='{} the system wide configuration file '
                                         '({})'.format(purpose, environment.SYSTEM_CONFIG_FILENAME))

    config_file_option.add_argument('--model',
                                    action=ConfigFileOption,
                                    nargs=1,
                                    metavar='IDENTIFIER',
                                    type=int,
                                    help='{} the model\'s configuration file '
                                         '(path/to/environment/model/'
                                         '{})'.format(purpose, environment.MODEL_CONFIG_FILENAME))

    config_file_option.add_argument('--file',
                                    action=ConfigFileOption,
                                    nargs=1,
                                    type=pathlib.Path,
                                    help='{} a specified configuration file'.format(purpose))

    def create_config(args):
        try:
            environ = environment.Environment()
            path = environ.directory
        except environment.EnvironmentNotFoundError:
            environ = None
            path = '.'
        return environment.local_configuration(path), environ

    parser.set_defaults(config='local', create_config=create_config)

    return parser


def logging_parser(default=logging.INFO, add_help=False):
    import logging
    import mle.logging

    class LogLevelAction(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            log_level = getattr(logging, values.upper(), None)
            if log_level is None:
                raise ValueError('Invalid log level: {}'.format(log_level))

            mle.logging.DEFAULT_LOGGING_LEVEL = log_level
            setattr(namespace, self.dest, log_level)

    mle.logging.DEFAULT_LOGGING_LEVEL = default

    parser = argparse.ArgumentParser(add_help=add_help)

    parser.add_argument('--log',
                        dest='log_level',
                        action=LogLevelAction,
                        choices=['debug', 'info', 'warning', 'error', 'critical'],
                        default=default)
    return parser


def autocomplete(parser):
    """
    Add autocompletion to a parser

    This function applies uses the argcomplete package.  If the package
    is not installed this function quietly does nothing.  Default
    argcomplete auto completion is applied to the parser.  If custom
    or specialized auto completion (e.g. adding completer attributes to
    the parser) is necessary it needs to be implemented by the script
    before this function is called.
    """
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass








