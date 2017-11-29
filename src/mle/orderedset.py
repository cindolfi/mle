import bisect

from .synchronized import synchronized


class OrderedSet:
    """Sorted collection of unique items"""
    @synchronized
    def __init__(self, items=None):
        self._items = sorted(set(items)) if items is not None else list()


    @synchronized
    def add(self, item):
        if item is None or item in self:
            return False

        index = bisect.bisect_left(self._items, item)
        self._items.insert(index, item)
        return True


    @synchronized
    def discard(self, item):
        index = self.index(item)
        del self._items[index]


    @synchronized
    def clear(self):
        self._items.clear()


    @synchronized
    def copy(self):
        copied = self.__class__()
        copied._items = self._items.copy()
        return copied


    @synchronized
    def index(self, item):
        i = bisect.bisect_left(self._items, item)
        j = bisect.bisect_right(self._items, item)
        return self._items[i : j].index(item) + i


    @synchronized
    def __len__(self):
        return len(self._items)


    @synchronized
    def __getitem__(self, index):
        return self._items[index]


    @synchronized
    def __contains__(self, item):
        i = bisect.bisect_left(self._items, item)
        j = bisect.bisect_right(self._items, item)
        return item in self._items[i : j]


    @synchronized
    def __iter__(self):
        return iter(self._items)


    @synchronized
    def __reversed__(self):
        return reversed(self._items)


    @synchronized
    def __eq__(self, sequence):
        return self._items == sequence


    @synchronized
    def __ne__(self, sequence):
        return not self.__eq__(sequence)


    @synchronized
    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self._items)


    @synchronized
    def __str__(self):
        return str(self._items)
