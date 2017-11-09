
import threading

import wrapt


def synchronized(wrapped):
    #   adapted from wrapt.synchronized
    def _synchronized_lock(context):
        # Attempt to retrieve the lock for the specific context.
        lock = vars(context).get('_synchronized_lock', None)

        if lock is None:
            # There is no existing lock defined for the context we
            # are dealing with so we need to create one. This needs
            # to be done in a way to guarantee there is only one
            # created, even if multiple threads try and create it at
            # the same time. We can't always use the setdefault()
            # method on the __dict__ for the context. This is the
            # case where the context is a class, as __dict__ is
            # actually a dictproxy. What we therefore do is use a
            # meta lock on this wrapper itself, to control the
            # creation and assignment of the lock attribute against
            # the context.
            meta_lock = vars(synchronized).setdefault('_synchronized_meta_lock',
                                                      threading.Lock())
            with meta_lock:
                lock = vars(context).get('_synchronized_lock', None)

                if lock is None:
                    lock = threading.RLock()
                    setattr(context, '_synchronized_lock', lock)

        return lock

    def _synchronized_wrapper(wrapped, instance, args, kwargs):
        if instance is None:
            lock = _synchronized_lock(wrapped)
        else:
            lock = _synchronized_lock(instance)

        with lock:
            return wrapped(*args, **kwargs)

    class _FinalDecorator(wrapt.FunctionWrapper):
        def __enter__(self):
            self._self_lock = _synchronized_lock(self.__wrapped__)
            self._self_lock.acquire()
            return self._self_lock

        def __exit__(self, *args):
            self._self_lock.release()

    return _FinalDecorator(wrapped=wrapped, wrapper=_synchronized_wrapper)

