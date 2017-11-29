
import sys
import builtins

try:
    #   try using colorama for colored text,
    #   if that is not installed try using termcolor
    import colorama
    colorama.init()

    def colored(*items, color, sep=' '):
        text = sep.join(str(item) for item in items)
        if color is None:
            return text
        else:
            return getattr(colorama.Fore, color.upper()) + text + colorama.Fore.RESET

except ImportError:
    if sys.platform != 'windows':
        import termcolor
        try:
            def colored(*items, color, sep=' '):
                text = sep.join(str(item) for item in items)
                if color is None:
                    return text
                else:
                    return termcolor.colored(text, color)

        except ImportError:
            pass

COLOR_TEXT_SUPPORTED = hasattr(sys.modules[__name__], 'colored')

if not COLOR_TEXT_SUPPORTED:
    def colored(*items, color, sep=' '):
        return sep.join(str(item) for item in items)


class printing:
    """
    Context manager that colors all text before it is printed

    Example:
        with colored.printing('red') as print:
            print('hello red world')

        #   globally disable colored printing
        colored.printing.disable()
        with colored.printing('red') as print:
            print('hello uncolored world')
    """
    _color_stack = list()
    _colored_print_enabled = True

    def __init__(self, color):
        self.color = color


    def __enter__(self):
        printing._color_stack.append(self.color)


    def __exit__(self, *exception):
        printing._color_stack.pop()


    @classmethod
    def default_color(cls):
        """The default color used by printing.print"""
        try:
            return cls._color_stack[-1]
        except IndexError:
            return None


    @classmethod
    def enable(cls):
        """Enable colored printing with colored.print"""
        cls._colored_print_enabled = True


    @classmethod
    def disable(cls):
        """Disable colored printing with colored.print"""
        cls._colored_print_enabled = False


    @classmethod
    def is_enabled(cls):
        """Returns True if colored printing is enabled"""
        return cls._colored_print_enabled


    @contextlib.contextmanager
    @classmethod
    def disabled(cls):
        """Context manager that temporiraly disables colored printing"""
        was_enabled = cls.is_enabled()
        cls.disable()

        yield

        if was_enabled:
            cls.enable()


    @classmethod
    def print(cls, *items, color=None, **kwds):
        """
        If colored printing is enabled, items are run through the
        colored.colored function before being printed using builtins.print.
        If colored printing is disabled, this function is equivalent to
        builtins.print.
        """
        if cls.is_enabled():
            if color is None:
                color = cls.default_color()
            kwds.setdefault('sep', ' ')
            builtins.print(colored(*items, color=color, sep=kwds['sep']), **kwds)
        else:
            builtins.print(*items, **kwds)


print = printing.print






