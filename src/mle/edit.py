
import os
import subprocess
import pathlib


#def open_editor(filepath, editor_key='editor', config=None):
    #"""
    #Open a file in an editor
    #"""
    #suffix = pathlib.Path(str(filepath)).suffix
    #if suffix:
        #editor_key_with_suffix = editor_key + suffix

    #editor = None
    #if suffix:
        #editor = os.environ.get('MLE_' + editor_key_with_suffix.upper().replace('.', '_'))
    #if not editor:
        #editor = os.environ.get('MLE_' + editor_key.upper().replace('.', '_'))

    #if not editor:
        #if config is None:
            #from . import environment
            #try:
                #config = environment.local_configuration()
            #except environment.ConfigurationNotFoundError:
                #try:
                    #config = environment.global_configuration()
                #except environment.ConfigurationNotFoundError:
                    #try:
                        #config = environment.system_configuration()
                    #except environment.ConfigurationNotFoundError:
                        #config = environment.DEFAULT_GLOBAL_CONFIGURATION

        #if suffix:
            #editor = config.get(editor_key_with_suffix)
        #if not editor:
            #editor = config.get(editor_key)

        #if not editor:
            #if suffix:
                #message = '{} and {} are not set'.format(editor_key_with_suffix, editor_key)
            #else:
                #message = '{} is not set'.format(editor_key)
            #raise KeyError(message)

    #subprocess.run([editor, str(filepath)])



def open_editor(filepath, editor_key='editor', config=None):
    """
    Open a file in an editor
    """
    suffix = pathlib.Path(str(filepath)).suffix
    if suffix:
        editor_key_with_suffix = editor_key + suffix

    editor = None

    #   try MLE_EDITORKEY_SUFFIX os environment variable
    if suffix:
        editor = os.environ.get('MLE_' + editor_key_with_suffix.upper().replace('.', '_'))

    #   if config wasn't given, get the most local configuration
    #   relative to the current directory
    if not editor and config is None:
        from . import environment
        try:
            config = environment.local_configuration()
        except environment.ConfigurationNotFoundError:
            try:
                config = environment.global_configuration()
            except environment.ConfigurationNotFoundError:
                try:
                    config = environment.system_configuration()
                except environment.ConfigurationNotFoundError:
                    config = environment.DEFAULT_CONFIGURATION

    #   try configuration's editorkey.suffix variable
    if not editor and suffix:
        editor = config.get(editor_key_with_suffix)

    #   try MLE_EDITORKEY os environment variable
    if not editor:
        editor = os.environ.get('MLE_' + editor_key.upper().replace('.', '_'))

    #   try configuration's editorkey variable
    if not editor:
        editor = config.get(editor_key)

    if not editor:
        if suffix:
            message = '{} and {} are not set'.format(editor_key_with_suffix, editor_key)
        else:
            message = '{} is not set'.format(editor_key)
        raise KeyError(message)

    subprocess.run([editor, str(filepath)])














