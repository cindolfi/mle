# pylint: disable=bad-whitespace
"""
Setup machine learning environment tools
"""

from setuptools import setup, find_packages
import glob


CLASSIFIERS = ['Development Status :: 2 - Pre-Alpha',
               'Programming Language :: Python :: 3.5']

setup(
    name = 'mle',
    version = '0.1.0',
    description = 'Tools for managing a machine learning environment',
    author = 'Chris Indolfi',
    author_email = 'indolfc@sunyit.edu',
    classifiers = CLASSIFIERS,
    package_dir = {'': 'src'},
    packages = ['mle'],
    entry_points = dict(console_scripts=['mle = mle.__main__:main']),
    python_requires = '>=3.5',
    scripts = glob.glob('bin/*'),
)


