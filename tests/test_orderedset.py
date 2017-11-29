
import random

import pytest

import mle.orderedset



class TestOrderedSet:
    @pytest.fixture(params=[(0, True, True),
                            (10, True, True),
                            (10, False, True),
                            (10, True, False),
                            (10, False, False)])
    def items(self, request):
        length, unique, sort = request.param

        items = list(range(0, 2 * length, 2))
        if not unique:
            while list(set(items)) == items:
                items = (items + items)
                random.shuffle(items)
                items = items[:length]
        else:
            random.shuffle(items)

        if sort:
            items = sorted(items)

        return items


    @pytest.fixture
    def ordered_set(self, items):
        return mle.orderedset.OrderedSet(items)


    def test_length(self, ordered_set, items):
        items = sorted(set(items))
        assert len(ordered_set) == len(items)
        if items:
            assert ordered_set
        else:
            assert not ordered_set


    def test_equals(self, ordered_set, items):
        items = sorted(set(items))
        assert ordered_set == ordered_set
        assert ordered_set == items


    def test_not_equals(self, ordered_set, items):
        if items:
            items = sorted(set(items))
            assert ordered_set != items[:-1]
            items[0] = max(items) + 1
            assert ordered_set != items


    def test_iteration(self, ordered_set, items):
        assert sorted(set(items)) == list(iter(ordered_set))


    def test_reversed(self, ordered_set, items):
        assert list(reversed(ordered_set)) == list(reversed(sorted(set(items))))
        assert list(reversed(ordered_set)) == list(reversed(list(ordered_set)))


    def test_contains(self, ordered_set, items):
        for item in ordered_set:
            assert item in ordered_set

        for item in items:
            assert item in ordered_set

        assert self.new_back_item(items) not in ordered_set
        assert self.new_front_item(items) not in ordered_set


    def test_getitem(self, ordered_set, items):
        items = sorted(set(items))
        for index, item in enumerate(items):
            assert ordered_set[index] == item


    def test_index(self, ordered_set, items):
        items = sorted(set(items))
        for index, item in enumerate(items):
            assert ordered_set.index(item) == index


    def test_clear(self, ordered_set, items):
        ordered_set.clear()
        assert len(ordered_set) == 0
        self.verify_constraints(ordered_set)


    def test_copy(self, ordered_set, items):
        copied = ordered_set.copy()
        assert ordered_set == copied
        assert ordered_set is not copied

        self.verify_constraints(copied)


    def test_add_to_front(self, ordered_set, items):
        length = len(ordered_set)
        item = self.new_front_item(items)
        assert item not in ordered_set
        if ordered_set:
            assert item < ordered_set[0]

        ordered_set.add(item)
        self.verify_add(ordered_set, item, length + 1)
        self.verify_constraints(ordered_set)


    def test_add_to_back(self, ordered_set, items):
        length = len(ordered_set)
        item = self.new_back_item(items)
        assert item not in ordered_set
        if ordered_set:
            assert item > ordered_set[-1]

        ordered_set.add(item)
        self.verify_add(ordered_set, item, length + 1)
        self.verify_constraints(ordered_set)


    def test_add_to_middle(self, ordered_set, items):
        length = len(ordered_set)
        item = self.new_middle_item(items)
        assert item not in ordered_set
        if ordered_set:
            assert ordered_set[0] < item < ordered_set[-1]

        ordered_set.add(item)
        self.verify_add(ordered_set, item, length + 1)
        self.verify_constraints(ordered_set)


    def test_add_existing(self, ordered_set, items):
        if items:
            length = len(ordered_set)

            item = items[0]
            ordered_set.add(item)
            self.verify_add(ordered_set, item, length)
            self.verify_constraints(ordered_set)

            item = items[len(items) // 2]
            ordered_set.add(item)
            self.verify_add(ordered_set, item, length)
            self.verify_constraints(ordered_set)

            item = items[-1]
            ordered_set.add(item)
            self.verify_add(ordered_set, item, length)
            self.verify_constraints(ordered_set)


    def test_remove_from_front(self, ordered_set, items):
        if items:
            length = len(ordered_set)
            item = items[0]
            ordered_set.discard(item)
            self.verify_remove(ordered_set, item, length - 1)
            self.verify_constraints(ordered_set)


    def test_remove_from_back(self, ordered_set, items):
        if items:
            length = len(ordered_set)
            item = items[-1]
            ordered_set.discard(item)
            self.verify_remove(ordered_set, item, length - 1)
            self.verify_constraints(ordered_set)


    def test_remove_from_middle(self, ordered_set, items):
        if items:
            length = len(ordered_set)
            item = items[len(items) // 2]
            ordered_set.discard(item)
            self.verify_remove(ordered_set, item, length - 1)
            self.verify_constraints(ordered_set)


    def test_remove_non_existing(self, ordered_set, items):
        length = len(ordered_set)
        item = min(items) - 1 if items else 0
        assert item not in ordered_set
        with pytest.raises(ValueError):
            ordered_set.discard(item)

        self.verify_remove(ordered_set, item, length)
        self.verify_constraints(ordered_set)


    def verify_add(self, ordered_set, item, length):
        assert item in ordered_set
        assert len(ordered_set) == length


    def verify_remove(self, ordered_set, item, length):
        assert item not in ordered_set
        assert len(ordered_set) == length

    def new_front_item(self, items):
        return min(items) - 1 if items else 0

    def new_back_item(self, items):
        return max(items) + 1 if items else 0

    def new_middle_item(self, items):
        if items:
            item = items[len(items) // 4]

            item = random.randrange(min(items) + 1, max(items))
            while item in items:
                item = random.randrange(min(items), max(items))

            assert min(items) < item < max(items)
        else:
            item = 0

        assert item not in items
        return item


    @staticmethod
    def verify_constraints(ordered_set):
        assert ordered_set == sorted(set(ordered_set))













