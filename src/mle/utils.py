
import pathlib
import sys

#   try using colorama for colored text,
#   if that is not installed try using termcolor
try:
    import colorama
    colorama.init()

    def colored(*items, color, sep=' '):
        text = sep.join(str(item) for item in items)
        return getattr(colorama.Fore, color.upper()) + text + colorama.Fore.RESET

except ImportError:
    if sys.platform != 'windows':
        import termcolor
        try:
            def colored(*items, color, sep=' '):
                text = sep.join(str(item) for item in items)
                return termcolor.colored(text, color)

        except ImportError:
            pass

COLOR_TEXT_SUPPORTED = hasattr(sys.modules[__name__], 'colored')

if not COLOR_TEXT_SUPPORTED:
    def colored(*items, color, sep=' '):
        return sep.join(str(item) for item in items)


def clean_name(name):
    return pathlib.Path(name).name


def autocomplete(parser):
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass

