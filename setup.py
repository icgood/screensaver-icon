
from setuptools import setup, find_packages

from screensavericon import _VERSION

setup(name='screensaver-icon',
      version=_VERSION,
      description='Displays an icon to control xscreensaver.',
      author='Ian Good',
      author_email='ian.good@rackspace.com',
      packages=find_packages(),
      package_data={'screensavericon': ['icons/*.png']},
      entry_points={'console_scripts': [
              'screensaver-icon = screensavericon:main',
          ]})

# vim:et:fdm=marker:sts=4:sw=4:ts=4
