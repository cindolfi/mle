import weakref
import inspect
import collections


class CallbackSet:
    """
    Set of weak references to callbacks

    weakref.WeakSet does not work with bound methods.
    This class gets around that limitation.
    """
    def __init__(self):
        self._callbacks = set()


    def add(self, callback):
        if inspect.ismethod(callback):
            owner = callback.__self__
            callback = weakref.WeakMethod(callback)
            if callback not in self._callbacks:
                weakref.finalize(owner, self._discard, callback)
        else:
            callback = weakref.ref(callback, self._discard)

        self._callbacks.add(callback)


    def remove(self, callback):
        if inspect.ismethod(callback):
            callback = weakref.WeakMethod(callback)
        else:
            callback = weakref.ref(callback)

        self._callbacks.remove(callback)


    def __iter__(self):
        return (callback() for callback in self._callbacks
                if callback() is not None)


    def __len__(self):
        return len(self._callbacks)


    def __call__(self, *args, **kwds):
        for callback in self:
            callback(*args, **kwds)


    def _discard(self, callback):
        try:
            self._callbacks.remove(callback)
        except KeyError:
            pass





















