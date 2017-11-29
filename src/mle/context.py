
import contextlib
import abc
import logging

from .environment import Environment, ModelEnvironment, ModelNotFoundError
from . import configuration
from .callbacks import CallbackSet


__all__ = ['environ',
           'NotEnvironmentContext']


class EnvironmentProxy(abc.ABC):
    def __init__(self, environment, current_model):
        super().__init__()

        if current_model is None:
            try:
                current_model = environment.active_model
            except ModelNotFoundError:
                current_model = None
        elif not isinstance(current_model, ModelEnvironment):
            current_model = environment.model(current_model)

        if current_model is not None and environment is not current_model.environment:
            raise ValueError('environment is not current_model.environment')

        object.__setattr__(self, '_environment', environment)
        object.__setattr__(self, '_current_change_callbacks', CallbackSet())
        object.__setattr__(self, '_current_model', current_model)

        #   Keep the identifier of the model separately to disambiguate
        #   None values that may occur if the model is discarded.
        #   That is, if the current_model is supposed to alias the
        #   active model, then a _current_model == None means that the
        #   active model was not found, but if the current_model is supposed
        #   to be some fixed model, say id = 42, a _current_model == None
        #   indicates that model 42 was discarded and changes to the
        #   active_model should not be propagated to the current_model.
        current_identifier = self._get_indentifier_if_not_active(current_model)
        object.__setattr__(self, '_current_identifier', current_identifier)

        environment.add_active_model_change_callback(self._on_active_model_changed)
        environment.add_discard_model_callback(self._on_discard_model)
        environment.add_create_model_callback(self._on_create_model)


    @property
    def current_model(self):
        if self._current_model is None:
            raise ModelNotFoundError(self, self._current_identifier)
        return self._current_model


    @current_model.setter
    def current_model(self, current_model):
        if current_model is None:
            current_model = self._environment.active_model

        previous_model = None
        if isinstance(current_model, ModelEnvironment):
            if self._current_model is not current_model:
                previous_model = self._current_model
        else:
            if self._current_model.identifier != current_model:
                previous_model = self._current_model
                current_model = self._environment.model(current_model)

        if previous_model is not None:
            identifier = self._get_indentifier_if_not_active(current_model)
            object.__setattr__(self, '_current_identifier', identifier)
            object.__setattr__(self, '_current_model', current_model)
            self._current_change_callbacks(current_model, previous)


    def _get_indentifier_if_not_active(self, model):
        try:
            if model is None or model is self._environment.active_model:
                identifier = None
            else:
                identifier = model.identifier
        except ModelNotFoundError:
            identifier = model.identifier

        return identifier


    def model(self, identifier=None):
        if identifier is None:
            return self.current_model

        return self._environment.model(identifier)


    def __getattr__(self, name):
        return getattr(self._environment, name)

    def __setattr__(self, name, value):
        if name != 'current_model':
            setattr(self._environment, name, value)
        else:
            object.__setattr__(self, name, value)


    def _on_active_model_changed(self, current, previous):
        #   check _current_identifier to make sure that a None
        #   current_model is not due to discarding the current model
        if self._current_identifier is None and self.current_model is previous:
            self._current_model = current
            self._current_change_callbacks(current, previous)


    def _on_discard_model(self, model):
        if self._current_model is not None and model == self._current_model:
            previous = self._current_model
            self._current_model = None
            self._current_change_callbacks(self._current_model, previous)


    def _on_create_model(self, model):
        if self._current_model is None and model.identifier == self._current_identifier:
            previous = self._current_model
            self._current_model = self._environment.model(self._current_identifier)
            self._current_change_callbacks(self._current_model, previous)


    def add_current_model_change_callback(self, callback):
        self._current_change_callbacks.add(callback)


    def remove_current_model_change_callback(self, callback):
        self._current_change_callbacks.remove(callback)



#   make issubclass(EnvironmentProxy, Environment) true
EnvironmentProxy.register(Environment)






class CurrentModelChangedError(Exception):
    def __init__(self, environment, current, previous):
        super().__init__('current model changed: '
                         'environment = {}\current = {}\previous = {}'.format(environment.directory,
                                                                              current,
                                                                              previous))
        self.environment = environment
        self.current = current
        self.previous = previous


class NotEnvironmentContext(Exception):
    def __init__(self):
        super().__init__('code not called from within an mle.environ context')


class environ:
    """
    Context manager that overrides an Environment's default model environment

    Normally, the default model for an Environment object is the
    environment's active model.
    i.e.
    environment = Environment()
    assert environment.model() is environment.active_model

    In some situations it may be helpful to temporarily set a
    default model different from the active model.  This context
    manager provides an EnvironmentProxy object that effectively
    adds a current_model property to the given Environment object.
    The current_model property is used in lieu of the active_model as
    the default model.  That is, instead of model() aliasing active_model,
    model() aliases current_model.  All logging handled by
    mle.logging.ModelFileHandler handlers is redirected to the current
    model's log directory.

        with environ(model=10) as environment:
            assert environment.model() is environment.current_model
            assert environment.model().identifier == 10

    The difference between between providing a ModelEnvironment object
    and a model identifier is essentially the difference between equality
    and identity.

        env = Environment()

        #   create a default constructed environment that uses model 42
        model = env.model(42)
        with environ(model=42) as environment:
            #   since an integer was given to current_model,
            #   equality holds but identity does not
            assert environment.model() == environment.model(42)
            assert environment.model() is not environment.model(42)

        #   use existing Environment and ModelEnvironment objects
        model = environment.model(24)
        with environ(model, env) as environment:
            #   since a ModelEnvironment was given to current_model,
            #   both equality and identity hold
            assert environment.model() == model
            assert environment.model() is model

            #   but since environment.model(24) creates a new object
            assert environment.model() == environment.model(42)
            assert environment.model() is not environment.model(42)



    If None is provided for the model the active model is used.

        with environ() as environment:
            assert environment.current_model is environment.active_model

    If the value 'new' is passed to the model argument, a new model
    environment is created with environment.create_model().

    When the model argument is an integer or a ModelEnvironment objects,
    a ModelNotFoundError is raised if the model environment does not exist.
    A None value will never result in a ModelNotFoundError exception,
    even if the environment does not have an active model.  Instead,
    accessing the current_model property or calling the model() method
    from inside the body of the with statement will result in a
    ModelNotFoundError.  This allows subclasses to set the current_model
    property after the context has been initialized via
    environ.__init__(model=None) but prior to calling environ.__enter__().

        env = Environment()
        env.active_model = None

        with environ(environment=env) as environment:
            try:
                environment.current_model
            except ModelNotFoundError:
                assert True
            else:
                assert False

    If the current model is changed after entering the context
    a CurrentModelChangedError is raised.

        try:
            with environ(model=42) as environment:
                environment.current_model = 24
        except CurrentModelChangedError:
            assert True
        else:
            assert False

    A CurrentModelChangedError can occur indirectly when the current
    model aliases the active model and the active model is changed
    from inside the with statement, from another part of the program,
    or from outside the program by modifying the symbolic link to
    the active model's directory.  A CurrentModelChangedError may
    also occur if the current_model is discarded and/or removed from
    the file system.


    The save argument takes a string that determines when the environment
    and current model are saved.  It defaults to 'exit', in which case
    both objects are saved when the context exits.  Other options are
    'exit_no_errors', 'immediate', and 'never'.  See configuration.saved
    for more information.


    Example:
        #   suppose your application has a load_model_from_file() function
        #   and a save_model_to_file() function that serializes/deserializes
        #   some type of model object to/from a file.
        #   use environ.top() to get the running context's current model
        def save_model(model, filename):
            try:
                save_model_to_file(model, environ.top().model().path(filename))
            except NotEnvironmentContext:
                save_model_to_file(model, filename)

        def load_model(filename):
            try:
                return load_model_from_file(environ.top().model().path(filename))
            except NotEnvironmentContext:
                return load_model_from_file(filename)


        #   create and train a model by varying the learning rate
        #   since training may take a long time, activate each new model
        #   identifier so that training can be easily monitored externally
        #   by accessing the symbolic link that points to the active model
        #   environment's directory
        log = logging.getLogger('train')
        log.addHandler(mle.logging.ModelFileHandler('train.log'))

        for learning_rate in learning_rates():
            with environ(model='new', activate=True) as environment:
                #   set some model environment variables, these will be
                #   saved when the context exits
                environment.current_model['learning_rate'] = learning_rate

                #   create and train the model with application specific functions
                model = create_some_model()
                training_stats = do_some_training(model, environment)

                #   write the training stats to the summary file
                with environment.model().summary_path.open('w') as file:
                    file.write(str(training_stats))

                #   save the model to the current model directory
                save_model(model, 'some.model')

                #   all logging is automatically routed to the current
                #   model's log directory
                log.info('write some info to environment.model().log_path('train.log')')


        #   iteratively evaluate these models
        log = logging.getLogger('eval')
        log.addHandler(mle.logging.ModelFileHandler('eval.log'))

        for identifier in range(10):
            with environ(model=identifier) as environment:
                #   load the model from the current model directory
                model = load_model('some.model')

                #   do some evaluation with application specific functions
                evaluation_stats = do_some_evaluation(model, environment)
                print(evaluation_stats)

                #   write the evaulation statistics to the summary file
                with environment.model().summary_path.open('a') as file:
                    file.write(str(evaluation_stats))

                #   all logging is automatically routed to the current
                #   model's log directory
                log.info('write some info to environment.model().log_path('eval.log')')

    Args:
        model: a ModelEnvironment object, identifier, 'new', or None
            if None, the environment's active model is used
            if 'new', a Environment.create_model() is used
        environment: Environment object, path, or None
            If a path or None is given, it is used to construct
            an Environment object
        save(str): policy used to save the environment and the model environment
            (see configuration.saved)
        activate(bool): if True, the active_model is set to the current_model
    """
    _stack = list()

    def __init__(self, model, environment=None, *, save='exit', activate=False):
        if not isinstance(environment, Environment):
            environment = Environment(environment)

        if model == 'new':
            model = environment.create_model()

        self.environment = EnvironmentProxy(environment, model)

        self.environment_saver = configuration.saved(self.environment, save)
        self.model_saver = configuration.saved(None, save)

        self.activate = activate
        self._model_file_log_handlers = dict()


    @classmethod
    def top(cls):
        """
        The current context's environment object

        This is used by functions defined outside of this class to
        access the context's environment.  For example, a save_model
        function might consider its file path argument as being relative
        to the context's current model path.

        def save_model(model, filepath):
            filepath = environ.top().model().path(filepath)
            ...

        Returns:
            The Environment object used in the most recent instance
            of the context manager.

        Raises:
            NotEnvironmentContext no current environ context
        """
        try:
            return cls._stack[-1]
        except IndexError:
            raise NotEnvironmentContext() from None


    def _raise_error_on_model_environment_changed(self, current, previous):
        raise CurrentModelChangedError(self.environment, current, previous)


    def _update_model_file_logging_handlers(self):
        from .logging import model_environment_file_handlers
        for handler in model_environment_file_handlers()
            self._model_file_log_handlers[handler] = handler.environment
            handler.environment = self.environment


    def _restore_model_file_logging_handlers(self):
        for handler, environment in self._model_file_log_handlers.items():
            handler.environment = environment


    def __enter__(self):
        self._update_model_file_logging_handlers()

        try:
            if self.activate:
                self.environment.active_model = self.environment.current_model

            self.model_saver.configuration = self.environment.current_model
            self.environment_saver.__enter__()
            self.model_saver.__enter__()

            self.environment.add_current_model_change_callback(self._raise_error_on_model_environment_changed)
            environ._stack.append(self.environment)
        except Exception:
            self._restore_model_file_logging_handlers()
            raise

        return self.environment


    def __exit__(self, exception_type, exception_value, traceback):
        try:
            self.environment_saver.__exit__(exception_type, exception_value, traceback)
        finally:
            try:
                self.model_saver.__exit__(exception_type, exception_value, traceback)
            finally:
                try:
                    self._restore_model_file_logging_handlers()
                finally:
                    environ._stack.pop()

